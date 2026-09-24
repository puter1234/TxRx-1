"""원본 카메라 프레임에서 바코드를 한 번 읽는다."""
import numpy as np
import zxingcpp

# 의류 택에서 쓰는 형식만 검사해 판독 시간을 제한한다.
FORMATS = zxingcpp.barcode_formats_from_str("Code93|Code128|Code39|ITF")

def scan(img: np.ndarray) -> list:
    """원본 프레임에서 지원 중인 의류 택 형식만 한 번 읽는다."""
    return zxingcpp.read_barcodes(
        img, formats=FORMATS, try_downscale=False, try_invert=False,
    )
