"""바코드 값 디코딩 (zxing-cpp).

핵심은 '전체 이미지가 아니라 바코드 주변만 스캔한다'는 것이다. 12MP 사진 전체를
zxing에 넘기면 300~700ms가 걸리지만, 바코드 quad 주변만 잘라 넘기면 10ms 이하다.
"""
import numpy as np
import zxingcpp

# 택에 쓰이는 1D 포맷만 켠다. 전체 포맷을 열어두면 느려지는 데다,
# 높이 1px짜리 Code 39 같은 오검출이 섞여 들어온다.
FORMATS = zxingcpp.barcode_formats_from_str("Code93|Code128|Code39|ITF")

# 이보다 짧은 것은 노이즈로 본다 (원본 해상도 기준 픽셀).
MIN_SPAN_PX = 40

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
