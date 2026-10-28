"""Display results use the retained frame, never a new camera acquisition."""
import numpy as np
import cv2
import pytest
from fastapi import HTTPException
from station.inspection_views import inspection_view
from tests_station.test_bench import rig


def test_tag_input_preserves_source_and_matches_detector_preprocessing():
    from vendor.barcode_pipeline.tag_detector.tagdet.common import prepare_image
    from vendor.barcode_pipeline.tag_detector.tagdet.geometry import letterbox
    source = np.zeros((6000, 8000, 3), np.uint8)
    source[:, :, 0] = 240
    source[:, :, 1] = np.arange(8000, dtype=np.uint8)
    source[:, :, 2] = 100
    before = source.copy()
    actual = inspection_view(source, {"locator": "yolo26"}, "tag_input")
    expected = letterbox(prepare_image(cv2.resize(source, (4000, 3000), interpolation=cv2.INTER_AREA))[0], 960)[0]
    np.testing.assert_array_equal(actual, expected)
    np.testing.assert_array_equal(source, before)
    assert actual.shape == (960, 960, 3)
    assert np.array_equal(actual[:, :, 0], actual[:, :, 1])
    assert (actual[0, 0] == 114).all()


@pytest.mark.parametrize("view,region", [("unknown", 0), ("tag_input", -1), ("tag_input", 1), ("barcode_input", 4)])
def test_unavailable_views_rejected(view, region):
    with pytest.raises(HTTPException) as error:
        inspection_view(np.zeros((20, 40, 3), np.uint8), {"locator": "yolo26", "tags": []}, view, region)
    assert error.value.status_code == 422


def test_barcode_crop_and_full_resolution_ocr_preparation_use_retained_pixels():
    source = np.full((48, 64, 3), (10, 20, 30), np.uint8)
    source[12:21, 10:31] = (90, 60, 40)
    original = source.copy()
    diagnostics = {"locator": "yolo26", "ocr_preprocessing": {"mode": "green_gain", "gain": 3.5},
                   "regions": [{"quad": [[10, 12], [30, 12], [30, 20], [10, 20]]}]}
    cropped = inspection_view(source, diagnostics, "barcode_crop", 0)
    np.testing.assert_array_equal(cropped, np.full((9, 21), 210, np.uint8))
    turned = {**diagnostics, "regions": [{"quad": [[10, 20], [10, 12], [30, 12], [30, 20]]}]}
    np.testing.assert_array_equal(inspection_view(source, turned, "barcode_crop"), cropped)
    raw_crop = inspection_view(source, {**diagnostics, "locator": "stripes"}, "barcode_crop")
    np.testing.assert_array_equal(raw_crop, source[12:21, 10:31])
    prepared = inspection_view(source, diagnostics, "ocr_input")
    assert prepared.shape == source.shape[:2]
    assert prepared[0, 0] == 70 and prepared[12, 10] == 210
    np.testing.assert_array_equal(source, original)
    with pytest.raises(HTTPException):
        inspection_view(source, diagnostics, "barcode_crop", 1)
    with pytest.raises(HTTPException):
        inspection_view(source, {}, "ocr_input")


@pytest.mark.parametrize("kind", ["ocr", "pipeline"])
def test_ocr_views_retain_same_frame_without_reading_or_closing_camera(rig, kind):
    client, app = rig
    image = np.full((480, 640, 3), (10, 20, 30), np.uint8)
    camera = app.state.camera
    profile = camera.backend.profile.model_dump()
    assert client.post('/api/bench/camera/apply', json={"profile": profile, "save": True, "expected_revision": 0}).status_code == 200
    stream = camera.stream
    camera.read_latest = lambda: (image, {"seq": 101})
    diagnostics = {"locator": "yolo26", "tags": [],
                   "ocr_preprocessing": {"mode": "green_gain", "gain": 3.5},
                   "regions": [{"quad": [[10, 12], [30, 12], [30, 20], [10, 20]]}]}
    app.state.vision.test_auto = lambda frame, **kw: {"barcode_diagnostics": diagnostics, "reads": []}
    response = client.post('/api/bench/ocr/read', json={"locator": "yolo26"})
    assert response.status_code == 200, response.text
    url = response.json()['preview_url']
    if kind == "pipeline":
        with app.state.sensor_ocr.lock:
            app.state.sensor_ocr.jobs.append({"id": "saved", "state": "passed", "frames": [
                {"seq": 101, "state": "passed", "image": image, "crops": [],
                 "result": {"barcode_diagnostics": diagnostics}}]})
        url = '/api/bench/pipeline/frames/saved/101'
    camera.read_latest = lambda: pytest.fail('display must not acquire another frame')
    preprocessed = client.get(url + '?view=tag_input')
    assert preprocessed.status_code == 200, preprocessed.text
    rendered = cv2.imdecode(np.frombuffer(preprocessed.content, np.uint8), cv2.IMREAD_COLOR)
    assert rendered.shape == (960, 960, 3)
    assert (rendered[480, 480] == 70).all()
    original = cv2.imdecode(np.frombuffer(client.get(url + '?original=true').content, np.uint8), cv2.IMREAD_COLOR)
    np.testing.assert_array_equal(original, image)
    prepared = client.get(url + '?view=ocr_input')
    assert prepared.status_code == 200
    rendered = cv2.imdecode(np.frombuffer(prepared.content, np.uint8), cv2.IMREAD_GRAYSCALE)
    np.testing.assert_array_equal(rendered, np.full((480, 640), 70, np.uint8))
    cropped = client.get(url + '?view=barcode_crop&region=0')
    assert cropped.status_code == 200
    rendered = cv2.imdecode(np.frombuffer(cropped.content, np.uint8), cv2.IMREAD_COLOR)
    np.testing.assert_array_equal(rendered, np.full((9, 21, 3), 70, np.uint8))
    assert camera.stream is stream and not stream.closed
    assert client.get(url + '?view=barcode_input&region=4').status_code == 422
