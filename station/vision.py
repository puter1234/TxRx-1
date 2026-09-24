"""Local PARSeq inference. Neither model creation nor weights use a network path."""

from __future__ import annotations

import hashlib
import base64
import importlib.util
import io
import json
import sys
import threading
import time
from pathlib import Path

from .schema import Brand, Recipe

ROOT = Path(__file__).resolve().parents[1]

OCR_MODULES = ("PIL", "torch", "torchvision", "timm", "pytorch_lightning", "yaml", "lmdb", "nltk", "zxingcpp")


def missing_ocr_modules():
    return [name for name in OCR_MODULES if importlib.util.find_spec(name) is None]


def _serial_fields(text: str, brand: Brand):
    """Decode a complete printed product code from registered option values only."""
    from ocr.normalize import normalize_strict

    serial = normalize_strict(text)
    if not serial or not brand.options:
        return None
    matches = []

    def walk(index, offset, fields):
        if len(matches) > 1:
            return
        if index == len(brand.options):
            if offset == len(serial):
                matches.append(dict(fields))
            return
        option = brand.options[index]
        for value in option.values:
            part = normalize_strict(value)
            if part and serial.startswith(part, offset):
                fields[option.key] = value
                walk(index + 1, offset + len(part), fields)
        fields.pop(option.key, None)

    walk(0, 0, {})
    return matches[0] if len(matches) == 1 else None


