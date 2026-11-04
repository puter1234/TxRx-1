"""Two-stage locator with OCR crops from the preprocessed 48MP source."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading
import time

import cv2
import numpy as np
from PIL import Image
from station.vision_trace import stage
from .preprocess import GREEN_GAIN

SOURCE_SIZE = (8000, 6000)
DETECTION_SIZE = (4000, 3000)
BUNDLE = Path(__file__).resolve().parents[1] / "vendor/barcode_pipeline"
_instance = None
_load_lock = threading.Lock()


def validate_source_size(width, height):
    """Any camera size is accepted; frames are brought to SOURCE_SIZE by to_source()."""


def to_source(frame):
    """The frame at SOURCE_SIZE, scaled to fit with its aspect kept and its edge pixels repeated around it."""
    h, w = frame.shape[:2]
    if (w, h) == SOURCE_SIZE:
        return frame
    scale = min(SOURCE_SIZE[0] / w, SOURCE_SIZE[1] / h)
    nw, nh = round(w * scale), round(h * scale)
    resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)
    x, y = (SOURCE_SIZE[0] - nw) // 2, (SOURCE_SIZE[1] - nh) // 2
    return cv2.copyMakeBorder(resized, y, SOURCE_SIZE[1] - nh - y, x, SOURCE_SIZE[0] - nw - x, cv2.BORDER_REPLICATE)


def verify_bundle(directory=BUNDLE):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    required = {"tag_detector/models/tag_label.onnx", "barcode_segmenter/models/barcode.onnx",
                "tag_detector/models/deployment.json", "barcode_segmenter/models/deployment.json"}
    if not required <= set(manifest["files"]):
        raise ValueError("택 검출과 바코드 분할 모델 묶음이 불완전합니다.")
    for name, expected in manifest["files"].items():
        path = (directory / name).resolve()
        if directory.resolve() not in path.parents or not path.is_file():
            raise ValueError("바코드 모델 파일이 없습니다: " + name)
    return manifest


class ModelLocator:
    def __init__(self):
        self.manifest = verify_bundle()
        try:
            from vendor.barcode_pipeline.tag_detector.tagdet.infer import TagDetector
            from vendor.barcode_pipeline.barcode_segmenter.barseg.infer import BarcodeSegmenter
        except ImportError as exc:
            raise RuntimeError("택 검출과 바코드 분할 실행 패키지가 필요합니다. requirements-barcode-pipeline.txt를 설치하세요.") from exc
        tag = json.loads((BUNDLE / "tag_detector/models/deployment.json").read_text())
        seg = json.loads((BUNDLE / "barcode_segmenter/models/deployment.json").read_text())
        self.detector = TagDetector(BUNDLE / "tag_detector/models/tag_label.onnx",
                                    imgsz=tag["imgsz"], conf=tag["confidence"], threads=tag["threads"])
        self.segmenter = BarcodeSegmenter(BUNDLE / "barcode_segmenter/models/barcode.onnx",
                                          imgsz=seg["imgsz"], conf=seg["conf"],
                                          dedup_iou=seg["mask_dedup_iou"], threads=tag["threads"])
        self.padding = tag["roi_padding"]
        self.lock = threading.Lock()

    def locate(self, original, diagnostics, *, text=True, barcodes=False):
        """Tags, their text lines in reading order and, only for barcode values, their barcodes."""
        started = time.perf_counter()
        # This is the only full-frame resampling. Never replace the retained source.
        with stage("frame_resize"):
            detection = cv2.resize(original, DETECTION_SIZE, interpolation=cv2.INTER_AREA)
        resize_ms = (time.perf_counter() - started) * 1000
        with self.lock:
            with stage("tag_detection"):
                found = self.detector.predict(detection, roi_padding=self.padding)
            tag_ms = found["timing_ms"]["pipeline_without_decode"]
            segmentation_ms = text_ms = ocr_preprocess_ms = 0.
            records = []
            for roi_index, det in enumerate(found["detections"]):
                roi = det["roi_bbox_xyxy"]
                x1, y1, x2, y2 = roi
                instances = []
                if barcodes:
                    raw = detection[y1:y2, x1:x2].copy()
                    with stage(f"barcode_segmentation roi={roi_index} shape={raw.shape}"):
                        result = self.segmenter.predict(raw, roi_xyxy=roi, source_size=list(DETECTION_SIZE),
                                                        target_size=list(SOURCE_SIZE))
                    segmentation_ms += result["timing_ms"]["total_without_decode"]
                    instances = result["instances"]
                lines = {"regions": [], "tag": None, "origin": (0, 0)}
                if text:
                    from .text_lines import find_tag_lines
                    with stage(f"tag_lines roi={roi_index}"):
                        lines = find_tag_lines(original, roi)
                    text_ms += lines["elapsed_ms"]
                    ocr_preprocess_ms += lines["preprocess_ms"]
                shared = {"roi_index": roi_index, "roi_12mp": roi, "tag": lines["tag"], "origin": lines["origin"]}
                for index, instance in enumerate(instances):
                    records.append({"quad": instance["quad_target"], "polygon": instance["polygon_target"],
                                    "confidence": instance["confidence"], **shared,
                                    "regions": lines["regions"] if index == 0 else []})
                if text and not instances:
                    corners = (np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], float) * 2).tolist()
                    records.append({"quad": corners, "polygon": corners, "confidence": 0., **shared,
                                    "regions": lines["regions"]})
        if text and records:
            diagnostics["ocr_preprocessing"] = {"mode": "green_gain", "gain": GREEN_GAIN,
                "width": original.shape[1], "height": original.shape[0], "ms": ocr_preprocess_ms}
        elapsed = (time.perf_counter() - started) * 1000
        diagnostics.update(locator="yolo26", source_width=SOURCE_SIZE[0], source_height=SOURCE_SIZE[1],
            detection_width=DETECTION_SIZE[0], detection_height=DETECTION_SIZE[1],
            model_commit=self.manifest["commit"], prepare_ms=resize_ms, align_ms=0., decoded=0,
            status="located" if records else "not_detected",
            tags=[{"roi": det["roi_bbox_xyxy"]} for det in found["detections"]],
            texts=[{"quad": region["quad_target"]} for record in records for region in record["regions"]],
            regions=[{"quad": record["quad"], "polygon": record["polygon"], "stage": "yolo26"}
                     for record in records],
            stages=[{"stage": "yolo26", "candidates": len(records), "tag_count": len(found["detections"]),
                "working_width": DETECTION_SIZE[0], "working_height": DETECTION_SIZE[1],
                "detect_ms": elapsed, "tag_ms": tag_ms, "segment_ms": segmentation_ms,
                "text_ms": text_ms, "preprocess_ms": resize_ms,
                "attempted": 0, "decoded": 0, "decode_ms": 0.}])
        return records


def get_locator():
    global _instance
    with _load_lock:
        if _instance is None:
            _instance = ModelLocator()
        return _instance


def trim_symbols(text):
    """Product codes start and end with a letter or digit; marks like * or " around them are dropped."""
    import re
    return re.sub(r"^[^0-9A-Za-z가-힣]+|[^0-9A-Za-z가-힣]+$", "", text)


