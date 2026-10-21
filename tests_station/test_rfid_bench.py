"""RFID bench API with the real GPIO adapter and serial frame decoder."""

import pytest

from station.rfid import frame
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
    assert port.writes == [frame(0x27, b"\x22\x00\x64"), frame(0x28)] * 2
