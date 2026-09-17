"""OCR 전처리(이진화) 파라미터를 트랙바로 조절하며 실시간 미리보기하는 툴.

택 전체가 아니라 read_tag()가 잘라준 above/below 크롭에 맞춰 튜닝하는 게 맞으므로,
--crop 옵션을 주면 바코드 위/아래 크롭을 대상으로 미리보기한다.

's' 저장 / 'q'·ESC 종료 시 최종 파라미터를 코드에 붙여 넣을 형태로 출력한다.
실행: python tools/tune.py images/사진.jpg --crop above
"""
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

import _bootstrap  # noqa: F401  (sys.path 설정)
import tagreader
from tagreader.io import imread, imwrite
from tagreader.preprocess import binarize

WINDOW = "preprocess tuner  (s: save, q/ESC: quit)"
MAX_DISPLAY_WIDTH = 900

TRACKBARS = [
    # (라벨, 초기값, 최대값)
    ("mode(0=adaptive,1=otsu)", 0, 1),
    ("blockSize", 31, 199),
    ("C", 15, 50),
    ("denoise", 10, 30),
    ("illumKernel", 15, 60),
    ("morphOpen", 2, 10),
    ("invert(0/1)", 0, 1),
]


def resize_for_display(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    if w <= MAX_DISPLAY_WIDTH:
        return img
    scale = MAX_DISPLAY_WIDTH / w
    return cv2.resize(img, (int(w * scale), int(h * scale)))


def to_bgr(img: np.ndarray) -> np.ndarray:
    return img if img.ndim == 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def pick_target(img: np.ndarray, crop: str) -> np.ndarray:
    """--crop 지정 시 read_tag로 해당 영역을 잘라 반환한다."""
    if crop == "none":
        return img
    tags = tagreader.read_tag(img)
    if not tags:
        print("바코드를 감지하지 못해 원본 전체로 튜닝합니다.", file=sys.stderr)
        return img
    target = getattr(tags[0], crop)
    if target is None or not target.size:
        print(f"{crop} 크롭이 비어 있어 원본 전체로 튜닝합니다.", file=sys.stderr)
        return img
    return target


def main():
    parser = argparse.ArgumentParser(description="OCR 전처리 파라미터 실시간 튜닝")
    parser.add_argument("input", type=Path, help="입력 이미지 파일")
    parser.add_argument("output", type=Path, nargs="?", default=Path("tuned.png"), help="저장 경로")
    parser.add_argument("--crop", choices=["above", "below", "none"], default="above",
                        help="튜닝 대상 영역 (기본: 바코드 위쪽 텍스트)")
    args = parser.parse_args()

    img = imread(args.input)
    if img is None:
        print(f"이미지를 읽을 수 없습니다: {args.input}", file=sys.stderr)
        sys.exit(1)

    target = pick_target(img, args.crop)

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    for label, initial, maximum in TRACKBARS:
        cv2.createTrackbar(label, WINDOW, initial, maximum, lambda _: None)

    params = {}
    while True:
        get = lambda label: cv2.getTrackbarPos(label, WINDOW)  # noqa: E731
        params = dict(
            mode="otsu" if get("mode(0=adaptive,1=otsu)") else "adaptive",
            block_size=max(3, get("blockSize") | 1),  # 3 이상 홀수 보장
            c=float(get("C")),
            denoise=get("denoise"),
            illum_kernel=get("illumKernel"),
            morph_open=get("morphOpen"),
            invert=bool(get("invert(0/1)")),
        )
        result = binarize(target, **params)

        preview = np.vstack([
            resize_for_display(to_bgr(target)),
            resize_for_display(to_bgr(result)),
        ]) if target.shape[1] > target.shape[0] else np.hstack([
            resize_for_display(to_bgr(target)),
            resize_for_display(to_bgr(result)),
        ])
        cv2.imshow(WINDOW, preview)

        key = cv2.waitKey(30) & 0xFF
        if key in (ord("q"), 27):
            break
        if key == ord("s"):
            imwrite(args.output, result)
            print(f"[saved] {args.output}")

    cv2.destroyAllWindows()
    print("\n최종 파라미터:")
    print(f"  binarize(img, {', '.join(f'{k}={v!r}' for k, v in params.items())})")


if __name__ == "__main__":
    main()
