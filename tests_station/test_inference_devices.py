"""TEMP: GPU indicator. What each model runs on, as /api/status reports it."""
import sys
import types

from station import counting
from station.vision import inference_devices


class Session:
    def __init__(self, first):
        self.first = first

    def get_providers(self):
        return [self.first, "CPUExecutionProvider"]


def test_nothing_loaded_shows_nothing(monkeypatch):
    monkeypatch.setattr(counting, "last_counter", None)
    monkeypatch.setitem(sys.modules, "tagreader.text_detector", types.SimpleNamespace(_instance=None))
    assert inference_devices({"device": None}) == {"ocr": None, "detector": None, "wappen": None}


def test_reports_the_providers_that_really_run(monkeypatch):
    detector = types.SimpleNamespace(session=Session("CPUExecutionProvider"))
    monkeypatch.setitem(sys.modules, "tagreader.text_detector", types.SimpleNamespace(_instance=detector))
    counter = counting.ObjectCounter.__new__(counting.ObjectCounter)
    # Asked for the GPU, but the ONNX session fell back to the CPU.
    counter.device = 0
    counter.model = types.SimpleNamespace(predictor=types.SimpleNamespace(
        model=types.SimpleNamespace(session=Session("CPUExecutionProvider"))))
    monkeypatch.setattr(counting, "last_counter", counter)
    assert inference_devices({"device": "cuda:0"}) == {"ocr": "GPU", "detector": "CPU", "wappen": "CPU"}
    counter.model.predictor.model.session = Session("CUDAExecutionProvider")
    detector.session = Session("CUDAExecutionProvider")
    assert inference_devices({"device": "cpu"}) == {"ocr": "CPU", "detector": "GPU", "wappen": "GPU"}
    # Before the first prediction the requested device is shown; a .pt model reports its torch device.
    counter.model.predictor = None
    assert inference_devices({"device": "cpu"})["wappen"] == "GPU"
    counter.model.predictor = types.SimpleNamespace(model=types.SimpleNamespace(device="cpu"))
    assert inference_devices({"device": "cpu"})["wappen"] == "CPU"
    counter.model = None
    assert inference_devices({"device": "cpu"})["wappen"] == "CPU"


def test_status_carries_the_devices(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from station.app import create_app

    monkeypatch.setattr(counting, "last_counter", None)
    with TestClient(create_app(tmp_path)) as client:
        client.post("/api/auth/setup", json={"password": "123456"})
        assert client.get("/api/status").json()["inference"]["wappen"] is None
