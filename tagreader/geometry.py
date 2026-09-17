"""quad(바코드 4점) 관련 기하 연산."""
import math

import cv2
import numpy as np


def deskew_angle(quad: np.ndarray, horizontal: bool = True) -> float:
    """바코드 quad를 축에 맞추는 데 필요한 회전각(도)을 구한다.

    horizontal=True(기본)면 바코드가 반드시 가로로 눕도록 필요 시 90°를 더한다.
    택에 인쇄된 시리얼 텍스트는 바코드 위/아래에 있으므로, 세로로 선 바코드를
    세로인 채 두면 crop.py가 텍스트가 아닌 엉뚱한 영역을 잘라낸다.
    (값 디코딩만 놓고 보면 zxing의 try_rotate가 90° 회전을 처리하므로 상관없다.)
    """
    rect = cv2.minAreaRect(quad.astype(np.float32))
    box = cv2.boxPoints(rect)
    edge0, edge1 = box[1] - box[0], box[2] - box[1]
    longer = edge0 if np.linalg.norm(edge0) >= np.linalg.norm(edge1) else edge1

    angle = math.degrees(math.atan2(longer[1], longer[0])) % 180
    if angle > 90:
        angle -= 180
    if angle > 45:
        angle -= 90
    elif angle <= -45:
        angle += 90

    if horizontal and _is_portrait(quad, angle):
        angle += 90 if angle <= 0 else -90
    return angle


def _is_portrait(quad: np.ndarray, angle: float) -> bool:
    """주어진 각도로 돌렸을 때 quad가 눕지 않고 서 있는지."""
    theta = math.radians(-angle)
    cos, sin = math.cos(theta), math.sin(theta)
    centered = quad - quad.mean(axis=0)
    xs = centered[:, 0] * cos - centered[:, 1] * sin
    ys = centered[:, 0] * sin + centered[:, 1] * cos
    return (ys.max() - ys.min()) > (xs.max() - xs.min())


def quad_area(quad: np.ndarray) -> float:
    return float(cv2.contourArea(quad.astype(np.float32)))


def quad_radius(quad: np.ndarray) -> float:
    """중심에서 가장 먼 꼭짓점까지의 거리. ROI 크기를 잡는 데 쓴다."""
    return float(np.linalg.norm(quad - quad.mean(axis=0), axis=1).max())


def dedupe_quads(quads: list[np.ndarray], min_dist: float = 150) -> list[np.ndarray]:
    """겹치는 타일에서 중복 감지된 quad를 중심점 거리로 묶고 면적이 가장 큰 것만 남긴다."""
    keep: list[np.ndarray] = []
    for quad in sorted(quads, key=quad_area, reverse=True):
        centroid = quad.mean(axis=0)
        if all(np.linalg.norm(centroid - k.mean(axis=0)) >= min_dist for k in keep):
            keep.append(quad)
    return keep


def rotate_bound(img: np.ndarray, angle_deg: float, border=(255, 255, 255)):
    """잘림 없이 회전한다. 확장된 캔버스와 사용된 변환행렬을 함께 돌려준다."""
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle_deg, 1.0)

    cos, sin = abs(M[0, 0]), abs(M[0, 1])
    new_w, new_h = int(h * sin + w * cos), int(h * cos + w * sin)
    M[0, 2] += new_w / 2 - w / 2
    M[1, 2] += new_h / 2 - h / 2

    rotated = cv2.warpAffine(img, M, (new_w, new_h), flags=cv2.INTER_LINEAR, borderValue=border)
    return rotated, M


def transform_points(points: np.ndarray, M: np.ndarray) -> np.ndarray:
    ones = np.ones((points.shape[0], 1))
    return (M @ np.hstack([points, ones]).T).T