LINE_MARGIN = 0.3  # detector boxes end at the ink; this much of the line height is added at each end


def widen(quad, ratio=LINE_MARGIN):
    """The same box, longer at both ends of its reading direction."""
    p = np.asarray(quad, dtype=np.float64).reshape(4, 2)
    along, across = p[1] - p[0], p[3] - p[0]
    if np.linalg.norm(across) > np.linalg.norm(along):  # a vertical line reads along its long side
        along, across = across, along
    length = np.linalg.norm(along)
    if length == 0:
        return p.tolist()
    shift = along / length * ratio * np.linalg.norm(across)
    ends = [-1, 1, 1, -1] if np.linalg.norm(p[1] - p[0]) >= np.linalg.norm(p[3] - p[0]) else [-1, -1, 1, 1]
    return (p + np.outer(ends, shift)).tolist()


def crop_original(original, quad):
    """Sample full-resolution source pixels at the recovered text orientation."""
    points = np.asarray(quad, dtype=np.float32).reshape(4, 2)
    if not np.isfinite(points).all():
        raise ValueError("문자 영역 좌표가 올바르지 않습니다.")
    width = max(2, round(float(np.linalg.norm(points[1] - points[0]))) + 1)
    height = max(2, round(float(np.linalg.norm(points[3] - points[0]))) + 1)
    width, height = min(width, SOURCE_SIZE[0]), min(height, SOURCE_SIZE[1])
    matrix = cv2.getAffineTransform(points[[0, 1, 3]], np.float32([[0, 0], [width - 1, 0], [0, height - 1]]))
    return cv2.warpAffine(original, matrix, (width, height), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))


