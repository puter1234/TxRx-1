"""하드웨어 스펙 결정용 벤치마크.

    .venv\\Scripts\\python tools\\bench.py

같은 사진으로 여러 PC에서 돌려 비교하라고 만든 것이다. 출력 맨 끝의 요약 한 줄을
PC끼리 나란히 놓으면 그게 스펙 결정 근거가 된다.

측정 항목:
  1. 배치 스케일링  — 이 워크로드가 연산 바운드인지 실행 오버헤드 바운드인지 가린다.
                     오버헤드 바운드면 GPU 등급을 올려도 latency가 안 줄어든다.
  2. Task 1건       — 실제 1건 처리 시간과 그 구성(바코드 CPU / OCR GPU)
  3. 동시 처리      — 컨베이어에서 Task가 겹칠 때 latency가 어떻게 무너지는지
  4. VRAM          — 필요한 메모리 (얼마짜리 카드를 사야 하는지)
"""
import argparse
import json
import statistics
import sys
import threading
import time
from pathlib import Path

import cv2
import torch
from PIL import Image

import _bootstrap  # noqa: F401  (sys.path 설정)
import pipeline
import tagreader
from ocr import Recognizer, find_text_lines
from tagreader.io import imread

ROOT = Path(__file__).resolve().parent.parent


def sync():
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def median(xs):
    return statistics.median(xs)


