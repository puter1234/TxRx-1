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
from .preprocess import GREEN_GAIN, prepare_ocr_source

SOURCE_SIZE = (8000, 6000)
DETECTION_SIZE = (4000, 3000)
BUNDLE = Path(__file__).resolve().parents[1] / "vendor/barcode_pipeline"
_instance = None
_load_lock = threading.Lock()


def validate_source_size(width, height):
    if (width, height) != SOURCE_SIZE:
        raise ValueError(f"48MP 촬영 원본이 필요합니다. 카메라를 8000 x 6000으로 설정하세요. 현재 {width} x {height}")


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
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("바코드 모델 파일이 변경됐습니다: " + name)
    return manifest


class ModelLocator:
    def __init__(self):
        self.manifest = verify_bundle()
        try:
            from vendor.barcode_pipeline.tag_detector.tagdet.infer import TagDetector
            from vendor.barcode_pipeline.barcode_segmenter.barseg.infer import BarcodeSegmenter
            from vendor.barcode_pipeline.barcode_segmenter.barseg.text_regions import extract_text_regions
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
        self.extract_text = extract_text_regions
        self.lock = threading.Lock()

    def locate(self, original, diagnostics, *, text=True):
        started = time.perf_counter()
        # This is the only full-frame resampling. Never replace the retained source.
        with stage("frame_resize"):
            detection = cv2.resize(original, DETECTION_SIZE, interpolation=cv2.INTER_AREA)
        resize_ms = (time.perf_counter() - started) * 1000
        with self.lock:
            with stage("tag_detection"):
                found = self.detector.predict(detection, roi_padding=self.padding)
            tag_ms = found["timing_ms"]["pipeline_without_decode"]
            segmentation_ms = text_ms = 0.
            records = []
            for roi_index, det in enumerate(found["detections"]):
                roi = det["roi_bbox_xyxy"]
                x1, y1, x2, y2 = roi
                raw = detection[y1:y2, x1:x2].copy()
                with stage(f"barcode_segmentation roi={roi_index} shape={raw.shape}"):
                    result = self.segmenter.predict(raw, roi_xyxy=roi, source_size=list(DETECTION_SIZE),
                                                    target_size=list(SOURCE_SIZE))
                segmentation_ms += result["timing_ms"]["total_without_decode"]
                regions = []
                if text and result["instances"]:
                    with stage(f"text_regions roi={roi_index}"):
                        candidates = self.extract_text(raw, result["instances"], roi,
                                                       list(DETECTION_SIZE), list(SOURCE_SIZE))
                    regions = candidates["regions"]
                    text_ms += candidates["elapsed_ms"]
                for index, instance in enumerate(result["instances"]):
                    records.append({"quad": instance["quad_target"],
                        "polygon": instance["polygon_target"], "confidence": instance["confidence"],
                        "roi_index": roi_index, "roi_12mp": roi,
                        "regions": [region for region in regions if region["barcode_index"] == index]})
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


def crop_original(original, quad):
    """Sample full-resolution source pixels at the recovered text orientation."""
    points = np.asarray(quad, dtype=np.float32).reshape(4, 2)
    if not np.isfinite(points).all():
        raise ValueError("문자 영역 좌표가 올바르지 않습니다.")
    width = max(2, round(float(np.linalg.norm(points[1] - points[0]))) + 1)
    height = max(2, round(float(np.linalg.norm(points[3] - points[0]))) + 1)
    if width > SOURCE_SIZE[0] or height > SOURCE_SIZE[1]:
        raise ValueError("문자 영역이 촬영 원본 크기를 초과했습니다.")
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


def process_frame(original, recognizer, *, diagnostics=None, decode_values=False):
    from pipeline import TagRead, TaskResult
    from ocr.normalize import Verdict, compare, normalize_strict
    from .geometry import deskew_angle
    if original.ndim != 3 or original.shape[2] != 3 or original.dtype != np.uint8:
        raise ValueError("카메라의 BGR 원본 프레임이 필요합니다.")
    validate_source_size(original.shape[1], original.shape[0])
    started = time.perf_counter()
    diagnostics = diagnostics if diagnostics is not None else {}
    with stage("locator.initialize"):
        locator = get_locator()
    records = locator.locate(original, diagnostics, text=recognizer is not None)
    location_ms = (time.perf_counter() - started) * 1000
    ocr_source = None
    preprocessing_ms = 0.
    if recognizer is not None and any(record["regions"] for record in records):
        t0 = time.perf_counter()
        with stage("ocr_source_preprocess"):
            ocr_source = prepare_ocr_source(original)
        preprocessing_ms = (time.perf_counter() - t0) * 1000
        diagnostics["ocr_preprocessing"] = {"mode": "green_gain", "gain": GREEN_GAIN,
            "width": original.shape[1], "height": original.shape[0], "ms": preprocessing_ms}
    reads, ocr_ms, decode_ms, align_ms = [], 0., 0., 0.
    for record in records:
        code = fmt = None
        if decode_values:
            t0 = time.perf_counter()
            code, fmt = decode_original(original, record["quad"])
            decode_ms += (time.perf_counter() - t0) * 1000
        crops, metadata = [], []
        t0 = time.perf_counter()
        if recognizer is not None:
            for region in record["regions"]:
                # quad_target belongs to this very source frame, never a second capture.
                crop = cv2.cvtColor(crop_original(ocr_source, region["quad_target"]), cv2.COLOR_GRAY2BGR)
                for rotation in (0, 180):
                    crops.append(crop if rotation == 0 else cv2.rotate(crop, cv2.ROTATE_180))
                    metadata.append({"rotation_degrees": rotation, "quad_source": region["quad_target"],
                                     "side": region["side_in_aligned_image"], "roi_index": record["roi_index"]})
        align_ms += (time.perf_counter() - t0) * 1000
        lines = []
        if crops:
            t0 = time.perf_counter()
            images = [Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)) for crop in crops]
            outputs = recognizer.read_batch(images) if hasattr(recognizer, "read_batch") else [recognizer.read(image) for image in images]
            if len(outputs) != len(crops):
                raise RuntimeError("OCR 결과 수가 입력한 글자 줄 수와 다릅니다.")
            ocr_ms += (time.perf_counter() - t0) * 1000
            lines = [{**out, **meta} for out, meta in zip(outputs, metadata)]
        if decode_values:
            verdict = compare(code, [(line["text"], line["confidence"]) for line in lines])
        else:
            usable = [line for line in lines if normalize_strict(line["text"])]
            best = max(usable, key=lambda line: line["confidence"]) if usable else None
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
    return TaskResult(reads=reads, ms_barcode=location_ms + preprocessing_ms + decode_ms + align_ms, ms_ocr=ocr_ms,
                      ms_total=(time.perf_counter() - started) * 1000,
                      error=None if records else "바코드 위치를 찾지 못했습니다")
