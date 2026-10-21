"""Same-frame coordinate and pixel contracts, with deterministic model/OCR doubles."""
import threading
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

import pipeline
from tagreader import model_pipeline as model


@pytest.fixture
def camera_frame():
    frame = np.full((6000, 8000, 3), 32, dtype=np.uint8)
    # Fine color detail disappears in a 2x downsample. OCR must retain it.
    region = frame[1220:1259, 1040:1399]
    region[:, ::2] = (13, 71, 239)
    region[:, 1::2] = (241, 113, 17)
    region[0, 0] = (19, 37, 61)
    return frame


@pytest.fixture
def locator(monkeypatch, camera_frame):
    instance = model.ModelLocator.__new__(model.ModelLocator)
    instance.manifest = {"commit": "test"}
    instance.padding = .08
    instance.lock = threading.Lock()
    roi = [500, 600, 900, 900]
    points = np.float32([[20, 40], [180, 40], [180, 100], [20, 100]])
    quad48 = ((points + roi[:2]) * 2).tolist()
    text_quad = [[1040., 1220.], [1398., 1220.], [1398., 1258.], [1040., 1258.]]
    calls = []

    def detect(image, roi_padding):
        assert image.shape == (3000, 4000, 3) and roi_padding == .08
        calls.append("detect")
        return {"detections": [{"roi_bbox_xyxy": roi}], "timing_ms": {"pipeline_without_decode": 1}}

    def segment(image, roi_xyxy, source_size, target_size):
        calls.append("segment")
        assert roi_xyxy == roi and source_size == [4000, 3000] and target_size == [8000, 6000]
        expected = cv2.resize(camera_frame[1200:1800, 1000:1800], (400, 300), interpolation=cv2.INTER_AREA)
        np.testing.assert_array_equal(image, expected)
        return {"instances": [{"quad_target": quad48, "polygon_target": quad48, "confidence": .9}],
                "timing_ms": {"total_without_decode": 2}}

    def text(image, instances, actual_roi, source_size, target_size):
        calls.append("text")
        assert actual_roi == roi and source_size == [4000, 3000] and target_size == [8000, 6000]
        return {"regions": [{"barcode_index": 0, "quad_target": text_quad,
                             "crop_size": [180, 20], "side_in_aligned_image": "above"}], "elapsed_ms": 1}

    instance.detector = SimpleNamespace(predict=detect)
    instance.segmenter = SimpleNamespace(predict=segment)
    instance.extract_text = text
    monkeypatch.setattr(model, "get_locator", lambda: instance)
    return instance, calls, quad48, text_quad


def test_same_48mp_frame_supplies_full_resolution_text_and_both_orientations(camera_frame, locator, monkeypatch):
    _, calls, quad48, text_quad = locator
    expected = camera_frame[1220:1259, 1040:1399].copy()
    received = []

    class Reader:
        def read_batch(self, images):
            received.extend(np.asarray(image).copy() for image in images)
            return [{"text": text, "confidence": confidence, "ms": 1}
                    for text, confidence in (("wrong", .2), ("AB12", .99))]

    def forbidden(*args, **kwargs):
        pytest.fail("OCR-only must not decode a barcode")

    monkeypatch.setattr(model, "decode_original", forbidden)
    diagnostics = {}
    task = pipeline.process_task(camera_frame, Reader(), locator="yolo26", decode_values=False, diagnostics=diagnostics)
    assert calls == ["detect", "segment", "text"]
    assert task.reads[0].verdict.text == "AB12"
    np.testing.assert_array_equal(received[0], expected[:, :, ::-1])
    np.testing.assert_array_equal(received[1], expected[::-1, ::-1, ::-1])
    np.testing.assert_array_equal(task.reads[0].line_crops[0], expected)
    np.testing.assert_array_equal(camera_frame[1220:1259, 1040:1399], expected)
    assert received[0].shape == (39, 359, 3)
    assert diagnostics["source_width"] == 8000 and diagnostics["detection_width"] == 4000
    assert diagnostics["regions"][0]["quad"] == quad48
    assert task.reads[0].lines[1]["rotation_degrees"] == 180
    assert task.reads[0].lines[0]["quad_source"] == text_quad


