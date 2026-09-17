"""택 사진을 골라 회전 보정 + 바코드 값을 창으로 보여주는 데스크톱 앱.

디스크에 중간 파일을 쓰지 않고 전부 메모리에서 처리한다 (구글드라이브 동기화 폴더에
파일을 쓰면 느려지는 문제 회피). 파일 선택은 PowerShell의 Windows Forms
OpenFileDialog를 이용해 tkinter 없이 네이티브 창을 띄운다.

실행: python apps/desktop.py
      파일 선택 -> 결과 창 -> 아무 키: 다음 사진 / ESC·q: 종료
"""
import subprocess
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import _bootstrap  # noqa: F401  (sys.path 설정)
import tagreader
from tagreader.io import imread

WINDOW = "tag barcode reader"
MAX_WIDTH = 1200
BANNER_H = 52

# cv2.putText의 Hershey 폰트는 ASCII 전용이라 한글이 '???'로 찍힌다. PIL로 그린다.
_FONT_CANDIDATES = ["C:/Windows/Fonts/malgun.ttf", "C:/Windows/Fonts/gulim.ttc"]


def _load_font(size: int):
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


FONT = _load_font(26)
FONT_SMALL = _load_font(18)


def draw_text(img: np.ndarray, text: str, xy, color=(0, 0, 0), font=None) -> np.ndarray:
    """BGR ndarray 위에 한글 텍스트를 그린다."""
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    ImageDraw.Draw(pil).text(xy, text, font=font or FONT, fill=color[::-1])
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def pick_file() -> str | None:
    """PowerShell OpenFileDialog로 파일을 선택한다.

    stdout으로 경로를 넘기면 콘솔 코드페이지 때문에 한글 경로가 깨질 수 있어,
    선택 결과를 UTF-8 임시 파일에 써서 그걸 읽는 방식으로 우회한다.
    """
    result_file = Path(tempfile.gettempdir()) / "tagreader_selected_path.txt"
    result_file.unlink(missing_ok=True)

    ps_script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$f = New-Object System.Windows.Forms.OpenFileDialog; "
        '$f.Filter = "Images|*.jpg;*.jpeg;*.png;*.bmp"; '
        '$f.Title = "택 사진 선택"; '
        'if ($f.ShowDialog() -eq "OK") { '
        f'[System.IO.File]::WriteAllText("{result_file}", $f.FileName, [System.Text.Encoding]::UTF8) '
        "}"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps_script])

    if not result_file.exists():
        return None
    path = result_file.read_text(encoding="utf-8").strip()
    result_file.unlink()
    return path or None


def resize_to_width(img: np.ndarray, max_width: int) -> np.ndarray:
    h, w = img.shape[:2]
    if w <= max_width:
        return img
    scale = max_width / w
    return cv2.resize(img, (max_width, int(h * scale)))


def build_view(img: np.ndarray, elapsed_ms: float) -> np.ndarray:
    tags = tagreader.read_tag(img)

    if not tags:
        view = resize_to_width(img, MAX_WIDTH)
        return draw_text(view, f"바코드 감지 실패  ({elapsed_ms:.0f} ms)", (20, 20), (0, 0, 255))

    panels = []
    for i, tag in enumerate(tags):
        label = tag.text or "디코딩 실패"
        color = (0, 160, 0) if tag.text else (0, 0, 255)
        width = MAX_WIDTH

        if tag.above is not None and tag.above.size:
            panel = resize_to_width(tag.above, MAX_WIDTH)
            width = panel.shape[1]
        else:
            panel = None

        banner = np.full((BANNER_H, width, 3), 255, dtype=np.uint8)
        banner = draw_text(banner, f"[{i}] {label}", (10, 12), color)
        banner = draw_text(
            banner, f"{tag.format} · {tag.angle:.1f}°", (width - 220, 16), (120, 120, 120), FONT_SMALL
        )
        panels.append(banner)
        if panel is not None:
            panels.append(panel)

    width = min(p.shape[1] for p in panels)
    view = np.vstack([p[:, :width] for p in panels])
    return draw_text(view, f"{elapsed_ms:.0f} ms", (10, view.shape[0] - 26), (120, 120, 120), FONT_SMALL)


def main():
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)

    while True:
        path = pick_file()
        if not path:
            break

        t0 = time.perf_counter()
        img = imread(path)
        if img is None:
            print(f"이미지를 읽을 수 없습니다: {path}")
            continue

        elapsed = (time.perf_counter() - t0) * 1000
        cv2.imshow(WINDOW, build_view(img, elapsed))
        print(f"{path}: {elapsed:.0f} ms")

        if (cv2.waitKey(0) & 0xFF) in (ord("q"), 27):
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
