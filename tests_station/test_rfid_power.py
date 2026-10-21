from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from fastapi.testclient import TestClient

from station.app import create_app
from station.devices import ReplayIO
from station.rfid import frame
from station.schema import StationConfig
from station.storage import Store
from test_bench import rig
from test_moving_api import line, prepare, issue, wait_state, EPC
from test_rfid import wire


@pytest.mark.parametrize("power", [None, 1900])
def test_initialization_sends_and_verifies_selected_power(wire, power):
    reader, port, _ = wire
    expected = 2600 if power is None else power
    payload = expected.to_bytes(2, "big")
    port.chunks = [frame(0x08, b"\x06", 1), frame(0x07, b"\x00", 1),
                   frame(0x08, b"\x06", 1), frame(0xB6, b"\x00", 1), frame(0xB7, payload, 1)]
    reader.initialize(*([] if power is None else [power]))
    assert reader.initialized and reader.power == expected
    assert port.writes[-2:] == [frame(0xB6, payload), frame(0xB7)]


@pytest.mark.parametrize("reject", ["set", "get"])
def test_power_rejection_never_leaves_reader_ready(wire, reject):
    reader, port, _ = wire
    port.chunks = [frame(0xB6, b"\x01" if reject == "set" else b"\x00", 1),
                   frame(0xB7, (2600).to_bytes(2, "big"), 1)]
    with pytest.raises(IOError, match="RFID power"):
        reader.set_power(1800)
    assert not reader.initialized and reader.last_error


def test_saved_power_reaches_existing_reader_reconnection_and_production(line, monkeypatch):
    c, app = line.client, line.app
    response = c.put("/api/bench/rfid/setup", json={"rfid_power": 2200})
    assert response.status_code == 200, response.text
    assert line.io.reader.power == 2200
    # An older client's partial RFID save must not reset the selected power.
    assert c.put("/api/bench/rfid/setup", json={"rfid_window_ms": 300}).status_code == 200
    assert c.get("/api/bench").json()["setup"]["rfid_power"] == 2200
    # The full connection settings endpoint applies the same device setting.
    body = c.get("/api/bench").json()["setup"]
    body["rfid_power"] = 2000
    assert c.put("/api/bench/setup", json=body).status_code == 200
    assert line.io.reader.power == app.state.controller.config.rfid_power == 2000
    assert app.state.store.get("bench_setup")["rfid_power"] == 2000
    del body["rfid_power"]
    assert c.put("/api/bench/setup", json=body).status_code == 200
    assert line.io.reader.power == 2000
    line.io.reader.initialized = False
    line.io.reset()
    assert line.io.reader.power == 2000
    powers = []

    def read(*args):
        powers.append(line.io.reader.power)
        return [{"epc": EPC}]

    monkeypatch.setattr(line.io.reader, "inventory_once", read)
    prepare(line, ("rfid",))
    issue(line, "start")
    assert c.put("/api/bench/rfid/setup", json={"rfid_power": 1500}).status_code == 409
    line.gpio.sensor(1, 0)
    wait_state(line, lambda s: bool(powers))
    line.gpio.sensor(2, 0)
    wait_state(line, lambda s: s["session"]["count"] == 1)
    assert powers == [2000]


@pytest.mark.parametrize("saved,expected", [({}, 2100), ({"rfid_power": 1800}, 1800)])
def test_restart_restores_power_before_hardware_initialization(tmp_path, monkeypatch, saved, expected):
    store = Store(tmp_path / "data")
    store.put("bench_setup", saved)
    store.close()
    path = tmp_path / "config.json"
    path.write_text(StationConfig(mode="HARDWARE", rfid_power=2100).model_dump_json())
    monkeypatch.setenv("TXRX_CONFIG", str(path))
    initialized = []

    def hardware(config):
        initialized.append(config.rfid_power)
        return ReplayIO()

    monkeypatch.setattr("station.hardware.GpioIO", hardware)
    camera = SimpleNamespace(connect=lambda: None, close=lambda: None,
                             status=lambda: {"connected": False})
    app = create_app(tmp_path / "data", camera=camera)
    with TestClient(app):
        assert initialized == [expected]
        assert app.state.controller.config.rfid_power == app.state.bench.setup.rfid_power == expected


@pytest.mark.parametrize("failure", ["reader", "storage"])
def test_failed_save_preserves_previous_power(line, monkeypatch, failure):
    app = line.app
    before = app.state.store.get("bench_setup")
    if failure == "reader":
        def reject(power):
            raise IOError("RFID power SET rejected")
        monkeypatch.setattr(line.io.reader, "set_power", reject)
    else:
        event = app.state.store.event
        def reject_event(kind, *args, **kwargs):
            if kind == "BENCH_RFID_SETUP_SAVED":
                raise IOError("storage failed")
            return event(kind, *args, **kwargs)
        monkeypatch.setattr(app.state.store, "event", reject_event)
    response = line.client.put("/api/bench/rfid/setup", json={"rfid_power": 1800})
    assert response.status_code == 422, response.text
    assert app.state.bench.setup.rfid_power == line.io.config.rfid_power == line.io.reader.power == 2600
    assert app.state.store.get("bench_setup") == before


@pytest.mark.parametrize("power", [-1, 2601, 2000.5])
def test_invalid_power_is_rejected_without_saving(rig, power):
    c, app = rig
    response = c.put("/api/bench/rfid/setup", json={"rfid_power": power})
    assert response.status_code == 422
    assert app.state.bench.setup.rfid_power == 2600


def test_stop_does_not_wait_for_power_setting_response(line, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = line.io.reader.set_power

    def delayed(power):
        entered.set()
        assert release.wait(3)
        original(power)

    monkeypatch.setattr(line.io.reader, "set_power", delayed)
    with ThreadPoolExecutor() as pool:
        saving = pool.submit(line.client.put, "/api/bench/rfid/setup", json={"rfid_power": 2000})
        try:
            assert entered.wait(1)
            stopping = pool.submit(line.client.post, "/api/bench/stop", json={})
            response = stopping.result(timeout=1)
            assert response.status_code == 200, response.text
            assert not line.io.snapshot()["motor_requested"]
        finally:
            release.set()
        assert saving.result().status_code == 200
