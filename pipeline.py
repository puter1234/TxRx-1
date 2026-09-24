"""Task 단위 통합 파이프라인: 택 사진 1장 -> 바코드 + 인쇄 시리얼 OCR + 대조 판정.

Task = 택 사진 한 장. 처리 결과는 세 가지다.

    1. 바코드 값        (tagreader, CPU)
    2. 인쇄된 시리얼    (ocr/PARSeq, GPU)
    3. 둘의 대조 판정    (ocr.normalize)

두 엔진이 자원을 나눠 쓴다: 바코드는 순수 CPU(OpenCV + zxing), OCR만 GPU를 쓴다.
JPEG 디코드는 한 번만 하고 ndarray를 두 엔진이 공유한다.
"""
import time
from dataclasses import dataclass, field
from itertools import zip_longest

import cv2
import numpy as np
from PIL import Image

import tagreader
from tagreader.crop import rotate_text_region
from ocr import Recognizer, Verdict, compare, find_text_lines
from ocr.normalize import normalize_loose, normalize_strict

# 바코드 위/아래로 텍스트를 찾을 범위 (바코드 높이 대비 배수).
SEARCH_MARGIN = 1.6

# 텍스트 탐색 x범위를 바코드 폭 기준으로 넓히는 비율.
# 인쇄 시리얼은 바코드와 같은 폭으로 찍히므로, 여기를 넓히면 배경 노이즈만 들어온다.
X_PAD_RATIO = 0.10


@dataclass
class TagRead:
    """택 한 장(바코드 하나)에 대한 인식 결과."""

    barcode: str | None
    barcode_format: str | None
    angle: float
    stage: str
    verdict: Verdict
    lines: list[dict] = field(default_factory=list)   # OCR한 줄들 [{text, confidence, ms}]
    line_crops: list[np.ndarray] = field(default_factory=list)
    crop: np.ndarray | None = None                    # 판정 근거가 된 줄 크롭 (BGR)
    band: np.ndarray | None = None                    # 바코드 주변 밴드 (디버깅/표시용)


@dataclass
class TaskResult:
    reads: list[TagRead]
    ms_decode: float = 0.0
    ms_barcode: float = 0.0
    ms_ocr: float = 0.0
    ms_total: float = 0.0
    error: str | None = None


def _band_of(rotated: np.ndarray, rquad: np.ndarray):
    """바코드 위/아래 밴드와 글자 높이 기준값을 돌려준다."""
    xs, ys = rquad[:, 0], rquad[:, 1]
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    bar_h, bar_w = y1 - y0, x1 - x0

    h, w = rotated.shape[:2]
    pad = int(bar_w * X_PAD_RATIO)
    left, right = max(0, x0 - pad), min(w, x1 + pad)

    above = rotated[max(0, y0 - int(bar_h * SEARCH_MARGIN)):y0, left:right]
    below = rotated[y1:min(h, y1 + int(bar_h * SEARCH_MARGIN)), left:right]
    return above, below, bar_h


def _ordered_crops(above: np.ndarray, below: np.ndarray, bar_h: float, max_lines: int):
    """바코드에 가까운 줄이 앞에 오도록 정렬한다.

    above는 아래쪽 줄이(바코드에 붙은 쪽), below는 위쪽 줄이 바코드에 가깝다.
    """
    near_above = list(reversed(find_text_lines(above, bar_h, max_lines=max_lines)))
    near_below = find_text_lines(below, bar_h, max_lines=max_lines)

    ordered = []
    for pair in zip_longest(near_above, near_below):
        ordered += [c for c in pair if c is not None]
    return ordered[:max_lines]


