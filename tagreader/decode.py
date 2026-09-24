"""원본 카메라 프레임에서 바코드를 한 번 읽는다."""
import numpy as np
import zxingcpp

def scan(img: np.ndarray) -> list:
    """원본 프레임을 모든 표준 바코드 형식으로 한 번 읽는다."""
    return zxingcpp.read_barcodes(img, try_downscale=False, try_invert=False)
