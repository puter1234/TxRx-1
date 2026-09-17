"""이미지 입출력 헬퍼 (Windows 유니코드 경로 대응)."""
from pathlib import Path

import cv2
import numpy as np

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def imread(path: str | Path) -> np.ndarray | None:
    """cv2.imread는 Windows에서 한글 경로를 못 읽는 경우가 있어 우회한다."""
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def imwrite(path: str | Path, img: np.ndarray) -> bool:
    """cv2.imwrite의 유니코드 경로 대응 버전."""
    path = Path(path)
    ok, buf = cv2.imencode(path.suffix or ".png", img)
    if not ok:
        return False
    buf.tofile(str(path))
    return True


def imdecode(buf: bytes) -> np.ndarray | None:
    """업로드된 바이트를 BGR ndarray로. 디스크를 거치지 않는다."""
    return cv2.imdecode(np.frombuffer(buf, dtype=np.uint8), cv2.IMREAD_COLOR)