def verify_model(directory: Path):
    path = directory / "manifest.json"
    if not path.is_file():
        raise RuntimeError("로컬 모델 묶음과 해시 목록이 필요합니다.")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not {"parseq-bb5792a6.pt", "source/hubconf.py"} <= set(manifest):
        raise RuntimeError("모델 묶음의 필수 파일이 없습니다.")
    for name, expected in manifest.items():
        p = (directory / name).resolve()
        if directory.resolve() not in p.parents or not p.is_file():
            raise RuntimeError("모델 묶음 경로 오류: " + name)
        if hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            raise RuntimeError("모델 해시 불일치: " + name)
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Vision:
    def __init__(self, model_dir: Path | None = None):
        self.directory = model_dir or ROOT / "models/parseq"
        self.recognizer = None
        self.lock = threading.Lock()
        self.model_lock = threading.Lock()
        self.model_hash = None
        self.error = None

    def load(self):
        with self.model_lock:
            self._load()

    def _load(self):
        if self.recognizer is not None:
            return
        self.model_hash = verify_model(self.directory)
        # Preserve Recognizer.read, tokenizer, official transform, GPU/CPU selection.
        import torch
        from ocr.core import Recognizer, resolve_device, build_transform

        sys.path.insert(0, str(self.directory / "source"))
        from strhub.models.utils import create_model

        model = create_model("parseq", pretrained=False)
        state = torch.load(
            self.directory / "parseq-bb5792a6.pt", map_location="cpu", weights_only=True
        )
        model.model.load_state_dict(state, strict=True)
        recognizer = Recognizer.__new__(Recognizer)
        recognizer.model_name = "parseq"
        recognizer.device = resolve_device()
        recognizer.gpu_name = (
            torch.cuda.get_device_name(recognizer.device)
            if recognizer.device.type == "cuda"
            else ""
        )
        recognizer.model = model.eval().to(recognizer.device)
        recognizer.img_size = tuple(model.hparams.img_size)
        recognizer.transform = build_transform(model.hparams.img_size)
        recognizer._lock = threading.Lock()
        self.recognizer = recognizer

    def inspect(self, image_path: Path, brand: Brand, recipe: Recipe):
        return self._inspect(image_path, brand, recipe)

    def inspect_frame(self, frame, brand: Brand, recipe: Recipe):
        """Inspect an OpenCV BGR frame without encoding or reopening a photo."""
        return self._inspect(frame, brand, recipe)

    def _inspect(self, source, brand: Brand, recipe: Recipe):
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("이전 영상 처리가 아직 끝나지 않았습니다.")
        try:
            self.error = None
            import cv2
            import numpy as np

            frame = None
            if isinstance(source, (str, Path)):
                from PIL import Image
                with Image.open(source) as original:
                    original.load()
                    image = original.convert("RGB")
            else:
                frame = source
                image = None
            width, height = (
                image.size if image is not None else (frame.shape[1], frame.shape[0])
            )
            if "barcode" in recipe.channels and width * height > 24_000_000:
                raise ValueError("바코드 영상은 2,400만 화소 이하만 지원합니다.")
            observations, detail, failures = {}, {}, []
            task = None
            if "ocr" in recipe.channels:
                bgr = frame if frame is not None else cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
                task = self._auto_read(bgr)
                candidates = []
                for read in task.reads:
                    for line in read.lines:
                        fields = _serial_fields(line["text"], brand)
                        if fields is not None:
                            candidates.append((fields, line, read.barcode))
                detail["ocr_lines"] = [line for read in task.reads for line in read.lines]
                detail["ocr_ms"] = task.ms_ocr
                detail["ocr_error"] = task.error
                distinct = {tuple(sorted(fields.items())) for fields, _, _ in candidates}
                if len(distinct) == 1:
                    fields, line, linked_barcode = candidates[0]
                    observations["ocr"] = fields
                    detail["ocr_serial"] = line["text"]
                    from ocr.normalize import normalize_strict
                    if "barcode" in recipe.channels and linked_barcode and (
                        normalize_strict(linked_barcode) != normalize_strict(line["text"])
                    ):
                        failures.append({"code": "BARCODE_OCR_MISMATCH"})
                else:
                    observations["ocr"] = {}
                    failures.append({"code": "MULTIPLE_OCR_VALUES" if distinct else "OCR_TEXT_MISSING"})
            if "barcode" in recipe.channels:
                import tagreader

                bgr = (
                    frame
                    if frame is not None
                    else cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
                )
                codes = sorted({t.text for t in tagreader.read_tag(bgr) if t.text}) if task is None else sorted({r.barcode for r in task.reads if r.barcode})
                detail["barcodes"] = codes
                if len(codes) != 1:
                    failures.append(
                        {
                            "code": (
                                "BARCODE_MISSING" if not codes else "MULTIPLE_BARCODES"
                            )
                        }
                    )
                else:
                    fields = brand.barcode_records.get(codes[0])
                    if fields is None:
                        failures.append(
                            {"code": "BARCODE_UNREGISTERED", "actual": codes[0]}
                        )
                    else:
                        observations["barcode"] = fields
            return {
                "observations": observations,
                "details": detail,
                "failures": failures,
                "model_hash": self.model_hash,
            }
        except Exception as exc:
            self.error = str(exc)
            raise
        finally:
            self.lock.release()

    def _auto_read(self, frame, *, diagnostics=None):
        self.load()
        import pipeline
        return pipeline.process_task(frame, self.recognizer, diagnostics=diagnostics)

    def test_auto(self, frame):
        """Run the production OCR path on a fresh frame without writing a photo."""
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("이전 영상 처리가 아직 끝나지 않았습니다.")
        try:
            from PIL import Image

            self.error = None
            model_started = time.perf_counter()
            self.load()
            ms_model_load = (time.perf_counter() - model_started) * 1000
            diagnostics = {}
            task = self._auto_read(frame, diagnostics=diagnostics)
            import cv2
            import importlib.metadata
            import tagreader
            diagnostics["runtime"] = {
                "opencv": cv2.__version__,
                "zxing": importlib.metadata.version("zxing-cpp"),
                "python": sys.version.split()[0],
                "source": str(Path(tagreader.__file__).resolve()),
                "report_version": 1,
            }
            reads = []
            for read in task.reads:
                lines = []
                for line, crop in zip(read.lines, read.line_crops):
                    import cv2
                    preview = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
                    preview.thumbnail((800, 500))
                    memory = io.BytesIO()
                    preview.save(memory, format="JPEG", quality=80)
                    lines.append({
                        **line, "crop_width": crop.shape[1], "crop_height": crop.shape[0],
                        "preview": "data:image/jpeg;base64," + base64.b64encode(memory.getvalue()).decode(),
                    })
                reads.append({
                    "barcode": read.barcode, "barcode_format": read.barcode_format,
                    "verdict": read.verdict.status,
                    "verdict_label": read.verdict.label,
                    "verdict_detail": read.verdict.detail,
                    "stage": read.stage,
                    "lines": lines,
                })
            return {
                "frame_width": frame.shape[1], "frame_height": frame.shape[0],
                "ok": len(task.reads) == 1 and task.reads[0].verdict.ok,
                "reads": reads, "error": task.error,
                "ms_barcode": task.ms_barcode, "ms_ocr": task.ms_ocr,
                "ms_model_load": ms_model_load,
                "ms_total": task.ms_total,
                "barcode_diagnostics": diagnostics,
            }
        except Exception as exc:
            self.error = str(exc)
            raise
        finally:
            self.lock.release()

    def status(self):
        return {
            "loaded": self.recognizer is not None,
            "local_assets_present": (self.directory / "manifest.json").exists(),
            "model": "PARSeq",
            "model_hash": self.model_hash,
            "error": self.error,
            "busy": self.lock.locked(),
            "device": str(self.recognizer.device) if self.recognizer else None,
            "gpu_name": self.recognizer.gpu_name if self.recognizer else None,
            "missing_modules": missing_ocr_modules(),
        }
