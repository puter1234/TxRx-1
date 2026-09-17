"""Real model/fixture regression, without opening a browser or visual inspection."""

import os
from pathlib import Path
import pytest


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
    roi = tmp_path / "single-line.png"
    assert cv2.imwrite(str(roi), original.crop)
    target = original.verdict.text.strip()
    brand = Brand(
        id="regression",
        name="기존 인식 회귀",
        options=[{"key": "text", "label": "문자", "values": [target]}],
        ocr_regions=[{"field": "text", "box": [0, 0, 1, 1]}],
    )
    recipe = Recipe(
        brand_id=brand.id, brand_revision=1, targets={"text": target}, channels=["ocr"]
    )
    result = v.inspect(roi, brand, recipe)
    assert result["observations"]["ocr"]["text"] == target
    assert not result["failures"]
    assert "barcode" not in result["observations"]