@pytest.mark.parametrize("size", [(4000, 3000), (1920, 1080), (7999, 6000)])
def test_lower_resolution_is_rejected_before_loading_models(size, monkeypatch):
    def forbidden():
        pytest.fail("Invalid resolution must be rejected before model load")
    monkeypatch.setattr(model, "get_locator", forbidden)
    frame = np.broadcast_to(np.uint8(0), (size[1], size[0], 3))
    with pytest.raises(ValueError, match="48MP"):
        pipeline.process_task(frame, None, locator="yolo26")


def test_barcode_only_uses_original_pixels_without_parseq_or_text_extraction(camera_frame, locator, monkeypatch):
    _, calls, quad48, _ = locator
    def decode(frame, quad):
        assert frame is camera_frame and quad == quad48
        return "AB12", "Code128"
    monkeypatch.setattr(model, "decode_original", decode)
    result = pipeline.process_task(camera_frame, None, locator="yolo26", decode_values=True)
    assert calls == ["detect", "segment"]
    assert result.reads[0].barcode == "AB12" and not result.reads[0].lines


def test_production_defaults_to_models_and_checks_registered_code(camera_frame, locator):
    from station.vision import Vision
    from station.schema import Brand, Recipe
    from station.rules import judge
    vision = Vision()
    vision.load = lambda: None
    vision.recognizer = SimpleNamespace(read_batch=lambda images: [
        {"text": text, "confidence": .9, "ms": 1} for text in ("PRICE", "AB12")])
    brand = Brand(id="test", name="Test", options=[
        {"key": "code", "label": "Code", "values": ["AB12", "CD34"]}])
    recipe = Recipe(brand_id="test", brand_revision=1, targets={"code": "CD34"}, channels=["ocr"])
    result = vision.inspect_frame(camera_frame, brand, recipe)
    assert result["observations"] == {"ocr": {"code": "AB12"}}
    assert judge(recipe, result["observations"])[0]["code"] == "TARGET_MISMATCH"
    assert result["details"]["ocr_lines"][1]["rotation_degrees"] == 180


def test_bundle_has_pinned_source_and_verified_weights():
    manifest = model.verify_bundle()
    assert manifest["commit"] == "100a3025192e7ea06a1eefcf32c2b7d7b16ba9a9"
    assert len(manifest["files"]) == 14


def test_live_preview_keeps_original_text_pixels(camera_frame, locator):
    import base64
    from station.vision import Vision
    vision = Vision()
    vision.load = lambda: None
    vision.recognizer = SimpleNamespace(device="cpu", read_batch=lambda images: [
        {"text": "AB12", "confidence": .9, "ms": 1} for _ in images])
    result = vision.test_auto(camera_frame)
    line = result["reads"][0]["lines"][0]
    assert line["preview"].startswith("data:image/png;base64,")
    restored = cv2.imdecode(np.frombuffer(base64.b64decode(line["preview"].split(",", 1)[1]), np.uint8), cv2.IMREAD_COLOR)
    np.testing.assert_array_equal(restored, camera_frame[1220:1259, 1040:1399])


def test_evidence_preserves_full_48mp_frame(camera_frame, tmp_path):
    from station.evidence import save_frame, save_upload
    path, meta = save_frame(tmp_path, "frame", camera_frame, {"seq": 48}, None)
    image = cv2.imread(str(path))
    assert image.shape == camera_frame.shape
    np.testing.assert_array_equal(image, camera_frame)
    # The upload path also accepts an original 48MP file.
    uploaded, _ = save_upload(tmp_path, "uploaded", path.read_bytes())
    assert cv2.imread(str(uploaded)).shape == (6000, 8000, 3)
