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
    # Alternating green detail disappears in a 2x downsample. OCR must retain it.
    region = frame[1220:1259, 1040:1399]
    region[:, ::2] = (13, 21, 239)
    region[:, 1::2] = (241, 63, 17)
    region[0, 0] = (19, 37, 61)
    return frame


TAG = (1000, 1200, 1800, 1800)  # the ROI below in 48MP pixels
TEXT_QUAD = [[1040., 1220.], [1398., 1220.], [1398., 1260.], [1040., 1260.]]


def gained(frame, x0, y0, x1, y1):
    green = np.clip(frame[y0:y1, x0:x1, 1].astype(float) * 3.5, 0, 255).astype(np.uint8)
    return np.repeat(green[:, :, None], 3, axis=2)


@pytest.fixture
def locator(monkeypatch, camera_frame):
    from tagreader import text_detector
    instance = model.ModelLocator.__new__(model.ModelLocator)
    instance.manifest = {"commit": "test"}
    instance.padding = .08
    instance.lock = threading.Lock()
    roi = [500, 600, 900, 900]
    points = np.float32([[20, 40], [180, 40], [180, 100], [20, 100]])
    quad48 = ((points + roi[:2]) * 2).tolist()
    calls = []
    boxes = [TEXT_QUAD]

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

    def text(image, min_side=None):
        calls.append("text")
        # The tag alone, already gained for OCR, at full resolution.
        assert image.shape == (600, 800)
        np.testing.assert_array_equal(image, gained(camera_frame, *TAG)[:, :, 0])
        return [(np.asarray(q, float) - TAG[:2], .9) for q in boxes]

    instance.detector = SimpleNamespace(predict=detect)
    instance.segmenter = SimpleNamespace(predict=segment)
    monkeypatch.setattr(model, "get_locator", lambda: instance)
    monkeypatch.setattr(text_detector, "get_detector", lambda: SimpleNamespace(boxes=text))
    return instance, calls, quad48, boxes


# TEXT_QUAD widened by 0.3 of its 40 px height at each end: 12 px.
WIDE = (1028, 1220, 1411, 1261)


def test_same_48mp_frame_supplies_full_resolution_text_and_both_orientations(camera_frame, locator, monkeypatch):
    _, calls, _, _ = locator
    original_crop = camera_frame.copy()
    expected = gained(camera_frame, *WIDE)
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
    # Lines come from the tag itself; the barcode segmenter is not run for OCR.
    assert calls == ["detect", "text"]
    assert task.reads[0].verdict.text == "AB12"
    np.testing.assert_array_equal(received[0], expected[:, :, ::-1])
    np.testing.assert_array_equal(received[1], expected[::-1, ::-1, ::-1])
    np.testing.assert_array_equal(task.reads[0].line_crops[0], expected)
    np.testing.assert_array_equal(camera_frame, original_crop)
    assert received[0].shape == (41, 383, 3)
    assert diagnostics["source_width"] == 8000 and diagnostics["detection_width"] == 4000
    assert diagnostics["regions"][0]["quad"] == [[1000., 1200.], [1800., 1200.], [1800., 1800.], [1000., 1800.]]
    assert diagnostics["ocr_preprocessing"]["width"] == 8000
    assert diagnostics["ocr_preprocessing"]["height"] == 6000
    assert diagnostics["ocr_preprocessing"]["gain"] == 3.5
    assert task.reads[0].lines[1]["rotation_degrees"] == 180
    assert task.reads[0].lines[0]["quad_source"] == TEXT_QUAD
    assert task.reads[0].lines[0]["roi_index"] == 0


def line(x, y, length, height=20):
    return [[x, y], [x + length, y], [x + length, y + height], [x, y + height]]


