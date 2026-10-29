"""Local detectors and directional, once-per-track crossing counts."""
from __future__ import annotations

from pathlib import Path
import math
import hashlib
import os
import time

from .schema import FlowSettings


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class CrossingTracker:
    def __init__(self, settings: FlowSettings):
        self.settings = settings
        self.tracks = {}
        self.serial = 0
        self.total = 0

    def update(self, boxes, now=None):
        now = time.monotonic() if now is None else now
        cfg = self.settings
        self.tracks = {k: v for k, v in self.tracks.items() if now - v["seen"] <= cfg.track_lost_ms / 1000}
        centers = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in boxes]
        pairs = sorted((math.dist(t["center"], p), k, i)
                       for k, t in self.tracks.items() for i, p in enumerate(centers))
        used_tracks, matched = set(), {}
        for distance, k, i in pairs:
            if distance <= cfg.match_distance and k not in used_tracks and i not in matched:
                used_tracks.add(k)
                matched[i] = k
        crossed = []
        for i, center in enumerate(centers):
            if i not in matched:
                self.serial += 1
                k = self.serial
                self.tracks[k] = {"center": center, "seen": now, "armed": False, "counted": False}
            else:
                k = matched[i]
            t = self.tracks[k]
            position = (center[0 if cfg.axis == "x" else 1] - cfg.line) * cfg.direction
            if position < -cfg.hysteresis:
                t["armed"] = True
            if position > cfg.hysteresis and t["armed"] and not t["counted"]:
                t["counted"] = True
                self.total += 1
                crossed.append(k)
            t.update(center=center, seen=now)
        return crossed


class ObjectCounter:
    def __init__(self, settings: FlowSettings):
        self.settings = settings
        self.tracker = CrossingTracker(settings)
        self.model = None
        self.device = "cpu"
        self.identity = {"counter": settings.counter}
        if settings.counter == "yolo":
            path = Path(settings.model_path).expanduser().resolve()
            if path.suffix.lower() not in (".pt", ".onnx") or not path.is_file():
                raise ValueError("YOLO 모델 파일을 확인하세요: " + str(path))
            # Explicit existing local paths only. Never download a default model.
            os.environ.setdefault("YOLO_AUTOINSTALL", "false")
            self.identity.update(path=str(path), sha256=file_sha256(path))
            try:
                from ultralytics import YOLO
            except ImportError as exc:
                raise ValueError("YOLO 실행 모듈이 없습니다. requirements-counting.txt를 설치하세요.") from exc
            import torch
            if torch.cuda.is_available():
                if path.suffix.lower() == ".pt":
                    self.device = 0
                else:
                    import onnxruntime
                    if "CUDAExecutionProvider" in onnxruntime.get_available_providers():
                        self.device = 0
            self.identity["device"] = "cuda:0" if self.device == 0 else "cpu"
            self.model = YOLO(str(path), task="detect")
        elif settings.counter == "cvzone":
            try:
                import cvzone
            except ImportError as exc:
                raise ValueError("CVZone 실행 모듈이 없습니다. requirements-counting.txt를 설치하세요.") from exc
            self.cvzone = cvzone

    def detect(self, frame):
        import cv2
        cfg = self.settings
        height, width = frame.shape[:2]
        x, y, w, h = cfg.roi
        left, top = int(x * width), int(y * height)
        cropped = frame[top:max(top + 1, int((y + h) * height)), left:max(left + 1, int((x + w) * width))]
        if self.model is not None:
            result = self.model.predict(cropped, imgsz=cfg.image_size, conf=cfg.confidence,
                                        classes=cfg.classes or None, verbose=False, device=self.device)[0]
            boxes = result.boxes.xyxy.cpu().numpy().tolist() if result.boxes is not None else []
        else:
            gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
            _, mask = cv2.threshold(gray, cfg.threshold, 255, cv2.THRESH_BINARY_INV if cfg.invert else cv2.THRESH_BINARY)
            _, contours = self.cvzone.findContours(cropped.copy(), mask, minArea=cfg.min_area, drawCon=True)
            boxes = [[a, b, a + c, b + d] for item in contours for a, b, c, d in [item["bbox"]]]
        return [[(a + left) / width, (b + top) / height, (c + left) / width, (d + top) / height] for a, b, c, d in boxes]

    def update(self, frame, now=None):
        started = time.perf_counter()
        boxes = self.detect(frame)
        crossed = self.tracker.update(boxes, now)
        return {"boxes": boxes, "crossed": crossed, "total": self.tracker.total,
                "width": frame.shape[1], "height": frame.shape[0], "inference_ms": (time.perf_counter() - started) * 1000,
                "tracks": [{"id": k, **v} for k, v in self.tracker.tracks.items()]}
