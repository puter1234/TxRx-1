"""택 이미지에서 텍스트 줄 영역을 찾는다.

**통합의 핵심 단계다.** PARSeq는 검출기가 아니라 '한 줄짜리 크롭'을 읽는 인식기라
입력 규격이 32x128이다. tagreader가 내주는 전폭 크롭(예: 3026x141, 종횡비 21:1)을
그대로 넣으면 엉뚱한 단어를 confidence 0.89로 뱉는다 (틀렸는데 자신만만한 형태).

그래서 검출기 모델을 추가로 얹는 대신, 인쇄 택이라는 조건을 이용해 고전 CV로 줄을 찾는다:
이진화 -> 가로 방향 팽창으로 글자를 단어 덩어리로 뭉침 -> 연결요소 -> 바코드 크기 기준 필터.
"""
import cv2
import numpy as np

# 글자 높이가 바코드 높이의 이 범위 밖이면 텍스트로 보지 않는다.
MIN_H_RATIO = 0.10
MAX_H_RATIO = 1.20

# 글자를 단어로 뭉치는 가로 커널 폭 (바코드 높이 대비).
MERGE_KERNEL_RATIO = 0.25

# 같은 줄로 묶을 세로 중심 거리 (글자 높이 대비).
LINE_TOLERANCE = 0.6

# OCR에 넘길 때 박스 주위로 더 주는 여백 (글자 높이 대비). 여백이 없으면 인식률이 떨어진다.
CROP_MARGIN = 0.25


def _word_boxes(band: np.ndarray, char_h: float) -> list[list[int]]:
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY) if band.ndim == 3 else band
    # 조명 편차가 있는 촬영 이미지라 adaptive. 글자가 흰 블롭이 되도록 INV.
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 15
    )
    kernel_w = max(3, int(char_h * MERGE_KERNEL_RATIO))
    merged = cv2.morphologyEx(
        binary, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_w, 3))
    )

    count, _, stats, _ = cv2.connectedComponentsWithStats(merged, 8)
    boxes = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if not (char_h * MIN_H_RATIO <= h <= char_h * MAX_H_RATIO):
            continue
        if w < h * 0.5:                      # 한 글자보다 좁으면 노이즈
            continue
        if w > band.shape[1] * 0.95:         # 배경 전체를 먹은 블롭
            continue
        if area < w * h * 0.15:              # 속 빈 사각형(테두리, 비닐 주름)
            continue
        boxes.append([int(x), int(y), int(w), int(h)])
    return boxes


def _merge_into_lines(boxes: list[list[int]]) -> list[list[int]]:
    """세로로 겹치는 단어 박스들을 한 줄로 합친다. '*HUTS 6A211' + 'BK' + '095*' -> 한 줄."""
    lines: list[list[int]] = []
    for x, y, w, h in sorted(boxes, key=lambda b: b[1]):
        center_y = y + h / 2
        for line in lines:
            if abs(center_y - (line[1] + line[3] / 2)) < max(h, line[3]) * LINE_TOLERANCE:
                x0, y0 = min(line[0], x), min(line[1], y)
                x1, y1 = max(line[0] + line[2], x + w), max(line[1] + line[3], y + h)
                line[:] = [x0, y0, x1 - x0, y1 - y0]
                break
        else:
            lines.append([x, y, w, h])
    return sorted(lines, key=lambda b: b[1])


def find_text_lines(band: np.ndarray, char_h: float, max_lines: int = 6) -> list[np.ndarray]:
    """밴드 이미지에서 텍스트 줄 크롭들을 잘라 돌려준다 (위 -> 아래 순).

    char_h는 글자 높이의 기준값으로, 바코드 높이를 넘기면 된다 (택 인쇄는 대개
    바코드 높이와 글자 높이가 한 자릿수 배율 안에 있다).
    """
    if band is None or band.size == 0:
        return []

    crops = []
    for x, y, w, h in _merge_into_lines(_word_boxes(band, char_h))[:max_lines]:
        if w < h:  # 세로로 긴 조각은 텍스트 줄이 아니다
            continue
        margin = int(h * CROP_MARGIN)
        crop = band[
            max(0, y - margin):min(band.shape[0], y + h + margin),
            max(0, x - margin):min(band.shape[1], x + w + margin),
        ]
        if crop.size:
            crops.append(crop)
    return crops
