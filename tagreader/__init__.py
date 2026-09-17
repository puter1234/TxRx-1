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
) -> list[TagResult]:
    """사진에서 바코드를 찾아 값을 읽고, OCR용 위/아래 크롭을 만든다.

    감지는 싼 단계부터 시도해 값이 읽히면 멈춘다. 값을 하나도 못 읽으면 마지막으로
    이미지 전체를 스캔한다 (이 경로는 크롭을 만들 수 없어 text만 채워진다).

    want_crops=False로 두면 크롭 생성을 건너뛰어 더 빠르다 (값만 필요할 때).
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img

    hits: list[tuple[str, str, np.ndarray]] = []
    stage = ""
    for stage, quads in candidate_tiers(gray):
        for quad in quads[:max_barcodes]:
            text, fmt = decode_quad(gray, quad)
            if text:
                hits.append((text, fmt, quad))
        if hits:
            break

    if not hits:
        found = scan(gray)
        if not found:
            return []
        return [TagResult(text=found[0].text, format=str(found[0].format), stage="whole-image")]

    if not (want_crops or want_rotated):
        return [
            TagResult(text=t, format=f, angle=deskew_angle(q), quad=q, stage=stage)
            for t, f, q in hits
        ]

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
    return results


def read_barcode_values(img: np.ndarray) -> list[str]:
    """바코드 값만 빠르게 필요할 때 쓰는 단축 함수."""
    return [r.text for r in read_tag(img, want_crops=False) if r.text]