def decode_original(original, quad):
    from .decode import decode_quad
    from .geometry import quad_radius
    points = np.asarray(quad, dtype=float)
    cx, cy = points.mean(axis=0)
    radius = quad_radius(points) * 1.5
    x0, y0 = max(0, int(cx - radius)), max(0, int(cy - radius))
    x1, y1 = min(original.shape[1], int(cx + radius) + 1), min(original.shape[0], int(cy + radius) + 1)
    if x1 <= x0 or y1 <= y0:
        return None, None
    gray = cv2.cvtColor(original[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    return decode_quad(gray, points - [x0, y0])


READ_BATCH = 4  # lines per OCR call; each is read upright and turned 180 degrees in the same call


def looks_like_code(text):
    """A product-code-shaped line: 8 to 22 letters and digits, at least two of each."""
    import re
    code = re.sub(r"[^A-Z0-9]", "", text.upper())
    return 8 <= len(code) <= 22 and sum(c.isalpha() for c in code) >= 2 and sum(c.isdigit() for c in code) >= 2


def process_frame(original, recognizer, *, diagnostics=None, decode_values=False, accept=None):
    """Read each tag's lines, longest first, in small batches until one is accepted.

    accept(text) says whether a line is the one looked for (the job's product code);
    without it the first product-code-shaped line ends the tag.
    """
    from pipeline import TagRead, TaskResult
    from ocr.normalize import Verdict, compare, normalize_strict
    from .geometry import deskew_angle
    if original.ndim != 3 or original.shape[2] != 3 or original.dtype != np.uint8:
        raise ValueError("카메라의 BGR 원본 프레임이 필요합니다.")
    original = to_source(original)
    accept = accept or looks_like_code
    started = time.perf_counter()
    diagnostics = diagnostics if diagnostics is not None else {}
    with stage("locator.initialize"):
        locator = get_locator()
    records = locator.locate(original, diagnostics, text=recognizer is not None, barcodes=decode_values)
    location_ms = (time.perf_counter() - started) * 1000
    reads, ocr_ms, decode_ms, align_ms = [], 0., 0., 0.
    for record in records:
        code = fmt = None
        if decode_values:
            t0 = time.perf_counter()
            code, fmt = decode_original(original, record["quad"])
            decode_ms += (time.perf_counter() - t0) * 1000
        crops, lines, accepted = [], [], None
        regions = record["regions"] if recognizer is not None else []
        for start in range(0, len(regions), READ_BATCH):
            t0 = time.perf_counter()
            batch, metadata = [], []
            for region in regions[start:start + READ_BATCH]:
                # quad_target belongs to this very source frame, never a second capture.
                quad = np.asarray(widen(region["quad_target"])) - record["origin"]
                crop = cv2.cvtColor(crop_original(record["tag"], quad), cv2.COLOR_GRAY2BGR)
                for rotation in (0, 180):
                    batch.append(crop if rotation == 0 else cv2.rotate(crop, cv2.ROTATE_180))
                    metadata.append({"rotation_degrees": rotation, "quad_source": region["quad_target"],
                                     "side": region["side_in_aligned_image"], "roi_index": record["roi_index"]})
            align_ms += (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter()
            images = [Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)) for crop in batch]
            outputs = recognizer.read_batch(images) if hasattr(recognizer, "read_batch") else [recognizer.read(image) for image in images]
            if len(outputs) != len(batch):
                raise RuntimeError("OCR 결과 수가 입력한 글자 줄 수와 다릅니다.")
            ocr_ms += (time.perf_counter() - t0) * 1000
            crops += batch
            lines += [{**out, "text": trim_symbols(out["text"]), **meta} for out, meta in zip(outputs, metadata)]
            accepted = next((line for line in lines[-len(batch):] if accept(line["text"])), None)
            if accepted is not None:
                break
        if decode_values:
            verdict = compare(code, [(line["text"], line["confidence"]) for line in lines])
        else:
            usable = [line for line in lines if normalize_strict(line["text"])]
            best = accepted or (max(usable, key=lambda line: line["confidence"]) if usable else None)
            verdict = (Verdict("ocr_read", None, best["text"], best["confidence"], "문자 읽음") if best else
                       Verdict("no_text", None, None, label="문자 미검출"))
        best_index = next((i for i, line in enumerate(lines) if line["text"] == verdict.text), 0)
        reads.append(TagRead(barcode=code, barcode_format=fmt, angle=deskew_angle(np.asarray(record["quad"])),
                             stage="yolo26", verdict=verdict, lines=lines, line_crops=crops,
                             crop=crops[best_index] if crops else None))
    decoded = sum(bool(read.barcode) for read in reads)
    diagnostics.update(decoded=decoded, align_ms=align_ms)
    if decoded:
        diagnostics["status"] = "decoded"
    elif decode_values and records:
        diagnostics["status"] = "decode_failed"
    diagnostics["stages"][0].update(attempted=len(records) if decode_values else 0,
                                     decoded=decoded, decode_ms=decode_ms)
    return TaskResult(reads=reads, ms_barcode=location_ms + decode_ms + align_ms, ms_ocr=ocr_ms,
                      ms_total=(time.perf_counter() - started) * 1000,
                      error=None if records else "바코드 위치를 찾지 못했습니다")
