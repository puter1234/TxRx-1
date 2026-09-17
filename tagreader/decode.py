"""바코드 값 디코딩 (zxing-cpp).

핵심은 '전체 이미지가 아니라 바코드 주변만 스캔한다'는 것이다. 12MP 사진 전체를
zxing에 넘기면 300~700ms가 걸리지만, 바코드 quad 주변만 잘라 넘기면 10ms 이하다.
"""
import cv2
import numpy as np
import zxingcpp

from .geometry import deskew_angle, quad_radius

# 택에 쓰이는 1D 포맷만 켠다. 전체 포맷을 열어두면 느려지는 데다,
# 높이 1px짜리 Code 39 같은 오검출이 섞여 들어온다.
FORMATS = zxingcpp.barcode_formats_from_str("Code93|Code128|Code39|ITF")

# 이보다 짧은 것은 노이즈로 본다 (원본 해상도 기준 픽셀).
MIN_SPAN_PX = 40

# 바코드 quad 주변으로 이만큼 더 잘라낸다. 여백(quiet zone)이 있어야 디코딩된다.
ROI_PAD = 0.45

# ROI가 이보다 작으면 확대해서 한 번 더 시도한다.
UPSCALE_TO = 900


def _span(barcode) -> float:
    """감지된 바코드의 윗변 길이. 세로로 선 바코드도 걸러지지 않도록 x폭이 아닌 실제 길이를 쓴다."""
    p0, p1 = barcode.position.top_left, barcode.position.top_right
    return float(np.hypot(p1.x - p0.x, p1.y - p0.y))


def scan(img: np.ndarray, min_span: float = MIN_SPAN_PX) -> list:
    """zxing으로 이미지를 스캔한다. try_downscale/try_invert는 택 사진에 불필요해 끈다."""
    results = zxingcpp.read_barcodes(
        img, formats=FORMATS, try_downscale=False, try_invert=False,
    )
    return [b for b in results if _span(b) > min_span]


def decode_quad(gray: np.ndarray, quad: np.ndarray, pad: float = ROI_PAD):
    """quad 주변만 잘라 회전 보정 후 디코딩한다. (값, 포맷) 또는 (None, None)."""
    angle = deskew_angle(quad)
    cx, cy = quad.mean(axis=0)
    half = quad_radius(quad) * (1 + pad)

    x0, y0 = int(max(0, cx - half)), int(max(0, cy - half))
    x1, y1 = int(min(gray.shape[1], cx + half)), int(min(gray.shape[0], cy + half))
    roi = gray[y0:y1, x0:x1]
    if roi.size == 0:
        return None, None

    # 정사각 ROI를 중심 기준으로 돌리므로 캔버스를 넓히지 않아도 바코드가 잘리지 않는다.
    M = cv2.getRotationMatrix2D((roi.shape[1] / 2, roi.shape[0] / 2), angle, 1.0)
    rotated = cv2.warpAffine(
        roi, M, (roi.shape[1], roi.shape[0]), flags=cv2.INTER_LINEAR, borderValue=255
    )

    found = scan(rotated)
    if not found and max(rotated.shape) < UPSCALE_TO:
        factor = UPSCALE_TO / max(rotated.shape)
        enlarged = cv2.resize(rotated, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
        found = scan(enlarged, min_span=MIN_SPAN_PX * factor)

    if not found:
        return None, None
    return found[0].text, str(found[0].format)