def main() -> int:
    parser = argparse.ArgumentParser(description="스펙 결정용 벤치마크")
    parser.add_argument("--device", default="auto", help="auto | cuda | cpu")
    parser.add_argument("--model", default="parseq")
    parser.add_argument("--runs", type=int, default=50, help="배치 스케일링 반복 횟수")
    args = parser.parse_args()

    print("=" * 92)
    print(f"torch {torch.__version__} / CUDA build {torch.version.cuda or '(CPU 빌드)'}")
    if torch.cuda.is_available():
        p = torch.cuda.get_device_properties(0)
        print(f"GPU  {p.name} / sm_{p.major}{p.minor} / VRAM {p.total_memory / 1e9:.1f} GB / SM {p.multi_processor_count}개")
    else:
        print("GPU  없음 (CPU 추론)")
    print(f"CPU  torch {torch.get_num_threads()} threads / opencv {cv2.getNumThreads()} threads")
    print("=" * 92)

    rec = Recognizer(args.model, args.device)
    params = sum(t.numel() for t in rec.model.parameters())
    print(f"모델 {rec.model_name} / {rec.device} / 입력 {rec.img_size} / 파라미터 {params / 1e6:.1f}M")
    print()

    stems = sorted(json.loads((ROOT / "tests/expected.json").read_text(encoding="utf-8")))
    imgs = {s: imread(ROOT / "images" / f"{s}.jpg") for s in stems}

    # --- 1. 배치 스케일링 -----------------------------------------------------
    crops = []
    for s in stems:
        tag = tagreader.read_tag(imgs[s], want_rotated=True)[0]
        above, below, bar_h = pipeline._band_of(tag.rotated, tag._rotated_quad)
        crops += find_text_lines(above, bar_h) + find_text_lines(below, bar_h)
    tensors = [rec.transform(Image.fromarray(cv2.cvtColor(c, cv2.COLOR_BGR2RGB))) for c in crops[:16]]

    print(f"[1] 배치 스케일링   (실제 택 크롭 {len(tensors)}장)")
    print(f"    {'배치':>5}{'총 ms':>10}{'줄당 ms':>10}{'배치1 대비':>12}")
    base, per_line = None, {}
    for bs in (1, 2, 4, 8, 16):
        if bs > len(tensors):
            break
        batch = torch.stack(tensors[:bs]).to(rec.device)
        for _ in range(10):
            with torch.inference_mode():
                rec.model(batch)
        sync()
        ts = []
        for _ in range(args.runs):
            t0 = time.perf_counter()
            with torch.inference_mode():
                rec.model(batch)
            sync()
            ts.append((time.perf_counter() - t0) * 1000)
        m = median(ts)
        base = base if base is not None else m
        per_line[bs] = m / bs
        print(f"    {bs:>5}{m:>10.2f}{m / bs:>10.2f}{m / base:>11.2f}x")

    scaling = per_line[min(per_line)] / per_line[max(per_line)]
    verdict = ("실행 오버헤드 바운드 — GPU 등급을 올려도 latency는 거의 안 준다"
               if scaling > 3 else
               "연산 바운드 — GPU 성능이 latency에 직결된다"
               if scaling < 1.5 else
               "중간 — 배치가 커질수록 GPU 성능이 의미를 갖는다")
    print(f"    배치1 대비 배치{max(per_line)}의 줄당 효율 {scaling:.1f}배  ->  {verdict}")
    print()

    # --- 2. Task 1건 ----------------------------------------------------------
    for s in stems[:2]:
        pipeline.process_task(imgs[s], rec)

    print("[2] Task 1건   (사진 -> 바코드 + OCR + 대조)")
    print(f"    {'file':<9}{'바코드ms':>10}{'OCRms':>9}{'줄':>4}{'합계ms':>9}  판정")
    totals, bcs, ocrs = [], [], []
    for s in stems:
        t0 = time.perf_counter()
        result = pipeline.process_task(imgs[s], rec)
        ms = (time.perf_counter() - t0) * 1000
        read = result.reads[0]
        totals.append(ms)
        bcs.append(result.ms_barcode)
        ocrs.append(result.ms_ocr)
        print(f"    {s[-6:]:<9}{result.ms_barcode:>10.0f}{result.ms_ocr:>9.0f}"
              f"{len(read.lines):>4}{ms:>9.0f}  {read.verdict.label}")
    seq = median(totals)
    print(f"    합계 중앙값 {seq:.0f} / 최악 {max(totals):.0f} ms"
          f"   |  바코드(CPU) {median(bcs):.0f} ms + OCR {median(ocrs):.0f} ms")
    print()

    # --- 3. 동시 처리 ---------------------------------------------------------
    print("[3] 동시 처리   (컨베이어에서 Task가 겹쳐 들어오는 상황)")
    print(f"    {'동시':>5}{'1건 중앙값 ms':>16}{'순차 대비':>11}{'전체 ms':>10}{'처리량 Task/s':>15}")
    print(f"    {1:>5}{seq:>16.0f}{1.0:>10.1f}x{seq:>10.0f}{1000 / seq:>15.1f}")
    throughput = {1: 1000 / seq}
    for n in (2, 4, 8):
        res, lock = [], threading.Lock()

        def worker(img):
            t0 = time.perf_counter()
            pipeline.process_task(img, rec)
            with lock:
                res.append((time.perf_counter() - t0) * 1000)

        t0 = time.perf_counter()
        threads = [threading.Thread(target=worker, args=(imgs[stems[i % len(stems)]],)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        wall = (time.perf_counter() - t0) * 1000
        throughput[n] = n / (wall / 1000)
        print(f"    {n:>5}{median(res):>16.0f}{median(res) / seq:>10.1f}x{wall:>10.0f}{throughput[n]:>15.1f}")
    print()

    # --- 4. VRAM --------------------------------------------------------------
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
        batch = torch.stack(tensors[:min(16, len(tensors))]).to(rec.device)
        with torch.inference_mode():
            rec.model(batch)
        sync()
        peak = torch.cuda.max_memory_allocated() / 1e6
        print(f"[4] VRAM   추론 피크 {peak:.0f} MB (예약 {torch.cuda.max_memory_reserved() / 1e6:.0f} MB) "
              f"| 가중치 {params * 4 / 1e6:.0f} MB")
        print()

    # --- 요약 -----------------------------------------------------------------
    gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU only"
    print("=" * 92)
    print("요약 (이 줄을 PC끼리 비교하면 된다)")
    print(f"  {gpu}  |  Task 중앙값 {seq:.0f} ms / 최악 {max(totals):.0f} ms  "
          f"|  최대 처리량 {max(throughput.values()):.1f} Task/s  |  {verdict.split(' — ')[0]}")
    print("=" * 92)
    return 0


if __name__ == "__main__":
    sys.exit(main())
