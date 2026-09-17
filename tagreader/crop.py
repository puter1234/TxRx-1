"""회전 보정된 택에서 바코드 위/아래 텍스트 영역을 잘라낸다 (OCR 입력용)."""
import numpy as np

from .geometry import rotate_bound, transform_points


class RotationCache:
    """같은 각도의 회전을 다시 계산하지 않는다.

    한 사진에 택이 여러 장 찍히면 대개 각도가 거의 같은데, 12MP warpAffine을
    바코드마다 반복하면 그것만으로 30ms씩 쌓인다.
    """

    def __init__(self, img: np.ndarray, tolerance: float = 0.5):
        self._img = img
        self._tolerance = tolerance
        self._entries: list[tuple[float, np.ndarray, np.ndarray]] = []

    def get(self, angle: float):
        for cached_angle, rotated, M in self._entries:
            if abs(cached_angle - angle) <= self._tolerance:
                return rotated, M
        rotated, M = rotate_bound(self._img, angle)
        self._entries.append((angle, rotated, M))
        return rotated, M


def crop_around(
    rotated: np.ndarray,
    rotated_quad: np.ndarray,
    margin_above: float = 1.2,
    margin_below: float = 1.2,
    full_width: bool = True,
    x_pad_ratio: float = 0.15,
):
    """바코드 높이의 배수만큼 위/아래를 잘라 (above, below)로 돌려준다.

    margin_above/below는 바코드 높이 대비 배수, x_pad_ratio는 full_width=False일 때
    좌우로 남길 여백(바코드 폭 대비)이다.
    """
    xs, ys = rotated_quad[:, 0], rotated_quad[:, 1]
    x_min, x_max = float(xs.min()), float(xs.max())
    y_min, y_max = float(ys.min()), float(ys.max())
    bc_w, bc_h = x_max - x_min, y_max - y_min

    h, w = rotated.shape[:2]
    if full_width:
        x0, x1 = 0, w
    else:
        pad = bc_w * x_pad_ratio
        x0, x1 = int(max(0, x_min - pad)), int(min(w, x_max + pad))

    above = rotated[int(max(0, y_min - bc_h * margin_above)):int(y_min), x0:x1]
    below = rotated[int(y_max):int(min(h, y_max + bc_h * margin_below)), x0:x1]
    return above, below


def draw_debug(rotated: np.ndarray, rotated_quad: np.ndarray, **kwargs) -> np.ndarray:
    """바코드 박스(빨강)와 above(파랑)/below(초록) 크롭 영역을 그린 진단용 이미지."""
    import cv2

    xs, ys = rotated_quad[:, 0], rotated_quad[:, 1]
    x_min, x_max = int(xs.min()), int(xs.max())
    y_min, y_max = int(ys.min()), int(ys.max())
    bc_h = y_max - y_min
    margin_above = kwargs.get("margin_above", 1.2)
    margin_below = kwargs.get("margin_below", 1.2)

    debug = rotated.copy()
    h, w = debug.shape[:2]
    cv2.rectangle(debug, (x_min, y_min), (x_max, y_max), (0, 0, 255), 2)
    cv2.rectangle(debug, (0, int(max(0, y_min - bc_h * margin_above))), (w, y_min), (255, 0, 0), 2)
    cv2.rectangle(debug, (0, y_max), (w, int(min(h, y_max + bc_h * margin_below))), (0, 255, 0), 2)
    return debug


__all__ = ["RotationCache", "crop_around", "draw_debug", "transform_points"]
