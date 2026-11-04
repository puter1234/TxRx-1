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
from .vision_trace import record_operation, stage

ROOT = Path(__file__).resolve().parents[1]

OCR_MODULES = ("PIL", "torch", "torchvision", "timm", "pytorch_lightning", "yaml", "lmdb", "nltk", "zxingcpp", "onnxruntime", "ultralytics")


def missing_ocr_modules():
    return [name for name in OCR_MODULES if importlib.util.find_spec(name) is None]


def _reads_as_target(text: str, brand: Brand, targets: dict) -> bool:
    """The target product code appears in the line, with look-alike characters
    (O/0, I/1, B/8, S/5 ...) treated as the same and other text around it ignored."""
    from ocr.normalize import normalize_loose, normalize_strict

    if not brand.options or any(o.key not in targets for o in brand.options):
        return False
    code = normalize_loose("".join(normalize_strict(targets[o.key]) for o in brand.options))
    return bool(code) and code in normalize_loose(text)


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


VIEW_WIDTH = 1600


def result_view(frame, found, lines, brand, targets):
    """The OCR input (gained green channel) with each tag and read line drawn; JPEG bytes.

    Green: a line that reads as the target, and a tag that holds one. Red: a tag without
    one. Grey: other lines the reader saw.
    """
    import cv2
    import numpy as np
    from tagreader.preprocess import prepare_ocr_source
    gray = prepare_ocr_source(frame)
    scale = VIEW_WIDTH / gray.shape[1]
    view = cv2.cvtColor(cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA), cv2.COLOR_GRAY2BGR)
    green, red, grey = (40, 200, 60), (40, 40, 230), (170, 170, 170)
    full = frame.shape[1] / 4000  # tag boxes come in detection pixels
    hit_tags = set()
    for line in lines:
        quad = line.get("quad_source")
        if quad is None:
            continue
        hit = _reads_as_target(line["text"], brand, targets)
        if hit:
            hit_tags.add(line.get("roi_index"))
        points = (np.asarray(quad, np.float64) * scale).astype(np.int32)
        cv2.polylines(view, [points], True, green if hit else grey, 4 if hit else 2)
    for index, tag in enumerate(found.get("tags", [])):
        x1, y1, x2, y2 = (np.asarray(tag["roi"], np.float64) * full * scale).astype(int)
        cv2.rectangle(view, (x1, y1), (x2, y2), green if index in hit_tags else red, 4)
    ok, data = cv2.imencode(".jpg", view, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return data.tobytes() if ok else None


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
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Vision:
    def __init__(self, model_dir: Path | None = None, *, locator="yolo26"):
        self.directory = model_dir or ROOT / "models/parseq"
        self.locator = locator
        # The last inspected frame as the reader saw it, with what it found drawn on it.
        self.last_view = None
        self.recognizer = None
        self.lock = threading.Lock()
        self.model_lock = threading.Lock()
        self.model_hash = None
        self.error = None
        self.trace_directory = ROOT / "runtime/diagnostics"

    @record_operation("locator.load")
    def prepare_locator(self, locator=None):
        if (locator or self.locator) == "yolo26":
            from tagreader.model_pipeline import get_locator
            get_locator()

    def source_error(self, status, locator=None):
        # Any camera size is used; frames are brought to the 48MP layout before reading.
        return None
        if (locator or self.locator) != "yolo26" or not status.get("connected"):
            return None
        from tagreader.model_pipeline import validate_source_size
        profile = status.get("profile") or {}
        try:
            validate_source_size(status.get("width") or profile.get("width"),
                                 status.get("height") or profile.get("height"))
        except ValueError as exc:
            return str(exc)
        return None

    def prepare_capture(self, status, locator=None):
        error = self.source_error(status, locator)
        if error:
            raise ValueError(error)
        self.prepare_locator(locator)

    @record_operation("parseq.load")
    def load(self):
        with self.model_lock:
            self._load()

    def loading(self):
        return self.recognizer is None and self.model_lock.locked()

    def warm_up(self):
        """Load the models in the background at start-up, with one reading for the GPU.

        Loaded on first use instead, they held the first process test or job for
        tens of seconds and stalled the whole station while they loaded.
        """
        import logging
        try:
            self.load()
            self.prepare_locator()
            from PIL import Image
            self.recognizer.read_batch([Image.new("RGB", (128, 32), "white")])
        except Exception as exc:
            logging.getLogger(__name__).warning("VISION_WARM_UP_FAILED: %s", exc)

    def _load(self):
        if self.recognizer is not None:
            return
        from ocr.core import resolve_device
        device = resolve_device()
        self.model_hash = verify_model(self.directory)
        # Preserve Recognizer.read, tokenizer, official transform, GPU/CPU selection.
        import torch
        from ocr.core import Recognizer, build_transform

        sys.path.insert(0, str(self.directory / "source"))
        from strhub.models.utils import create_model

        with stage("parseq.create_model"):
            model = create_model("parseq", pretrained=False)
        with stage("parseq.load_weights"):
            state = torch.load(
                self.directory / "parseq-bb5792a6.pt", map_location="cpu", weights_only=True
            )
            model.model.load_state_dict(state, strict=True)
        recognizer = Recognizer.__new__(Recognizer)
        recognizer.model_name = "parseq"
        recognizer.device = device
        recognizer.gpu_name = (
            torch.cuda.get_device_name(recognizer.device)
            if recognizer.device.type == "cuda"
            else ""
        )
        with stage("parseq.to_device"):
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

    @record_operation("production.inspect")
    def _inspect(self, source, brand: Brand, recipe: Recipe):
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("이전 영상 처리가 아직 끝나지 않았습니다.")
        try:
            self.error = None
            import cv2
            import numpy as np
            from tagreader.model_pipeline import to_source

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
            if width * height > 48_000_000:
                raise ValueError("검사 영상은 4,800만 화소 이하만 지원합니다.")
            observations, detail, failures = {}, {}, []
            task = None
            if "ocr" in recipe.channels and recipe.tag_count:
                bgr = to_source(frame if frame is not None else cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR))
                found = {}
                task = self._auto_read(bgr, diagnostics=found if self.locator == "yolo26" else None,
                                       decode_values=False,
                                       accept=lambda text: _reads_as_target(text, brand, recipe.targets))
                lines = [line for read in task.reads for line in read.lines]
                self.last_view = result_view(bgr, found, lines, brand, recipe.targets)
                detail["ocr_lines"] = lines
                detail["ocr_ms"] = task.ms_ocr
                detail["ocr_device"] = str(getattr(self.recognizer, "device", "unknown"))
                detail["ocr_error"] = task.error
                # Every tag or sticker must be there, and each must carry one line that
                # reads as the target product; other lines on it (price, size) are ignored.
                tags = len(found["tags"]) if "tags" in found else len(task.reads)
                by_tag = {}
                for index, read in enumerate(task.reads):
                    for line in read.lines:
                        by_tag.setdefault(line.get("roi_index", index), []).append(line)
                matched = [key for key, group in by_tag.items()
                           if any(_reads_as_target(line["text"], brand, recipe.targets) for line in group)]
                detail["tag_count"], detail["tags_matched"] = tags, len(matched)
                tag_failures = []
                if tags != recipe.tag_count:
                    tag_failures.append({"code": "TAG_COUNT_MISMATCH", "expected": str(recipe.tag_count), "actual": str(tags)})
                if len(matched) < tags:
                    tag_failures.append({"code": "OCR_TAG_UNMATCHED", "actual": f"{len(matched)}/{tags}"})
                failures += tag_failures
                observations["ocr"] = {} if tag_failures else dict(recipe.targets)
            elif "ocr" in recipe.channels:
                bgr = to_source(frame if frame is not None else cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR))
                found = {}
                task = self._auto_read(bgr, diagnostics=found if self.locator == "yolo26" else None,
                                       decode_values="barcode" in recipe.channels,
                                       accept=lambda text: _serial_fields(text, brand) is not None)
                self.last_view = result_view(bgr, found, [l for r in task.reads for l in r.lines], brand, recipe.targets)
                candidates = []
                for read in task.reads:
                    for line in read.lines:
                        fields = _serial_fields(line["text"], brand)
                        if fields is not None:
                            candidates.append((fields, line, read.barcode))
                detail["ocr_lines"] = [line for read in task.reads for line in read.lines]
                detail["ocr_ms"] = task.ms_ocr
                detail["ocr_device"] = str(getattr(self.recognizer, "device", "unknown"))
                detail["ocr_error"] = task.error
                distinct = {tuple(sorted(fields.items())) for fields, _, _ in candidates}
                if len(distinct) == 1:
                    fields, line, linked_barcode = candidates[0]
                    observations["ocr"] = fields
                    detail["ocr_serial"] = line["text"]
                    from ocr.normalize import normalize_strict
                    if "barcode" in recipe.channels and len(recipe.barcode_targets) == 1 and linked_barcode and (
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
                if task is None and self.locator == "yolo26":
                    import pipeline
                    task = pipeline.process_task(bgr, None, locator=self.locator, decode_values=True)
                codes = [t.text for t in tagreader.read_tag(bgr) if t.text] if task is None else [r.barcode for r in task.reads if r.barcode]
                # Separate registered tables identify label types. Keep duplicate
                # values from distinct labels so two requested labels require two reads.
                detail["barcodes"] = codes
                if len(codes) != len(recipe.barcode_targets):
                    failures.append(
                        {
                            "code": (
                                "BARCODE_MISSING" if len(codes) < len(recipe.barcode_targets) else "MULTIPLE_BARCODES"
                            )
                        }
                    )
                else:
                    from itertools import permutations
                    tables = [brand.barcode_records if target == "tag" else brand.barcode_poly_records
                              for target in recipe.barcode_targets]
                    matches = [[table.get(code) for table, code in zip(tables, order)]
                               for order in permutations(codes)]
                    matches = [rows for rows in matches if all(row is not None for row in rows)]
                    if not matches:
                        failures.append({"code": "BARCODE_UNREGISTERED", "actual": ", ".join(codes)})
                    else:
                        fields = matches[0][0]
                        if any(row != fields for rows in matches for row in rows):
                            failures.append({"code": "BARCODE_LABEL_MISMATCH"})
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

    def _auto_read(self, frame, *, diagnostics=None, decode_values=True, locator=None, accept=None):
        self.load()
        import pipeline
        return pipeline.process_task(frame, self.recognizer, diagnostics=diagnostics,
                                     decode_values=decode_values, locator=locator or self.locator,
                                     accept=accept)

    @record_operation("test_auto")
    def test_auto(self, frame, *, include_previews=True, crop_images=None, locator=None, accept=None):
        """Run the selected locator and return the actual prepared OCR inputs."""
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("이전 영상 처리가 아직 끝나지 않았습니다.")
        try:
            from PIL import Image

            self.error = None
            model_started = time.perf_counter()
            self.load()
            ms_model_load = (time.perf_counter() - model_started) * 1000
            diagnostics = {}
            task = self._auto_read(frame, diagnostics=diagnostics, decode_values=False, locator=locator,
                                   accept=accept)
            import cv2
            import importlib.metadata
            import tagreader
            diagnostics["runtime"] = {
                "opencv": cv2.__version__,
                "zxing": importlib.metadata.version("zxing-cpp"),
                "python": sys.version.split()[0],
                "source": str(Path(tagreader.__file__).resolve()),
                "report_version": 2,
            }
            reads = []
            for read in task.reads:
                lines = []
                for line, crop in zip(read.lines, read.line_crops):
                    item = {**line, "crop_width": crop.shape[1], "crop_height": crop.shape[0]}
                    if include_previews:
                        preview = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
                        memory = io.BytesIO()
                        preview.save(memory, format="PNG")
                        item["preview"] = "data:image/png;base64," + base64.b64encode(memory.getvalue()).decode()
                    if crop_images is not None:
                        crop_images.append(crop)
                    lines.append(item)
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
                "mode": "ocr_only",
                "ok": any(read.verdict.status == "ocr_read" for read in task.reads),
                "reads": reads, "error": task.error,
                "ms_barcode": task.ms_barcode, "ms_ocr": task.ms_ocr,
                "ms_model_load": ms_model_load,
                "ms_total": task.ms_total,
                "ocr_device": str(getattr(self.recognizer, "device", "unknown")),
                "ocr_gpu_name": getattr(self.recognizer, "gpu_name", ""),
                "ocr_batch_size": max((line.get("batch_size", 1)
                                       for read in task.reads for line in read.lines), default=0),
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
            "locator": self.locator,
            "model_hash": self.model_hash,
            "error": self.error,
            "busy": self.lock.locked(),
            "device": str(self.recognizer.device) if self.recognizer else None,
            "gpu_name": self.recognizer.gpu_name if self.recognizer else None,
            "missing_modules": missing_ocr_modules(),
        }