@pytest.mark.parametrize("accept,batches,read", [
    (None, [8, 8], 8),                              # the first code-shaped line ends the tag
    (lambda text: text == "W279000", [8, 8], 8),    # the job's own code ends it
    (lambda text: False, [8, 8, 4], 10),            # nothing matches: every line is read once each way
])
def test_lines_are_read_longest_first_in_batches_until_one_matches(camera_frame, locator, accept, batches, read):
    _, calls, _, boxes = locator
    # Ten lines of different lengths in shuffled order, and one too short to be a code.
    lengths = [300, 120, 260, 220, 400, 160, 200, 340, 100, 180]
    boxes[:] = [line(1100, 1300 + 30 * i, n) for i, n in enumerate(lengths)] + [line(1100, 1700, 60)]
    sizes = []

    def read_batch(images):
        sizes.append(len(images))
        texts = []
        for index, image in enumerate(images):
            batch, upright = len(sizes), index % 2 == 0
            # The second batch holds a code line, read correctly only when turned.
            texts.append("NOISE" if batch != 2 or upright else
                         {3: "AB12CD34", 5: "W279000"}.get(index, "NOISE"))
        return [{"text": text, "confidence": .5, "ms": 1} for text in texts]

    task = pipeline.process_task(camera_frame, SimpleNamespace(read_batch=read_batch), locator="yolo26",
                                 decode_values=False, accept=accept)
    assert sizes == batches
    lines = task.reads[0].lines
    assert [l["rotation_degrees"] for l in lines] == [0, 180] * (len(lines) // 2)
    widths = [crop.shape[1] for crop in task.reads[0].line_crops[::2]]
    assert widths == sorted(widths, reverse=True) and len(widths) == read
    assert all(l["quad_source"] != line(1100, 1700, 60) for l in lines)


def test_lines_are_cropped_along_their_own_long_side(camera_frame, locator, monkeypatch):
    _, calls, _, boxes = locator
    boxes[:] = [[[1040., 1220.], [1078., 1220.], [1078., 1578.], [1040., 1578.]],
                np.array([[1100., 1400.], [1400., 1500.], [1390., 1530.], [1090., 1430.]]).tolist()]
    monkeypatch.setattr(model, "decode_original", lambda *a: pytest.fail("OCR-only must not decode"))
    shapes = []

    def read_batch(images):
        shapes.extend(image.size for image in images)
        return [{"text": "AB12", "confidence": .9, "ms": 1} for _ in images]
    task = pipeline.process_task(camera_frame, SimpleNamespace(read_batch=read_batch), locator="yolo26",
                                 decode_values=False)
    assert "segment" not in calls and len(task.reads) == 1 and len(task.reads[0].lines) == 4
    # PIL sizes are (width, height): both lines are read lying down, in both directions.
    assert all(w > 4 * h for w, h in shapes)


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


def test_live_preview_shows_the_preprocessed_pixels_sent_to_ocr(camera_frame, locator):
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
    np.testing.assert_array_equal(restored, gained(camera_frame, *WIDE))


def test_ocr_preparation_precedes_interpolation_and_matches_model_gain():
    from tagreader.preprocess import prepare_ocr_source
    from vendor.barcode_pipeline.barcode_segmenter.barseg.common import prepare_roi
    original = np.zeros((8, 12, 3), np.uint8)
    original[:, 1::2, 1] = 160
    before = original.copy()
    prepared = prepare_ocr_source(original)
    np.testing.assert_array_equal(prepared, prepare_roi(original)[:, :, 1])
    assert prepared.shape == original.shape[:2]
    quad = [[.5, 1], [8.5, 1], [8.5, 5], [.5, 5]]
    actual = model.crop_original(prepared, quad)
    # Saturation must happen before interpolation. Cropping raw pixels first
    # would blend green to 80 and then saturate to 255 instead of producing 128.
    np.testing.assert_array_equal(actual, np.full((5, 9), 128, np.uint8))
    np.testing.assert_array_equal(original, before)


def test_evidence_preserves_full_48mp_frame(camera_frame, tmp_path):
    from station.evidence import save_frame, save_upload
    path, meta = save_frame(tmp_path, "frame", camera_frame, {"seq": 48}, None)
    image = cv2.imread(str(path))
    assert image.shape == camera_frame.shape
    np.testing.assert_array_equal(image, camera_frame)
    # The upload path also accepts an original 48MP file.
    uploaded, _ = save_upload(tmp_path, "uploaded", path.read_bytes())
    assert cv2.imread(str(uploaded)).shape == (6000, 8000, 3)


@pytest.mark.parametrize("raw,clean", [("*HUTS6D71314105*", "HUTS6D71314105"), ('"W279,000"', "W279,000"),
                                       ("-.HWTS 6C651 OW 095.", "HWTS 6C651 OW 095"), ("**", "")])
def test_marks_around_a_read_line_are_dropped(raw, clean):
    assert model.trim_symbols(raw) == clean
