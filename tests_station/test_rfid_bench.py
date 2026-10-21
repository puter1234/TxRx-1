"""RFID bench API with the real GPIO adapter and serial frame decoder."""

import pytest

from station.rfid import frame
from station.bench import Bench
from station.devices import ReplayIO
from station.schema import StationConfig
from station.storage import Store
from test_bench import rig
from test_moving_api import line
from test_rfid import notice, wire


@pytest.mark.parametrize("has_tag", [False, True])
def test_bench_missed_round_keeps_reader_ready_for_next_read(line, wire, has_tag):
    reader, port, _ = wire
    line.io.reader.close()
    line.io.reader = reader
    response = line.client.put("/api/bench/rfid/setup", json={
        "rfid_protocol_confirmed": True, "rfid_window_ms": 100,
    })
    assert response.status_code == 200, response.text
    port.chunks = ([notice()] if has_tag else []) + [frame(0xFF, b"\x15", 1)]

    response = line.client.post("/api/bench/rfid", json={})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["ok"] is has_tag
    assert len(result["tags"]) == int(has_tag)
    assert result["detail"] == f"읽은 태그 {int(has_tag)}개"
    assert line.io.snapshot()["rfid_ready"] and reader.last_error is None
    assert not line.app.state.bench.rfid_busy

    port.chunks = [notice()]
    response = line.client.post("/api/bench/rfid", json={})
    assert response.status_code == 200, response.text
    assert response.json()["ok"] and len(response.json()["tags"]) == 1
    assert line.io.snapshot()["rfid_ready"]
    assert port.writes == [frame(0x27, b"\x22\x00\x05"), frame(0x28)] * 2


def test_bench_reinitializes_shared_reader_on_next_click_after_no_response(line, wire):
    reader, port, _ = wire
    line.io.reader.close()
    line.io.reader = reader
    assert line.client.put("/api/bench/rfid/setup", json={
        "rfid_protocol_confirmed": True, "rfid_window_ms": 100,
    }).status_code == 200
    response = line.client.post("/api/bench/rfid", json={})
    assert response.status_code == 422 and "RFID 응답이 없습니다" in response.text
    assert not line.io.snapshot()["rfid_ready"]
    port.chunks = [frame(0x08, b"\x06", 1), frame(0xAD, b"\x00", 1),
                   frame(0xB6, b"\x00", 1), frame(0xB7, (2600).to_bytes(2, "big"), 1), notice()]
    response = line.client.post("/api/bench/rfid", json={})
    assert response.status_code == 200 and response.json()["ok"], response.text
    assert line.io.snapshot()["rfid_ready"] and reader.last_error is None
    assert port.writes[2:4] == [frame(0x08), frame(0xAD, b"\xff")]


def test_standalone_bench_initializes_hopping_and_accepts_late_tag(rig, wire, monkeypatch):
    client, _ = rig
    reader, port, _ = wire
    monkeypatch.setattr("station.rfid.Reader", lambda path: reader)
    assert client.put("/api/bench/rfid/setup", json={
        "rfid_port": "/dev/test", "rfid_protocol_confirmed": True, "rfid_power": 2000,
    }).status_code == 200
    port.chunks = [frame(0x08, b"\x06", 1), frame(0xAD, b"\x00", 1),
                   frame(0xB6, b"\x00", 1), frame(0xB7, (2000).to_bytes(2, "big"), 1)]
    port.chunks += [b""] * 40 + [notice()]
    response = client.post("/api/bench/rfid", json={})
    assert response.status_code == 200 and response.json()["ok"], response.text
    assert frame(0xAD, b"\xff") in port.writes
    assert frame(0x27, b"\x22\x00\x05") in port.writes
    assert not port.is_open


@pytest.mark.parametrize("saved,expected", [({}, 5000), ({"rfid_window_ms": 500}, 5000),
                                           ({"rfid_window_ms": 1300}, 1300)])
def test_bench_upgrades_old_default_once_and_preserves_other_settings(tmp_path, saved, expected):
    store = Store(tmp_path)
    store.put("bench_setup", {**saved, "rfid_power": 2000, "rfid_port": "/dev/test",
                              "rfid_protocol_confirmed": True})
    bench = Bench(StationConfig(), ReplayIO(), store)
    try:
        assert bench.setup.rfid_window_ms == expected
        assert bench.setup.rfid_power == 2000 and bench.setup.rfid_protocol_confirmed
        assert bench.setup.rfid_port == "/dev/test"
        # An operator can still explicitly select 500 ms after the upgrade.
        bench.save_rfid_setup({"rfid_window_ms": 500}, "test")
    finally:
        bench.close()
    bench = Bench(StationConfig(), ReplayIO(), store)
    try:
        assert bench.setup.rfid_window_ms == 500
    finally:
        bench.close()
        store.close()


@pytest.mark.parametrize("saved", [{}, {"rfid_window_ms": 500}])
def test_timing_upgrade_does_not_freeze_unsaved_config_defaults(tmp_path, saved):
    store = Store(tmp_path)
    store.put("bench_setup", saved)
    bench = Bench(StationConfig(rfid_power=2100), ReplayIO(), store)
    try:
        assert bench.setup.rfid_power == 2100
        assert "rfid_power" not in store.get("bench_setup")
        assert "rfid_port" not in store.get("bench_setup")
    finally:
        bench.close()
    bench = Bench(StationConfig(rfid_power=2300), ReplayIO(), store)
    try:
        assert bench.setup.rfid_power == 2300
    finally:
        bench.close()
        store.close()
