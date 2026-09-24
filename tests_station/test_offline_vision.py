"""Real model/fixture regression, without opening a browser or visual inspection."""

import os
from pathlib import Path
import pytest


def test_live_frame_matches_saved_png_without_model(tmp_path, monkeypatch):
    import cv2
    import numpy as np
    import tagreader

    from station.schema import Brand, Recipe
    from station.vision import Vision

    frame = np.zeros((24, 36, 3), dtype=np.uint8)
    frame[:, :18] = (17, 83, 241)
    path = tmp_path / "frame.png"
    assert cv2.imwrite(str(path), frame)
    seen = []

    def read_tag(image):
        seen.append(image.copy())
        return []

    monkeypatch.setattr(tagreader, "read_tag", read_tag)
    brand = Brand(id="test", name="Test", options=[{"key": "color", "label": "Color", "values": ["red"]}])
    recipe = Recipe(brand_id="test", brand_revision=1, targets={"color": "red"}, channels=["barcode"])
    vision = Vision()

    live = vision.inspect_frame(frame, brand, recipe)
    saved = vision.inspect(path, brand, recipe)

    assert live == saved
    assert len(seen) == 2 and np.array_equal(seen[0], seen[1])


def test_correction_matches_live_test_and_production_ocr(monkeypatch):
    import numpy as np

    from station.schema import Brand, Recipe
    from station.vision import Vision

    frame = np.full((60, 120, 3), 40, dtype=np.uint8)
    means = []

    class Reader:
        def read(self, crop):
            value = int(np.asarray(crop).mean())
            means.append(value)
            return {"text": str(value), "confidence": 0.9, "min_char": 0.9,
                    "chars": [], "ms": 1.0}

    vision = Vision()
    vision.recognizer = Reader()
    vision.load = lambda: None
    import pipeline
    from types import SimpleNamespace
    tag = SimpleNamespace(text="80", format="CODE39", angle=0, stage="test",
                          rotated=frame, _rotated_quad=np.array([[20, 20], [100, 20], [100, 40], [20, 40]]))
    def read_tag(image, **kwargs):
        tag.rotated = image
        return [tag]
    monkeypatch.setattr(pipeline.tagreader, "read_tag", read_tag)
    monkeypatch.setattr(pipeline, "_ordered_crops", lambda above, *args: [above])
    correction = {"gain": 2, "gamma": 1, "contrast": 1, "clahe": False}
    brand = Brand(id="test", name="Test", options=[{"key": "text", "label": "Text", "values": ["80"]}],
                  ocr_regions=[{"field": "text", "box": [0, 0, 1, 1]}])
    recipe = Recipe(brand_id="test", brand_revision=1, targets={"text": "80"}, channels=["ocr"])
    test_result = vision.test_auto(frame, correction)
    production = vision.inspect_frame(frame, brand, recipe, correction)
    assert test_result["reads"][0]["lines"][0]["text"] == "80"
    assert production["observations"]["ocr"]["text"] == "80"
    assert means == [80, 80]


def test_ocr_without_barcode_stops_before_model_inference(monkeypatch):
    import numpy as np
    import pipeline
    from station.schema import Brand, Recipe
    from station.vision import Vision

    frame = np.full((80, 160, 3), 40, dtype=np.uint8)
    monkeypatch.setattr(pipeline.tagreader, "read_tag", lambda *args, **kwargs: [])
    class Reader:
        device = "cpu"
        gpu_name = ""

        def __init__(self):
            self.calls = 0

        def read(self, image):
            self.calls += 1
            return {"text": "HUTS6A211BK095", "confidence": 0.9,
                    "min_char": 0.9, "chars": [], "ms": 1.0}

    vision = Vision()
    vision.recognizer = Reader()
    vision.load = lambda: None
    brand = Brand(id="hazzys", name="Hazzys", options=[
        {"key": "style", "label": "Style", "values": ["HUTS6A211"]},
        {"key": "color", "label": "Color", "values": ["BK"]},
        {"key": "size", "label": "Size", "values": ["095"]},
    ])
    recipe = Recipe(brand_id="hazzys", brand_revision=1, channels=["ocr"],
                    targets={"style": "HUTS6A211", "color": "BK", "size": "095"})
    result = vision.inspect_frame(frame, brand, recipe)
    assert result["observations"]["ocr"] == {}
    assert result["failures"] == [{"code": "OCR_TEXT_MISSING"}]
    assert vision.recognizer.calls == 0


@pytest.mark.slow
def test_real_parseq_without_network(tmp_path, monkeypatch):
    import socket
    import urllib.request

    def forbid(*args, **kwargs):
        raise AssertionError("Runtime network access attempted")

    monkeypatch.setattr(socket, "create_connection", forbid)
    monkeypatch.setattr(urllib.request, "urlopen", forbid)
    import torch

    monkeypatch.setattr(torch.hub, "load", forbid)
    monkeypatch.setattr(torch.hub, "load_state_dict_from_url", forbid)
    torch.set_num_threads(2)
    from station.vision import Vision
    from station.schema import Brand, Recipe
    import pipeline
    from tagreader.io import imread
    import cv2

    source = Path(
        os.environ.get("TXRX_TEST_IMAGE", "images/KakaoTalk_20260807_200206873.jpg")
    )
    if not source.exists():
        pytest.skip("Local private fixture required")
    v = Vision()
    v.load()
    legacy = pipeline.process_task(imread(source), v.recognizer)
    assert legacy.reads and legacy.reads[0].verdict.ok
    original = legacy.reads[0]
    assert original.crop is not None and original.verdict.text
    target = original.verdict.text.strip()
    brand = Brand(
        id="regression",
        name="기존 인식 회귀",
        options=[{"key": "text", "label": "문자", "values": [target]}],
    )
    recipe = Recipe(
        brand_id=brand.id, brand_revision=1, targets={"text": target}, channels=["ocr"]
    )
    result = v.inspect_frame(imread(source), brand, recipe)
    assert result["observations"]["ocr"]["text"] == target
    assert not result["failures"]
    assert "barcode" not in result["observations"]
