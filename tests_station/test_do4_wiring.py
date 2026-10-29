"""The documented J4012 DO4 works without entering a GPIO number."""
import enum
import json
import sys
import time
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from station.app import create_app
from station.schema import StationConfig


@pytest.mark.parametrize("legacy", [{}, {"speed_line": None}])
def test_existing_j4012_configs_resolve_do4(legacy):
    config = StationConfig.model_validate_json(json.dumps(legacy))
    assert config.speed_line == 50
    assert config.do_lines == (51, 52)
    assert config.di_lines == (105, 144, 106)


def test_custom_wiring_is_not_reassigned_to_j4012_do4():
    assert StationConfig(speed_line=108).speed_line == 108
    assert StationConfig(gpio_chip="/dev/gpiochip1").speed_line is None
    with pytest.raises(ValueError, match="중복"):
        StationConfig(permit_line=50)


def test_speed_buttons_drive_do4_without_entering_a_pin(tmp_path, monkeypatch):
    class Value(enum.Enum):
        INACTIVE = 0
        ACTIVE = 1

    class Direction(enum.Enum):
        INPUT = 1
        OUTPUT = 2

    values = {105: Value.ACTIVE, 144: Value.ACTIVE, 106: Value.ACTIVE}
    writes = []

    class Request:
        def __init__(self, chip, *, config, **kwargs):
            assert chip == "/dev/gpiochip0"
            for pin, settings in config.items():
                if settings["direction"] == Direction.OUTPUT:
                    self.set_value(pin, settings["output_value"])

        def set_value(self, pin, value):
            values[pin] = value
            writes.append((pin, value.value))

        def get_values(self, pins):
            return [values[pin] for pin in pins]

        def release(self):
            pass

    monkeypatch.setitem(sys.modules, "gpiod", SimpleNamespace(
        LineSettings=lambda **kwargs: kwargs, request_lines=Request))
    monkeypatch.setitem(sys.modules, "gpiod.line", SimpleNamespace(
        Direction=Direction, Value=Value))
    monkeypatch.setattr("platform.system", lambda: "Linux")
    config_path = tmp_path / "station.json"
    config_path.write_text('{"mode":"REPLAY","speed_line":null}', encoding="utf-8")
    monkeypatch.setenv("TXRX_CONFIG", str(config_path))
    app = create_app(tmp_path / "data")
    with TestClient(app) as client:
        assert client.post("/api/auth/setup", json={"password": "test-password"}).status_code == 200
        state = client.get("/api/bench").json()
        assert state["pins"]["speed"] == 50
        # Low must acquire DO4 in OFF state even before a high command.
        response = client.post("/api/bench/speed/off", json={})
        assert response.status_code == 200, response.text
        assert writes == [(50, 0)]
        app.state.bench.next_output_at["speed"] = 0
        state = client.get("/api/bench").json()
        response = client.post("/api/bench/output", json={
            "target": "speed", "seconds": None, "generation": state["generation"],
            "request_id": str(uuid.uuid4()), "issued_at": time.time(),
        })
        assert response.status_code == 200, response.text
        assert response.json()["io"]["speed_requested"] is True
        app.state.bench.next_output_at["speed"] = 0
        response = client.post("/api/bench/speed/off", json={})
        assert response.status_code == 200, response.text
        assert response.json()["io"]["speed_requested"] is False
        assert writes == [(50, 0), (50, 1), (50, 0)]
        assert not ({51, 52} & {pin for pin, _ in writes})
