"""택 검수 통합 웹앱 — 사진 한 장(Task)마다 바코드와 인쇄 시리얼을 읽고 서로 대조한다.

    python apps/web.py            ->  http://127.0.0.1:5000

모델은 서버가 뜰 때 한 번만 로드하고 계속 재사용한다. 이미지는 디스크를 거치지 않고
메모리에서만 처리한다. Task는 한 번에 하나씩 순차 처리되므로 표시되는 소요 시간이
실제 1건 처리 시간과 같다.
"""
import argparse
import base64
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, jsonify, request, send_from_directory

import _bootstrap  # noqa: F401  (sys.path 설정)
import pipeline
from ocr import MODEL_NAMES, Recognizer, versions
from tagreader.io import imdecode

HERE = Path(__file__).resolve().parent
TEMPLATE_DIR = HERE / "templates"
MAX_UPLOAD_MB = 32

# 응답에 실어 보내는 미리보기 이미지의 최대 폭. 원본을 그대로 base64로 보내면 수 MB가 된다.
PREVIEW_WIDTH = 900

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

recognizer: Recognizer | None = None
barcode_only = False


def _preview(img: np.ndarray | None, max_width: int = PREVIEW_WIDTH) -> str:
    if img is None or img.size == 0:
        return ""
    h, w = img.shape[:2]
    if w > max_width:
        img = cv2.resize(img, (max_width, max(1, int(h * max_width / w))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", img)
    return base64.b64encode(buf).decode("ascii") if ok else ""


@app.get("/")
def index():
    return send_from_directory(TEMPLATE_DIR, "index.html")


@app.get("/api/info")
def info():
    env = versions()
    return jsonify({
        "model": recognizer.model_name if recognizer else None,
        "device": str(recognizer.device) if recognizer else "cpu",
        "gpu": recognizer.gpu_name if recognizer else "",
        "img_size": list(recognizer.img_size) if recognizer else None,
        "barcode_only": barcode_only,
        "env": env,
    })


@app.post("/api/task")
def task():
    """Task 하나(사진 1장)를 처리한다."""
    file = request.files.get("image")
    if file is None:
        return jsonify({"error": "이미지가 없습니다"}), 400

    t0 = time.perf_counter()
    img = imdecode(file.read())
    ms_decode = (time.perf_counter() - t0) * 1000
    if img is None:
        return jsonify({"error": "이미지로 열 수 없습니다"}), 400

    try:
        result = pipeline.process_task(img, recognizer)
    except Exception as exc:  # 한 건 실패로 서버가 죽지 않게
        app.logger.exception("Task 처리 실패")
        return jsonify({"error": f"{exc.__class__.__name__}: {exc}"}), 500

    return jsonify({
        "error": result.error,
        "ms": {
            "decode": ms_decode,
            "barcode": result.ms_barcode,
            "ocr": result.ms_ocr,
            "total": ms_decode + result.ms_total,
        },
        "reads": [{
            "barcode": r.barcode,
            "format": r.barcode_format,
            "angle": r.angle,
            "stage": r.stage,
            "status": r.verdict.status,
            "label": r.verdict.label,
            "detail": r.verdict.detail,
            "ok": r.verdict.ok,
            "text": r.verdict.text,
            "confidence": r.verdict.confidence,
            "lines": r.lines,
            "crop": _preview(r.crop),
            "band": _preview(r.band),
        } for r in result.reads],
    })


@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": f"파일이 너무 큽니다 (최대 {MAX_UPLOAD_MB}MB)"}), 413


def main() -> int:
    parser = argparse.ArgumentParser(description="택 검수 통합 웹앱 (바코드 + OCR)")
    parser.add_argument("--model", default="parseq", choices=MODEL_NAMES)
    parser.add_argument("--device", default="auto", help="auto | cuda | cpu")
    parser.add_argument("--host", default="127.0.0.1", help="기본: 127.0.0.1 (본인 PC에서만 접속)")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--barcode-only", action="store_true", help="OCR 없이 바코드만 (모델 로드 생략)")
    args = parser.parse_args()

    global recognizer, barcode_only
    barcode_only = args.barcode_only

    if not barcode_only:
        print("PARSeq 로드 중... (첫 실행은 다운로드 때문에 몇 분 걸릴 수 있습니다)")
        recognizer = Recognizer(args.model, args.device)
        where = f"{recognizer.device}" + (f" ({recognizer.gpu_name})" if recognizer.gpu_name else "")
        print(f"  {recognizer.model_name} / {where} / 입력 {recognizer.img_size}")
        if recognizer.device.type != "cuda":
            print("  [!] GPU를 못 잡았습니다. CPU로 동작하며 OCR이 수십 배 느립니다.")
            print("      setup 스크립트를 다시 돌리거나 `python tools/doctor.py`로 진단하세요.")
    else:
        print("바코드 전용 모드 (OCR 비활성)")

    print()
    print(f"  http://{args.host}:{args.port}   <- 브라우저로 열기 (Ctrl+C 종료)")
    print()
    # reloader를 켜면 모델을 두 번 로드하므로 끈다.
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
