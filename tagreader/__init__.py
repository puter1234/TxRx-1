"""택(의류 라벨) 사진에서 바코드 값과 OCR용 텍스트 영역을 뽑아내는 리더.

공개 API는 read_tag() 하나다. BGR ndarray를 받아 TagResult 리스트를 돌려준다.

    import cv2, tagreader
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)      # 디코드는 한 번만
    for tag in tagreader.read_tag(img):
        print(tag.text)                             # 바코드 값
        ocr_engine(tag.above)                       # 위쪽 텍스트 (BGR ndarray)

파일 경로가 아니라 ndarray를 받는 이유: 12MP JPEG 디코드가 ~125ms라 OCR과
두 번 하면 그것만으로 예산을 갉아먹는다. 한 프로세스에서 한 번 디코드해 공유한다.
"""
from dataclasses import dataclass, field
import time

import cv2
import numpy as np

from .crop import RotationCache, crop_around, draw_debug
from .decode import decode_quad, scan
from .detect import candidate_tiers
from .geometry import deskew_angle, transform_points

__all__ = ["TagResult", "read_tag", "read_barcode_values"]


@dataclass
class TagResult:
    """택 한 장의 인식 결과. above/below가 OCR 입력이다."""

    text: str | None
    """디코딩된 바코드 값. 위치는 찾았지만 값을 못 읽었으면 None."""

    format: str | None = None
    """바코드 심볼로지 (예: 'Code 93')."""

    angle: float = 0.0
    """수평 보정에 적용한 회전각(도)."""

    quad: np.ndarray | None = None
    """원본 좌표계에서의 바코드 4점."""

    above: np.ndarray | None = None
    """바코드 위쪽 텍스트 영역 (BGR). want_crops=False면 None."""

    below: np.ndarray | None = None
    """바코드 아래쪽 텍스트 영역 (BGR)."""

    rotated: np.ndarray | None = None
    """회전 보정된 이미지 전체. 택을 통짜로 OCR에 넣고 싶을 때 쓴다."""

    stage: str = ""
    """값을 찾아낸 감지 단계 ('small' | 'full' | 'tiled' | 'whole-image')."""

    _rotated_quad: np.ndarray | None = field(default=None, repr=False)
    """rotated 좌표계로 옮긴 quad. debug_view()에서만 쓴다."""

    def debug_view(self, **kwargs) -> np.ndarray | None:
        """바코드 박스와 크롭 영역을 그린 진단용 이미지. want_rotated=True로 읽었을 때만 나온다."""
        if self.rotated is None or self._rotated_quad is None:
            return None
        return draw_debug(self.rotated, self._rotated_quad, **kwargs)


def read_tag(
    img: np.ndarray,
    *,
    want_crops: bool = True,
    want_rotated: bool = False,
    margin_above: float = 1.2,
    margin_below: float = 1.2,
    full_width: bool = True,
    x_pad_ratio: float = 0.15,
    max_barcodes: int = 4,
    diagnostics: dict | None = None,
    decode_values: bool = True,
) -> list[TagResult]:
    """사진에서 바코드를 찾아 값을 읽고, OCR용 위/아래 크롭을 만든다.

    decode_values=False면 위치를 찾는 즉시 원본 영역을 OCR용으로 정렬한다.
    이때 바코드 값 판독과 판독 실패에 따른 재검색은 실행하지 않는다.
    decode_values=True면 기존 값 판독 경로를 사용한다.

    want_crops=False로 두면 크롭 생성을 건너뛰어 더 빠르다 (값만 필요할 때).
    """
    prepared = time.perf_counter()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    if diagnostics is not None:
        diagnostics.update(stages=[], status="not_detected", decoded=0,
                           prepare_ms=(time.perf_counter() - prepared) * 1000, align_ms=0.0)

    hits: list[tuple[str | None, str | None, np.ndarray]] = []
    stage = ""
    detector_options = {"first_only": True} if not decode_values else {}
    if diagnostics is not None:
        detector_options["diagnostics"] = diagnostics["stages"]
    tiers = candidate_tiers(gray, **detector_options)
    for stage, quads in tiers:
        started = time.perf_counter()
        decoded = 0
        for quad in quads[:max_barcodes]:
            if not decode_values:
                hits.append((None, None, quad))
                continue
            text, fmt = decode_quad(gray, quad)
            if text:
                hits.append((text, fmt, quad))
                decoded += 1
        if diagnostics is not None:
            diagnostics["stages"][-1].update(
                decode_ms=(time.perf_counter() - started) * 1000 if decode_values else 0.0,
                attempted=min(len(quads), max_barcodes) if decode_values else 0, decoded=decoded)
        if hits:
            break

    if not hits:
        if not decode_values:
            return []
        started = time.perf_counter()
        found = scan(gray)
        if diagnostics is not None:
            diagnostics["status"] = ("decode_failed" if any(
                row["candidates"] for row in diagnostics["stages"]) else "not_detected")
            diagnostics["stages"].append({
                "stage": "whole-image", "candidates": 0, "attempted": 1,
                "detect_ms": 0.0, "decode_ms": (time.perf_counter() - started) * 1000,
                "decoded": len(found)})
        if not found:
            return []
        if diagnostics is not None:
            diagnostics.update(status="decoded", decoded=len(found))
        # ZXing returns barcode corners even when OpenCV's detector misses it.
        # Keep those corners so OCR can deskew and search beside the barcode.
        for barcode in found[:max_barcodes]:
            position = barcode.position
            quad = np.array([
                [getattr(position, name).x, getattr(position, name).y]
                for name in ("top_left", "top_right", "bottom_right", "bottom_left")
            ], dtype=np.float64)
            height = (np.linalg.norm(quad[3] - quad[0]) +
                      np.linalg.norm(quad[2] - quad[1])) / 2
            if height >= 4:
                hits.append((barcode.text, str(barcode.format), quad))
        if not hits:
            return [TagResult(text=found[0].text, format=str(found[0].format), stage="whole-image")]
        stage = "whole-image"

    if diagnostics is not None:
        diagnostics.update(status="decoded" if decode_values else "located",
                           decoded=sum(bool(text) for text, _, _ in hits))

    if not (want_crops or want_rotated):
        return [
            TagResult(text=t, format=f, angle=deskew_angle(q), quad=q, stage=stage)
            for t, f, q in hits
        ]

    aligned = time.perf_counter()
    cache = RotationCache(img)
    results = []
    for text, fmt, quad in hits:
        angle = deskew_angle(quad)
        rotated, M = cache.get(angle)
        rquad = transform_points(quad, M)
        above = below = None
        if want_crops:
            above, below = crop_around(
                rotated, rquad, margin_above, margin_below, full_width, x_pad_ratio
            )
        results.append(TagResult(
            text=text, format=fmt, angle=angle, quad=quad,
            above=above, below=below,
            rotated=rotated if want_rotated else None,
            stage=stage, _rotated_quad=rquad,
        ))
    if diagnostics is not None:
        diagnostics["align_ms"] = (time.perf_counter() - aligned) * 1000
    return results


def read_barcode_values(img: np.ndarray) -> list[str]:
    """바코드 값만 빠르게 필요할 때 쓰는 단축 함수."""
    return [r.text for r in read_tag(img, want_crops=False) if r.text]
