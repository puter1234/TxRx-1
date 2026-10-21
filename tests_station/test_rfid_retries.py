import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from station.schema import FlowSettings, Recipe, WorkPreset
from station.rfid import InventoryCancelled
from test_moving_flow import rig
from test_moving_api import line, prepare, issue, wait_state


EPC = "1D44D280281B70D75A8DF0000E114D7A"


@pytest.mark.parametrize("success_at", [1, 2, 3, None])
def test_product_retries_at_selected_interval_and_stops_at_first_read(controller, recipe, monkeypatch, success_at):
    c, io, _, cycle, clock = rig(controller, monkeypatch, recipe, rfid_attempts=3, rfid_interval_ms=50)
    calls = []

    async def sleep(delay):
        clock[0] += delay
        await asyncio.sleep(0)

    monkeypatch.setattr("station.flow.asyncio", SimpleNamespace(
        sleep=sleep, create_task=asyncio.create_task, gather=asyncio.gather, CancelledError=asyncio.CancelledError))

    def read_once(timeout, cancel):
        calls.append((clock[0], timeout))
        return [{"epc": EPC}] if len(calls) == success_at else []

    io.inventory_once = read_once
    io.inventory = lambda *args: pytest.fail("Production must not call the 100-round bench inventory")

    async def run():
        await cycle.tick()
        io.raw[0] = 0
        await cycle.tick()
        p = cycle.pending
        await cycle.read_rfid(p)
        expected = success_at or 3
        assert len(calls) == expected
        assert [at for at, _ in calls] == pytest.approx([100.1 + .05 * i for i in range(expected)])
        assert all(timeout == 50 for _, timeout in calls)
        assert p["inspection"]["rfid_attempts"] == expected and p["rfid_done"]
        if success_at:
            assert p["observations"]["rfid"] == recipe.targets and io.on
        else:
            assert p["failures"] == [{"code": "RFID_MISSING", "detail": ""}]
            assert not io.on
        io.raw[1] = 0
        await cycle.tick()
        assert c.session["count"] == (1 if success_at else 0)
        assert c.last_result["status"] == ("PASS" if success_at else "FAIL")
        assert len(calls) == expected

    asyncio.run(run())


@pytest.mark.parametrize("multiple", [False, True])
def test_first_wrong_or_multiple_tag_result_is_not_retried(controller, recipe, monkeypatch, multiple):
    recipe.targets["size"] = "100"
    c, io, _, cycle, clock = rig(controller, monkeypatch, recipe, rfid_attempts=5)
    calls = []

    def read_once(*args):
        calls.append(1)
        return [{"epc": EPC}] + ([{"epc": "AABB"}] if multiple else [])

    io.inventory_once = read_once

    async def run():
        await cycle.tick()
        io.raw[0] = 0
        await cycle.tick()
        clock[0] += .1
        await cycle.read_rfid(cycle.pending)
        assert len(calls) == 1 and not io.on
        assert cycle.pending["failures"][0]["code"] == ("MULTIPLE_RFID_TAGS" if multiple else "TARGET_MISMATCH")

    asyncio.run(run())


@pytest.mark.parametrize("settings", [
    {"rfid_attempts": 0}, {"rfid_attempts": 101}, {"rfid_interval_ms": 19},
    {"rfid_interval_ms": 10001}, {"rfid_attempts": 1.5},
])
def test_invalid_retry_settings_are_rejected(settings):
    with pytest.raises(ValueError):
        FlowSettings(**settings)


def test_rfid_schedule_must_fit_completion_timeout_only_when_rfid_enabled():
    flow = FlowSettings(rfid_attempts=4, rfid_interval_ms=100, result_timeout_ms=500)
    with pytest.raises(ValueError, match="RFID 읽기 종료"):
        WorkPreset(id="rfid", name="RFID", kind="condition", brand_id="hazzys", channels=["rfid"], flow=flow)
    with pytest.raises(ValueError, match="RFID 읽기 종료"):
        Recipe(brand_id="hazzys", brand_revision=1, channels=["rfid"], targets={"size": "095"}, flow=flow)
    assert WorkPreset(id="simple", name="단순 계수", flow=flow).flow == flow


@pytest.mark.parametrize("success", [False, True])
def test_camera_recovery_keeps_product_attempt_budget_and_reader_ready(line, monkeypatch, success):
    calls, started = [], threading.Event()

    def read_once(timeout, cancel):
        calls.append(time.monotonic())
        if len(calls) == 1:
            started.set()
            if not cancel.wait(2):
                raise TimeoutError("test did not interrupt the first read")
            raise InventoryCancelled("test camera interruption")
        return [{"epc": EPC}] if success else []

    monkeypatch.setattr(line.io.reader, "inventory_once", read_once)
    prepare(line, ("ocr", "rfid"), rfid_attempts=2, rfid_interval_ms=50, reconnect_interval_ms=100)
    issue(line, "start")
    line.gpio.sensor(1, 0)
    assert started.wait(1)
    line.camera.connected = False
    stopped = wait_state(line, lambda s: s["session"]["phase"] == "CAMERA_WAIT")
    product = stopped["session"]["active_product"]
    assert len(calls) == 1 and not line.io.snapshot()["motor_requested"]
    with line.io.lock:
        line.io.motor_ready_at = time.monotonic() - 1
    if success:
        resumed = wait_state(line, lambda s: s["session"]["phase"] == "FEEDING" and len(calls) == 2)
        assert resumed["session"]["active_product"] == product
        line.gpio.sensor(2, 0)
        done = wait_state(line, lambda s: s["session"]["count"] == 1)
        assert done["last_result"]["status"] == "PASS"
    else:
        done = wait_state(line, lambda s: s["session"]["phase"] == "HOLD")
        assert done["session"]["fault"] == "RFID_MISSING" and done["session"]["count"] == 0
    assert line.io.reader.initialized and len(calls) == 2
    assert done["last_result"]["rfid_attempts"] == 2
    assert done["last_result"]["product_id"] == product


def test_manual_stop_during_retry_gap_prevents_more_reads(line, monkeypatch):
    calls = []

    def miss(*args):
        calls.append(time.monotonic())
        return []

    monkeypatch.setattr(line.io.reader, "inventory_once", miss)
    prepare(line, ("rfid",), rfid_attempts=3, rfid_interval_ms=200)
    issue(line, "start")
    line.gpio.sensor(1, 0)
    wait_state(line, lambda s: len(calls) == 1)
    issue(line, "stop")
    time.sleep(.25)
    stopped = wait_state(line, lambda s: s["session"]["phase"] == "PAUSED" and not s["busy"])
    assert len(calls) == 1 and stopped["session"]["count"] == 0
    assert not line.io.snapshot()["motor_requested"]
