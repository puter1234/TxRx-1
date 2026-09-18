from types import SimpleNamespace
import pytest
from station import windows_camera as win


def fake_controls(monkeypatch, ignore=False):
    state = {"gain": 100, "auto": True, "calls": []}
    class Driver:
        def Get(self, prop): return state["gain"], 1 if state["auto"] else 2
        def Set(self, prop, value, flags):
            state["calls"].append((value, flags))
            if not ignore:
                state["gain"], state["auto"] = value, flags == 1
    api = Driver()
    def read(graph):
        return [{"name": "gain", "value": state["gain"], "min": 100, "max": 6400, "step": 1,
                 "flags": "inactive" if state["auto"] else "", "menu": {}},
                {"name": "gain_auto", "value": int(state["auto"]), "flags": "", "menu": {}}], {
                    "gain": (api, 9, 3), "gain_auto": (api, 9, 3)}
    monkeypatch.setattr(win, "_controls", read)
    return state


def test_manual_gain_switches_mode_before_value(monkeypatch):
    state = fake_controls(monkeypatch)
    win._set_controls(None, {"gain": 500, "gain_auto": 0})
    assert state["calls"] == [(100, 2), (500, 2)]
    assert state["gain"] == 500


def test_unsupported_gain_is_not_silently_accepted(monkeypatch):
    monkeypatch.setattr(win, "_controls", lambda graph: ([], {}))
    with pytest.raises(ValueError, match="gain"):
        win._set_controls(None, {"gain": 500})


def test_ignored_driver_change_fails_readback(monkeypatch):
    state = fake_controls(monkeypatch, ignore=True)
    state["auto"] = False
    with pytest.raises(ValueError, match="일치"):
        win._set_controls(None, {"gain": 500})


def test_out_of_range_gain_not_sent_to_driver(monkeypatch):
    state = fake_controls(monkeypatch)
    state["auto"] = False
    with pytest.raises(ValueError, match="범위"):
        win._set_controls(None, {"gain": 6401})
    assert state["calls"] == []
