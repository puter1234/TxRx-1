"""환경 자체점검. setup 직후와 문제 발생 시 이걸로 원인을 좁힌다.

    python tools/doctor.py

확인 항목: 파이썬/패키지 버전, GPU 인식, PARSeq 캐시, 바코드 엔진, 통합 파이프라인 1건.
"""
import sys
import time
from pathlib import Path

import _bootstrap  # noqa: F401  (sys.path 설정)

ROOT = Path(__file__).resolve().parent.parent
OK, BAD, WARN = "  OK  ", " 실패 ", " 주의 "

problems: list[str] = []


def check(label: str, fn):
    try:
        status, detail = fn()
    except Exception as exc:
        status, detail = BAD, f"{exc.__class__.__name__}: {exc}"
    print(f"[{status}] {label:<26} {detail}")
    if status == BAD:
        problems.append(label)


def c_python():
    v = sys.version_info
    if v < (3, 9):
        return BAD, f"{v.major}.{v.minor} (3.9 이상 필요)"
    return OK, f"{v.major}.{v.minor}.{v.micro}  ({sys.executable})"


def c_venv():
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    if in_venv:
        return OK, "가상환경 안에서 실행 중"
    return WARN, "가상환경이 아닌 전역 파이썬 (setup.ps1을 쓰면 .venv가 만들어진다)"


def c_opencv():
    import cv2

    if not hasattr(cv2, "barcode"):
        return BAD, f"{cv2.__version__} — cv2.barcode 없음 (opencv-python 4.8+ 필요)"
    return OK, cv2.__version__


def c_zxing():
    import zxingcpp

    return OK, getattr(zxingcpp, "__version__", "설치됨")


def c_torch():
    import torch

    if torch.cuda.is_available():
        return OK, f"{torch.__version__} / CUDA {torch.version.cuda} / {torch.cuda.get_device_name(0)}"
    if torch.version.cuda:
        return WARN, f"{torch.__version__} (CUDA 빌드지만 GPU를 못 잡음 — 드라이버 확인)"
    return WARN, f"{torch.__version__} (CPU 전용 빌드 — OCR이 수십 배 느리다)"


def c_timm():
    import timm

    major = int(timm.__version__.split(".")[0])
    if major >= 1:
        return BAD, f"{timm.__version__} — 1.x는 PARSeq 로드가 깨진다. pip install \"timm>=0.9,<1.0\""
    return OK, timm.__version__


def c_hub_cache():
    import torch

    repo = Path(torch.hub.get_dir()) / "baudm_parseq_main"
    ckpt = Path(torch.hub.get_dir()) / "checkpoints"
    files = list(ckpt.glob("parseq*.pt")) if ckpt.is_dir() else []
    if not repo.is_dir():
        return WARN, "PARSeq repo 캐시 없음 (첫 실행 시 다운로드된다)"
    size = sum(f.stat().st_size for f in files) / 1e6
    return OK, f"repo 캐시 있음, 체크포인트 {len(files)}개 ({size:.0f}MB)"


def c_barcode():
    import tagreader
    from tagreader.io import imread

    sample = next((ROOT / "images").glob("*.jpg"), None)
    if sample is None:
        return WARN, "images/ 에 샘플 사진이 없어 건너뜀"
    img = imread(sample)
    t0 = time.perf_counter()
    tags = tagreader.read_tag(img)
    ms = (time.perf_counter() - t0) * 1000
    if not tags or not tags[0].text:
        return BAD, f"{sample.name} 에서 바코드를 읽지 못함"
    return OK, f"{tags[0].text} ({ms:.0f} ms)"


def c_pipeline():
    import pipeline
    from ocr import Recognizer
    from tagreader.io import imread

    sample = next((ROOT / "images").glob("*.jpg"), None)
    if sample is None:
        return WARN, "images/ 에 샘플 사진이 없어 건너뜀"

    from PIL import Image

    print("       PARSeq 로드 중... (첫 실행은 다운로드로 몇 분)")
    rec = Recognizer("parseq", "auto")
    img = imread(sample)
    rec.read(Image.new("RGB", (128, 32), (255, 255, 255)))  # 웜업 (첫 추론은 느리다)

    t0 = time.perf_counter()
    result = pipeline.process_task(img, rec)
    ms = (time.perf_counter() - t0) * 1000
    if not result.reads:
        return BAD, f"{sample.name}: {result.error}"
    read = result.reads[0]
    return OK, (
        f"{sample.name} -> 바코드 {read.barcode} / 인쇄 {read.verdict.text} "
        f"/ {read.verdict.label} ({ms:.0f} ms, 그중 OCR {result.ms_ocr:.0f} ms)"
    )


def main() -> int:
    print("=" * 78)
    print("택 검수 환경 자체점검")
    print("=" * 78)
    for label, fn in [
        ("파이썬", c_python),
        ("가상환경", c_venv),
        ("opencv-python", c_opencv),
        ("zxing-cpp", c_zxing),
        ("torch / GPU", c_torch),
        ("timm", c_timm),
        ("PARSeq 캐시", c_hub_cache),
        ("바코드 엔진", c_barcode),
        ("통합 파이프라인", c_pipeline),
    ]:
        check(label, fn)

    print("=" * 78)
    if problems:
        print(f"실패 {len(problems)}건: {', '.join(problems)}")
        print("README.md의 '문제가 생기면' 표를 참고하세요.")
        return 1
    print("모두 정상. `python apps/web.py` 로 실행하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
