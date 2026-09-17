"""OCR 전처리: 조명 보정 + 이진화.

read_tag()가 잘라준 above/below를 OCR에 넣기 전에 통과시키는 단계다. 촬영 조명이
고르지 않은 택 사진에서 글자 대비를 살린다. 파라미터는 tools/tune.py로 맞춘다.
"""
import cv2
import numpy as np

DEFAULTS = dict(
    mode="adaptive",      # 조명이 불균일한 촬영 문서에는 adaptive가 낫다
    block_size=31,
    c=15.0,
    denoise=10,
    illum_kernel=15,
    morph_open=2,
    invert=False,
)


def correct_illumination(gray: np.ndarray, kernel_size: int) -> np.ndarray:
    """배경 조명을 dilate로 추정해 나눗셈 정규화로 그림자/명암 편차를 없앤다."""
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    background = cv2.morphologyEx(gray, cv2.MORPH_DILATE, kernel)
    return cv2.divide(gray, background, scale=255)


def binarize(
    img: np.ndarray,
    mode: str = "adaptive",
    block_size: int = 31,
    c: float = 15.0,
    denoise: int = 10,
    illum_kernel: int = 15,
    morph_open: int = 2,
    invert: bool = False,
) -> np.ndarray:
    """그레이스케일화 -> 노이즈 제거 -> 조명 보정 -> 이진화 -> 잡점 제거.

    denoise / illum_kernel / morph_open은 0이면 해당 단계를 건너뛴다.
    denoise는 fastNlMeansDenoising이라 눈에 띄게 비싸다 (수백 ms). 속도가 급하면 0.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img

    if denoise > 0:
        gray = cv2.fastNlMeansDenoising(gray, h=denoise)
    if illum_kernel > 0:
        gray = correct_illumination(gray, illum_kernel)

    thresh_type = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY

    if mode == "otsu":
        _, binary = cv2.threshold(gray, 0, 255, thresh_type + cv2.THRESH_OTSU)
    else:
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, thresh_type,
            max(3, block_size | 1),  # adaptiveThreshold는 3 이상 홀수 blockSize를 요구
            c,
        )

    if morph_open > 0:
        kernel = np.ones((morph_open, morph_open), np.uint8)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

    return binary
