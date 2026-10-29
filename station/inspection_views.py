"""Reproduce detector display inputs from the retained inspection frame on demand.

Only display requests enter this module. No camera reads or model inference occur.
The original full-resolution image remains untouched.
"""
import json
from pathlib import Path

import cv2
from fastapi import HTTPException

BUNDLE = Path(__file__).resolve().parents[1] / "vendor/barcode_pipeline"


def view_options(diagnostics):
    if diagnostics.get("locator") != "yolo26":
        return []
    return [{"view": "tag_input", "region": 0, "label": "택 검출 입력"}] + [
        {"view": "barcode_input", "region": i, "label": f"바코드 입력 {i + 1}"}
        for i, _ in enumerate(diagnostics.get("tags", []))] + (
            [{"view": "ocr_input", "region": 0, "label": "OCR 전처리"}]
            if diagnostics.get("ocr_preprocessing") else [])


def inspection_view(image, diagnostics, view, region=0):
    if view == "barcode_crop":
        regions = diagnostics.get("regions", [])
        if not 0 <= region < len(regions):
            raise HTTPException(422, "선택한 바코드 영역이 없습니다.")
        from tagreader.model_pipeline import crop_original
        from tagreader.preprocess import prepare_ocr_source
        source = prepare_ocr_source(image) if diagnostics.get("locator") == "yolo26" else image
        crop = crop_original(source, regions[region]["quad"])
        # Segmentation quads may start on the short edge. Display the barcode
        # along its long edge so a tall crop is not reduced to a thin sliver.
        return cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE) if crop.shape[0] > crop.shape[1] else crop
    if view == "ocr_input":
        if region != 0 or not diagnostics.get("ocr_preprocessing"):
            raise HTTPException(422, "OCR 전처리 결과가 없습니다.")
        from tagreader.preprocess import prepare_ocr_source
        return prepare_ocr_source(image)
    if diagnostics.get("locator") != "yolo26" or view not in ("tag_input", "barcode_input") or region < 0:
        raise HTTPException(422, "선택한 전처리 화면이 없습니다.")
    from tagreader.model_pipeline import DETECTION_SIZE
    working = cv2.resize(image, DETECTION_SIZE, interpolation=cv2.INTER_AREA)
    if view == "tag_input":
        if region != 0:
            raise HTTPException(422, "선택한 전처리 화면이 없습니다.")
        from vendor.barcode_pipeline.tag_detector.tagdet.common import prepare_image
        from vendor.barcode_pipeline.tag_detector.tagdet.geometry import letterbox
        config = json.loads((BUNDLE / "tag_detector/models/deployment.json").read_text())
        prepared, _ = prepare_image(working)
        return letterbox(prepared, config["imgsz"])[0]
    tags = diagnostics.get("tags", [])
    if region >= len(tags):
        raise HTTPException(422, "선택한 택 영역이 없습니다.")
    x1, y1, x2, y2 = tags[region]["roi"]
    from vendor.barcode_pipeline.barcode_segmenter.barseg.common import prepare_roi
    from ultralytics.data.augment import LetterBox
    config = json.loads((BUNDLE / "barcode_segmenter/models/deployment.json").read_text())
    prepared = prepare_roi(working[y1:y2, x1:x2])
    # Same LetterBox configuration as the segmentation ONNX runner. The final
    # channel layout and /255 tensor normalization do not change display colors.
    return LetterBox(new_shape=(config["imgsz"], config["imgsz"]), auto=False, stride=32)(image=prepared)