def process_task(
    img: np.ndarray,
    recognizer: Recognizer | None,
    *,
    max_lines: int = 6,
    diagnostics: dict | None = None,
    decode_values: bool = True,
) -> TaskResult:
    """사진 한 장을 Task로 처리한다. recognizer가 None이면 바코드만 읽는다."""
    t_start = time.perf_counter()

    t0 = time.perf_counter()
    kwargs = {"diagnostics": diagnostics} if diagnostics is not None else {}
    if not decode_values:
        kwargs["decode_values"] = False
    tags = tagreader.read_tag(img, want_crops=False, want_rotated=decode_values, **kwargs)
    if not decode_values:
        aligned = time.perf_counter()
        for tag in tags:
            tag.rotated, tag._rotated_quad = rotate_text_region(
                img, tag.quad, tag.angle, SEARCH_MARGIN, X_PAD_RATIO)
        if diagnostics is not None:
            diagnostics["align_ms"] = (time.perf_counter() - aligned) * 1000
    ms_barcode = (time.perf_counter() - t0) * 1000

    if not tags:
        return TaskResult(
            reads=[], ms_barcode=ms_barcode,
            ms_total=(time.perf_counter() - t_start) * 1000,
            error=("바코드 위치를 찾지 못했습니다" if not decode_values else
                   "바코드 후보 위치는 찾았지만 값을 읽지 못했습니다"
                   if diagnostics and diagnostics.get("status") == "decode_failed"
                   else "바코드 위치와 값을 찾지 못했습니다"),
        )

    reads, ms_ocr = [], 0.0
    for tag in tags:
        lines, best_crop, crops = [], None, []

        if recognizer is not None and tag.rotated is not None and tag._rotated_quad is not None:
            above, below, bar_h = _band_of(tag.rotated, tag._rotated_quad)
            # 택마다 상품코드 위치가 다르므로 위/아래 후보를 유지한다.
            crops = _ordered_crops(above, below, bar_h, max_lines)

            target = normalize_strict(tag.text) if tag.text else None
            outputs = None
            device = str(getattr(recognizer, "device", "cpu"))
            if crops and target is None and device.split(":")[0] == "cuda":
                t0 = time.perf_counter()
                images = [Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)) for crop in crops]
                outputs = recognizer.read_batch(images)
                if len(outputs) != len(crops):
                    raise RuntimeError("OCR 결과 수가 입력한 글자 줄 수와 다릅니다.")
                ms_ocr += (time.perf_counter() - t0) * 1000
            for index, crop in enumerate(crops):
                if outputs is None:
                    t0 = time.perf_counter()
                    image = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
                    out = recognizer.read(image)
                    ms_ocr += (time.perf_counter() - t0) * 1000
                else:
                    out = outputs[index]
                lines.append({"text": out["text"], "confidence": out["confidence"],
                              "min_char": out.get("min_char"), "chars": out.get("chars", []), "ms": out["ms"],
                              "batch_size": out.get("batch_size", 1), "batch_ms": out.get("batch_ms", out["ms"]),
                              "timing": out.get("timing", "single")})
                if best_crop is None:
                    best_crop = crop
                # 바코드 값과 구분자만 다른 줄을 찾았으면 나머지는 읽을 이유가 없다.
                # 무작위 텍스트가 시리얼과 우연히 완전일치할 확률은 사실상 0이라 조기 종료가 안전하다.
                if target and (normalize_strict(out["text"]) == target or
                               normalize_loose(out["text"]) == normalize_loose(tag.text)):
                    best_crop = crop
                    break

            if decode_values:
                verdict = compare(tag.text, [(l["text"], l["confidence"]) for l in lines])
            else:
                usable = [line for line in lines if normalize_strict(line["text"])]
                if usable:
                    strongest = max(usable, key=lambda line: line["confidence"])
                    verdict = Verdict("ocr_read", None, strongest["text"],
                                      strongest["confidence"], "문자 읽음")
                else:
                    verdict = Verdict("no_text", None, None, label="문자 미검출")
            for line, crop in zip(lines, crops):
                if verdict.text is not None and line["text"] == verdict.text:
                    best_crop = crop
                    break
        else:
            verdict = (compare(tag.text, []) if decode_values else
                       Verdict("no_text", None, None, label="문자 미검출"))

        reads.append(TagRead(
            barcode=tag.text, barcode_format=tag.format, angle=tag.angle, stage=tag.stage,
            verdict=verdict, lines=lines, line_crops=crops[:len(lines)] if recognizer is not None else [], crop=best_crop,
            band=_band_of(tag.rotated, tag._rotated_quad)[0] if tag.rotated is not None else None,
        ))

    return TaskResult(
        reads=reads,
        ms_barcode=ms_barcode,
        ms_ocr=ms_ocr,
        ms_total=(time.perf_counter() - t_start) * 1000,
        error=("바코드 위치를 찾지 못했습니다" if recognizer is not None and
               all(tag.rotated is None or tag._rotated_quad is None for tag in tags)
               else None),
    )
