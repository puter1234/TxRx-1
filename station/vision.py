"""Local PARSeq inference. Neither model creation nor weights use a network path."""

from __future__ import annotations

import hashlib
import json
import sys
import threading
from pathlib import Path

from .schema import Brand, Recipe

ROOT = Path(__file__).resolve().parents[1]


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
            from PIL import Image
            from ocr.core import to_rgb

            if isinstance(source, (str, Path)):
                with Image.open(source) as original:
                    original.load()
                    image = to_rgb(original)
            else:
                image = Image.fromarray(cv2.cvtColor(source, cv2.COLOR_BGR2RGB))
            if image.width * image.height > 24_000_000:
                raise ValueError("이미지는 2,400만 화소 이하만 지원합니다.")
            observations, detail, failures = {}, {}, []
            if "ocr" in recipe.channels:
                self.load()
                observations["ocr"] = {}
                for region in brand.ocr_regions:
                    if region.field not in recipe.targets:
                        continue
                    x, y, w, h = region.box
                    crop = image.crop(
                        (
                            int(x * image.width),
                            int(y * image.height),
                            int((x + w) * image.width),
                            int((y + h) * image.height),
                        )
                    )
                    if region.rotation:
                        crop = crop.rotate(region.rotation, expand=True)
                    out = self.recognizer.read(crop)
                    detail[region.field] = {
                        **out,
                        "box": region.box,
                        "rotation": region.rotation,
                    }
                    # Only trim outer whitespace. Never fill a missing field from the target.
                    observations["ocr"][region.field] = out["text"].strip()
                    if (
                        region.min_char_confidence is not None
                        and out["min_char"] < region.min_char_confidence
                    ):
                        failures.append(
                            {
                                "code": "OCR_LOW_CONFIDENCE",
                                "field": region.field,
                                "actual": out["min_char"],
                                "minimum": region.min_char_confidence,
                            }
                        )
                        break
                    actual = observations["ocr"][region.field]
                    if actual != recipe.targets[region.field]:
                        failures.append(
                            {
                                "code": (
                                    "TARGET_MISMATCH"
                                    if actual
                                    else "REQUIRED_FIELD_MISSING"
                                ),
                                "channel": "ocr",
                                "field": region.field,
                                "expected": recipe.targets[region.field],
                                "actual": actual,
                            }
                        )
                        break
            if "barcode" in recipe.channels:
                import tagreader

                bgr = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
                codes = sorted({t.text for t in tagreader.read_tag(bgr) if t.text})
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
        }
