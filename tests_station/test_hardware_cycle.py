import asyncio
import time
import numpy as np
import pytest
from station.schema import Commissioning, StationConfig
from station.runtime import HardwareCycle
from station.controller import Controller
from test_controller import command


class TestIO:
    __test__ = False

    def __init__(self):
        self.on = False
        self.raw = [0, 1, 1]
        self.log = []

    def stop(self):
        self.on = False
        self.raw[2] = 1
        self.log.append("stop")

    def motor(self, value, allowed=None):
        if value and allowed is not None:
            assert allowed()
        self.on = value
        self.raw[2] = 0 if value else 1
        self.log.append("motor-on" if value else "stop")

    def snapshot(self):
        return {
            "connected": True,
            "fault": None,
            "physical_permit": True,
            "km2_on": self.on,
            "di_raw": self.raw.copy(),
        }

    def blockers(self):
        return []

    def light(self, on):
        self.log.append("light")

    def inventory(self, *args):
        assert not self.on
        self.log.append("rfid")
        return [{"epc": "1D44D280281B70D75A8DF0000E114D7A"}]


class TestCamera:
    __test__ = False
    error = None

    def __init__(self, io):
        self.io = io

    def status(self):
        return {"connected": True, "frames": 20}

    def after(self, *args):
        assert not self.io.on
        self.io.log.append("capture")
        return np.zeros((80, 160, 3), dtype=np.uint8), {
            "host_received_ns": time.monotonic_ns()
        }


class TestDetector:
    def one(self, frame):
        return {"present": True}


class TestVision:
    def status(self):
        return {"busy": False, "local_assets_present": True}

    def inspect_frame(self, frame, brand, recipe):
        assert isinstance(frame, np.ndarray)
        return {"observations": {"ocr": dict(recipe.targets)}, "failures": []}


@pytest.mark.parametrize("save_pass_photos", [False, True])
@pytest.mark.parametrize("fail_vision", [False, True])
def test_stopped_single_product_cycle_and_departure(
    controller, recipe, monkeypatch, save_pass_photos, fail_vision
):
    # Synthetic field values are test fixtures only, never exported as commissioning.
    cm = Commissioning(
        settle_ms=10,
        inspection_timeout_ms=1000,
        feedback_timeout_ms=100,
        release_timeout_ms=1000,
        product_sensor=1,
        departure_sensor=2,
        sensor_clear_ms=10,
        sensor_active_raw=0,
        detector_module="fixture",
        detector_sha256="fixture",
        physical_permit_observed=True,
        power_cycle_off_verified=True,
        process_kill_off_verified=True,
        os_hang_off_verified=True,
        stop_chain_verified=True,
        single_product_verified=True,
        camera_calibrated=True,
        rfid_protocol_verified=True,
        signed_by="TEST ONLY",
        evidence_reference="TEST ONLY",
    )
    io = TestIO()
    c = Controller(
        controller.store,
        io,
        StationConfig(mode="HARDWARE", commissioning=cm, rfid_window_ms=100),
    )
    brand = c.store.brand(recipe.brand_id)
    brand["ocr_regions"] = [
        {"field": key, "box": [0, 0, 1, 1], "rotation": 0, "min_char_confidence": 0.9}
        for key in recipe.targets
    ]
    saved = c.store.save_brand(brand, brand["revision"], "TEST ONLY")
    c.store.put("save_pass_photos", save_pass_photos)
    if not save_pass_photos and not fail_vision:
        def unexpected_save(*args):
            raise AssertionError("A passing product must not encode or save a photo")

        monkeypatch.setattr("station.evidence.save_frame", unexpected_save)
    recipe.brand_revision = saved["revision"]
    recipe.channels = ["ocr", "rfid"]
    recipe.target_count = 1
    c.new_session(recipe)
    class FailVision(TestVision):
        def inspect_frame(self, frame, brand, recipe):
            return {
                "observations": {"ocr": {}},
                "failures": [{"code": "OCR_MISSING"}],
            }

    cycle = HardwareCycle(
        c, TestCamera(io), TestDetector(), FailVision() if fail_vision else TestVision()
    )
    c.runtime_blockers = cycle.blockers

    async def run():
        c.command(command(c, "start"), "test")
        assert not io.on and c.session["phase"] == "RETRY_PENDING"
        assert "motor-on" not in io.log
        await cycle.tick()
        await cycle.task
        await cycle.tick()
        photo = c.store.root / "evidence" / f'{c.last_result["id"]}.png'
        if fail_vision:
            assert c.session["count"] == 0 and c.session["phase"] == "HOLD"
            assert c.last_result["evidence"]["sha256"] and photo.is_file()
            return
        assert c.session["count"] == 1 and c.session["phase"] == "EJECTING"
        if save_pass_photos:
            assert c.last_result["evidence"]["sha256"] and photo.is_file()
        else:
            assert c.last_result["evidence"]["retained"] is False
            assert not photo.exists()
        io.raw[:2] = [1, 0]
        await cycle.tick()
        io.raw[:2] = [1, 1]
        await cycle.tick()
        await asyncio.sleep(0.02)
        await cycle.tick()
        assert c.session["phase"] == "DONE" and not io.on

    asyncio.run(run())
    assert io.log.index("capture") > io.log.index("stop")


def test_camera_stale_stops_feeding(controller, recipe):
    io = TestIO()
    c = controller
    c.io = io
    c.new_session(recipe)
    c.session["phase"] = "FEEDING"
    io.on = True
    cam = TestCamera(io)
    cam.status = lambda: {"connected": False, "frames": 20}
    cycle = HardwareCycle(c, cam, TestDetector(), TestVision())
    asyncio.run(cycle.tick())
    assert (
        c.session["phase"] == "FAULT"
        and c.session["fault"] == "CAMERA_STALE"
        and not io.on
    )


def test_rfid_disconnect_stops_before_next_inspection(controller, recipe):
    io = TestIO()
    c = controller
    c.io = io
    c.new_session(recipe)
    c.session["phase"] = "FEEDING"
    io.on = True
    prior = io.snapshot
    io.snapshot = lambda: {**prior(), "rfid_connected": False, "rfid_ready": False}
    cycle = HardwareCycle(c, TestCamera(io), TestDetector(), TestVision())
    asyncio.run(cycle.tick())
    assert (
        c.session["phase"] == "FAULT"
        and c.session["fault"] == "RFID_DISCONNECTED"
        and not io.on
    )


def test_cancelled_native_call_keeps_readiness_blocked(controller):
    import threading

    gate = threading.Event()
    started = threading.Event()
    cycle = HardwareCycle(controller, None, None, TestVision())

    def pending_library_call():
        started.set()
        gate.wait(2)

    async def run():
        task = asyncio.create_task(cycle.offload(pending_library_call))
        while not started.is_set():
            await asyncio.sleep(0.001)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert cycle.worker_busy()
        assert any("라이브러리" in reason for reason in cycle.blockers())
        gate.set()
        for _ in range(100):
            if not cycle.worker_busy():
                break
            await asyncio.sleep(0.001)
        assert not cycle.worker_busy()

    asyncio.run(run())
