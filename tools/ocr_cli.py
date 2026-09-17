"""통합 파이프라인 CLI — 폴더를 훑어 바코드/OCR/대조 판정을 표로 뽑는다.

    python tools/ocr_cli.py                    images/ 전체
    python tools/ocr_cli.py images/사진.jpg
    python tools/ocr_cli.py --device cpu
    python tools/ocr_cli.py --bench            latency 측정 (spec.md 5)
    python tools/ocr_cli.py --barcode-only     OCR 없이 바코드만

원본 OCR_core/run_ocr.py를 대체한다. 다른 점은 크롭 한 장이 아니라 택 사진 한 장(Task)을
통째로 받아 바코드까지 같이 읽고 대조한다는 것이다.
"""
import argparse
import math
import statistics
import sys
import time
from pathlib import Path

import _bootstrap  # noqa: F401  (sys.path 설정)
import pipeline
from ocr import MODEL_NAMES, Recognizer, versions
from tagreader.io import IMAGE_EXTS, imread

ROOT = Path(__file__).resolve().parent.parent


def collect(raw_paths) -> list[Path]:
    if not raw_paths:
        base = ROOT / "images"
        return sorted(p for p in base.iterdir() if p.suffix.lower() in IMAGE_EXTS) if base.is_dir() else []

    files = []
    for raw in raw_paths:
        path = Path(raw)
        if path.is_dir():
            files += sorted(p for p in path.iterdir() if p.suffix.lower() in IMAGE_EXTS)
        elif path.is_file():
            files.append(path)
        else:
            print(f"  [!] 파일 없음: {path}", file=sys.stderr)
    return files


def benchmark(rec, img, runs: int, warmup: int):
    for _ in range(warmup):
        pipeline.process_task(img, rec)

    totals, barcodes, ocrs = [], [], []
    for _ in range(runs):
        t0 = time.perf_counter()
        result = pipeline.process_task(img, rec)
        totals.append((time.perf_counter() - t0) * 1000)
        barcodes.append(result.ms_barcode)
        ocrs.append(result.ms_ocr)

    def stats(xs):
        xs = sorted(xs)
        return (
            statistics.mean(xs),
            statistics.median(xs),
            xs[max(0, math.ceil(0.95 * len(xs)) - 1)],
            xs[-1],
        )

    return stats(barcodes), stats(ocrs), stats(totals)


def main() -> int:
    parser = argparse.ArgumentParser(description="택 검수 통합 파이프라인 CLI")
    parser.add_argument("images", nargs="*", help="이미지 파일/폴더 (생략 시 images/ 전체)")
    parser.add_argument("--model", default="parseq", choices=MODEL_NAMES)
    parser.add_argument("--device", default="auto", help="auto | cuda | cpu")
    parser.add_argument("--barcode-only", action="store_true", help="OCR 없이 바코드만")
    parser.add_argument("--bench", action="store_true", help="첫 이미지로 latency 측정")
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--lines", action="store_true", help="OCR한 줄 전부 출력")
    args = parser.parse_args()

    paths = collect(args.images)
    if not paths:
        print("읽을 이미지가 없다. images/ 에 넣거나 경로를 인자로 줄 것.", file=sys.stderr)
        return 1

    env = versions()
    print("=" * 96)
    print(f"torch {env['torch']} / CUDA {env['cuda_build']} / {env['gpu'] or 'GPU 없음'}")

    rec = None
    if not args.barcode_only:
        print(f"model: {args.model} (pretrained, torch.hub baudm/parseq)")
        print("=" * 96)
        print("모델 로드 중... (첫 실행은 다운로드 때문에 몇 분 걸릴 수 있다)")
        rec = Recognizer(args.model, args.device)
        print(f"  device: {rec.device}" + (f" ({rec.gpu_name})" if rec.gpu_name else ""))
        print(f"  입력 크기: {rec.img_size}")
    else:
        print("바코드 전용 모드")
        print("=" * 96)
    print()

    header = f"{'file':<32}{'barcode':<20}{'인쇄면 OCR':<22}{'판정':<20}{'ms':>7}"
    print(header)
    print("-" * len(header))

    ok = 0
    for path in paths:
        img = imread(path)
        if img is None:
            print(f"{path.name:<32}[열기 실패]")
            continue

        result = pipeline.process_task(img, rec)
        if not result.reads:
            print(f"{path.name:<32}{'-':<20}{'-':<22}{result.error or '실패':<20}{result.ms_total:>7.0f}")
            continue

        for i, read in enumerate(result.reads):
            name = path.name if i == 0 else ""
            ms = f"{result.ms_total:.0f}" if i == 0 else ""
            ok += read.verdict.ok
            print(f"{name[:31]:<32}{str(read.barcode):<20}{str(read.verdict.text or '-')[:21]:<22}"
                  f"{read.verdict.label:<20}{ms:>7}")
            if args.lines and read.lines:
                for line in read.lines:
                    print(f"    {line['text']:<28} conf {line['confidence']:.3f}  {line['ms']:.1f} ms")

    print("-" * len(header))
    print(f"대조 성공 {ok}/{len(paths)}")

    if args.bench:
        print()
        print(f"latency 측정: warmup {args.warmup}회 후 {args.runs}회 반복 — {paths[0].name}")
        bc, oc, total = benchmark(rec, imread(paths[0]), args.runs, args.warmup)
        for label, s in (("바코드", bc), ("OCR", oc), ("합계", total)):
            print(f"  {label:<7} mean {s[0]:7.1f} | median {s[1]:7.1f} | p95 {s[2]:7.1f} | max {s[3]:7.1f}  (ms)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
