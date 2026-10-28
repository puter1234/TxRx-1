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


def test_ocr_views_retain_same_frame_without_reading_or_closing_camera(rig):
    client, app = rig
    image = np.full((480, 640, 3), (10, 20, 30), np.uint8)
    camera = app.state.camera
    profile = camera.backend.profile.model_dump()
    assert client.post('/api/bench/camera/apply', json={"profile": profile, "save": True, "expected_revision": 0}).status_code == 200
    stream = camera.stream
    camera.read_latest = lambda: (image, {"seq": 101})
    app.state.vision.test_auto = lambda frame, **kw: {"barcode_diagnostics": {"locator": "yolo26", "tags": []}, "reads": []}
    response = client.post('/api/bench/ocr/read', json={"locator": "yolo26"})
    assert response.status_code == 200, response.text
    url = response.json()['preview_url']
    camera.read_latest = lambda: pytest.fail('display must not acquire another frame')
    preprocessed = client.get(url + '?view=tag_input')
    assert preprocessed.status_code == 200, preprocessed.text
    rendered = cv2.imdecode(np.frombuffer(preprocessed.content, np.uint8), cv2.IMREAD_COLOR)
    assert rendered.shape == (960, 960, 3)
    assert (rendered[480, 480] == 70).all()
    original = cv2.imdecode(np.frombuffer(client.get(url + '?original=true').content, np.uint8), cv2.IMREAD_COLOR)
    np.testing.assert_array_equal(original, image)
    assert camera.stream is stream and not stream.closed
    assert client.get(url + '?view=barcode_input&region=4').status_code == 422
