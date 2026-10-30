"""Real bench routes and GPIO adapter, with synthetic signals/camera/OCR."""
import enum
import json
import sys
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from station.app import create_app
from station.sensor_ocr import SensorOcrSettings
from test_api import login


def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition did not become true")
        time.sleep(.003)


@pytest.fixture
def trial(tmp_path, monkeypatch):
    class Value(enum.Enum):
        INACTIVE = 0
        ACTIVE = 1

    class Direction(enum.Enum):
        INPUT = 0
        OUTPUT = 1

    values = {105: 1, 144: 1, 106: 1}
    writes = []

    class Request:
        def __init__(self, chip, *, config, **kwargs):
            assert chip == "/dev/gpiochip0"
            for pin, options in config.items():
                if options["direction"] == Direction.OUTPUT:
                    self.set_value(pin, options["output_value"])

        def get_values(self, pins):
            return [Value(values[pin]) for pin in pins]

        def set_value(self, pin, value):
            values[pin] = value.value
            writes.append((time.monotonic_ns(), pin, value.value))
            if pin == 51:
                values[106] = 1 - value.value

        def release(self):
            pass

    monkeypatch.setitem(sys.modules, "gpiod", SimpleNamespace(
        request_lines=Request, LineSettings=lambda **kwargs: kwargs))
    monkeypatch.setitem(sys.modules, "gpiod.line", SimpleNamespace(Value=Value, Direction=Direction))
    monkeypatch.setattr("platform.system", lambda: "Linux")
    config = tmp_path / "station.json"
    config.write_text(json.dumps({"mode": "REPLAY", "speed_line": None}))
    monkeypatch.setenv("TXRX_CONFIG", str(config))

    class Camera:
        connected = True
        seq = 1
        received = time.monotonic_ns()
        lock = threading.Lock()

        def status(self):
            with self.lock:
                return {"connected": self.connected, "frames": self.seq, "width": 40, "height": 20,
                        "profile": {"fps": 100}, "revision": 1}

        def verify_fixed_controls(self):
            pass

        def read_latest(self):
            with self.lock:
                return np.full((20, 40, 3), self.seq % 255, np.uint8), {
                    "seq": self.seq, "host_received_ns": self.received, "camera_settings_revision": 1}

        def publish(self):
            with self.lock:
                self.seq += 1
                self.received = time.monotonic_ns()

        def close(self):
            self.connected = False

    class Vision:
        text = "AB12"
        result_error = None
        load_error = None

        def __init__(self):
            self.locators = []
            self.text_finders = []
            self.release = threading.Event()
            self.release.set()
            self.entered = threading.Event()

        def load(self):
            if self.load_error:
                raise ValueError(self.load_error)

        def status(self):
            return {"busy": False, "local_assets_present": True, "loaded": True, "error": None}

        def test_auto(self, image, *, crop_images, **kwargs):
            self.locators.append(kwargs.get("locator"))
            self.text_finders.append(kwargs.get("text_finder"))
            self.entered.set()
            assert self.release.wait(3)
            reads = []
            if self.text is not None:
                crop_images.append(image[:10].copy())
                reads = [{"lines": [{"text": self.text, "confidence": .99}]}]
            return {"reads": reads, "error": self.result_error,
                    "ms_barcode": 1, "ms_ocr": 1, "ms_total": 2}

    camera, vision = Camera(), Vision()
    app = create_app(tmp_path / "data", camera=camera, vision=vision)
    closed = threading.Event()

    def publish():
        while not closed.wait(.005):
            camera.publish()

    publisher = threading.Thread(target=publish)
    publisher.start()
    with TestClient(app) as client:
        login(client)
        assert client.post("/api/bench/io/connect", json={}).status_code == 200

        def sensor(channel, raw):
            with app.state.bench.lock:
                values[(105, 144)[channel - 1]] = raw
                app.state.bench._tick()

        def start(**settings):
            settings.setdefault("sensor_gap_ms", 0)  # Sensors are stepped back to back here.
            body = SensorOcrSettings(conveyor_sync=True, **settings).model_dump()
            response = client.post("/api/bench/pipeline/start", json=body)
            assert response.status_code == 200, response.text
            return response.json()

        try:
            yield SimpleNamespace(client=client, app=app, camera=camera, vision=vision,
                                  values=values, writes=writes, sensor=sensor, start=start,
                                  state=lambda: app.state.sensor_ocr.status())
        finally:
            vision.release.set()
            client.post("/api/bench/stop", json={})
            closed.set()
            publisher.join(timeout=1)


def test_settings_reach_gpio_capture_ocr_and_di2_count(trial):
    t = trial
    t.vision.release.clear()
    settings = SensorOcrSettings(conveyor_sync=True, low_speed_ms=120, capture_delay_ms=60,
                                 capture_interval_ms=70, frame_count=2).model_dump()
    saved = t.client.put("/api/bench/pipeline/settings", json=settings)
    assert saved.status_code == 200
    assert t.app.state.store.get("sensor_ocr_settings") == settings
    result = t.start(low_speed_ms=120, capture_delay_ms=60, capture_interval_ms=70, frame_count=2)
    assert result["pins"]["speed"] == 50
    assert t.values[51] == t.values[50] == 1 and t.values[52] == 0
    t.sensor(1, 0)
    assert t.values[50] == 0 and t.values[52] == 1
    assert t.state()["count"] == 0
    t.sensor(1, 1)
    assert t.state()["count"] == 0
    wait_for(lambda: t.vision.entered.is_set())
    wait_for(lambda: t.values[50] == 1)
    wait_for(lambda: len(t.state()["jobs"][0]["frames"]) == 2)
    frames = t.state()["jobs"][0]["frames"]
    assert frames[0]["after_trigger_ms"] >= 60
    assert frames[1]["after_trigger_ms"] >= 130
    assert frames[0]["seq"] < frames[1]["seq"]
    assert t.state()["jobs"][0]["missed_frames"] == 0
    t.sensor(2, 0)
    t.sensor(2, 0)
    assert t.values[52] == 0 and t.values[51] == 1
    assert t.state()["count"] == 1 and t.state()["passed"] == 0
    t.vision.release.set()
    wait_for(lambda: t.state()["passed"] == 1)
    job = t.state()["jobs"][0]
    assert job["matched_text"] == "AB12" and job["counted"]
    assert job["frames"][0]["result"]["reads"][0]["lines"][0]["text"] == "AB12"
    assert t.vision.locators == ["yolo26"]
    image = t.client.get(f'/api/bench/pipeline/frames/{job["id"]}/{frames[0]["seq"]}')
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert t.client.get("/api/history").json()["inspections"] == []


@pytest.mark.parametrize("cause", ["stop", "camera", "heartbeat", "manual_speed"])
def test_interruption_cancels_speed_timer_and_all_outputs(trial, cause):
    t = trial
    t.start(low_speed_ms=100, capture_delay_ms=0, frame_count=1)
    t.sensor(1, 0)
    assert t.values[50] == 0 and t.values[52] == 1
    if cause == "stop":
        t.client.post("/api/bench/stop", json={})
    elif cause == "manual_speed":
        assert t.client.post("/api/bench/speed/off", json={}).status_code == 200
    elif cause == "camera":
        t.camera.connected = False
    else:
        with t.app.state.bench.lock:
            t.app.state.bench.runs["motor"]["last_heartbeat"] -= 2
            t.app.state.bench._tick()
    wait_for(lambda: not t.state()["active"])
    time.sleep(.12)
    assert all(t.values[pin] == 0 for pin in (50, 51, 52))
    assert t.state()["count"] == 0


def test_di2_before_last_capture_stops_and_preserves_reason(trial):
    t = trial
    t.start(capture_delay_ms=500, frame_count=1)
    t.sensor(1, 0)
    t.sensor(2, 0)
    assert not t.state()["active"] and t.state()["count"] == 1
    assert "DI2가 촬영 예정 시각보다 먼저" in t.state()["error"]
    assert all(t.values[pin] == 0 for pin in (50, 51, 52))


def test_heartbeat_stop_preserves_cause_after_workers_exit_and_repeated_stop(trial):
    t = trial
    t.start(capture_delay_ms=500, frame_count=1)
    t.sensor(1, 0)
    with t.app.state.bench.lock:
        t.app.state.bench.runs["motor"]["last_heartbeat"] -= 2
        t.app.state.bench._tick()
    wait_for(lambda: not t.state()["busy"])
    result = t.client.get("/api/bench/pipeline").json()
    assert result["jobs"][0]["state"] == "cancelled"
    assert result["stop_reason"] == "화면 연결 끊김"
    assert not result["active"] and not result["busy"]
    assert all(t.values[pin] == 0 for pin in (50, 51, 52))
    t.client.post("/api/bench/stop", json={})
    assert t.state()["stop_reason"] == "화면 연결 끊김"
    assert t.app.state.bench.cooldown_ms("motor") > 4000


@pytest.mark.parametrize("cause", ["extra_di1", "di2_without_di1"])
def test_unmatched_sensor_sequence_stops_without_adding_counts(trial, cause):
    t = trial
    t.start(capture_delay_ms=0, frame_count=1)
    if cause == "extra_di1":
        t.sensor(1, 0)
        t.sensor(1, 1)
        t.sensor(1, 0)
    else:
        t.sensor(2, 0)
    assert not t.state()["active"] and t.state()["count"] == 0
    assert all(t.values[pin] == 0 for pin in (50, 51, 52))


@pytest.mark.parametrize("text,result_error", [
    ("wrong", None), ("", None), (None, "바코드 영역을 찾지 못했습니다."),
])
@pytest.mark.parametrize("frame_count", [1, 3])
def test_ocr_miss_keeps_motor_running_and_accepts_next_product(trial, text, result_error, frame_count):
    t = trial
    t.vision.text, t.vision.result_error = text, result_error
    t.start(low_speed_ms=120, capture_delay_ms=0, capture_interval_ms=20,
            frame_count=frame_count, pattern="[0-9]{4}")
    run_id = t.app.state.bench.runs["motor"]["id"]
    start_writes = len(t.writes)
    t.sensor(1, 0)
    assert t.values[50] == 0 and t.values[52] == 1
    wait_for(lambda: t.state()["failed"] == 1)
    wait_for(lambda: t.values[50] == 1 or not t.state()["active"])
    assert t.state()["active"] and t.state()["error"] is None
    assert t.values[51] == t.values[50] == t.values[52] == 1
    job = t.state()["jobs"][0]
    assert job["state"] == "failed" and len(job["frames"]) == frame_count
    for frame in job["frames"]:
        assert frame["state"] == "no_match" and frame["image_available"]
        assert frame["result"]["error"] == result_error
        if text is not None:
            assert frame["result"]["reads"][0]["lines"][0]["text"] == text
        else:
            assert frame["result"]["reads"] == []
    t.sensor(1, 1)
    t.sensor(2, 0)
    assert t.state()["count"] == 1 and t.values[52] == 0
    t.sensor(2, 1)

    t.vision.text, t.vision.result_error = "1234", None
    t.sensor(1, 0)
    assert t.values[50] == 0 and t.values[52] == 1
    wait_for(lambda: t.state()["passed"] == 1 and not t.state()["jobs"][0]["collecting"])
    wait_for(lambda: t.values[50] == 1)
    t.sensor(1, 1)
    t.sensor(2, 0)
    state = t.state()
    assert state["active"] and state["error"] is None
    assert state["detected"] == state["count"] == 2
    assert state["passed"] == state["failed"] == 1
    assert state["jobs"][0]["matched_text"] == "1234"
    assert all(item["counted"] for item in state["jobs"])
    assert t.values[51] == t.values[50] == 1 and t.values[52] == 0
    assert t.app.state.bench.runs["motor"]["id"] == run_id
    assert not any(pin == 51 and raw == 0 for _, pin, raw in t.writes[start_writes:])
    assert t.client.get("/api/history").json()["inspections"] == []


def test_capture_timeout_still_stops_conveyor(trial):
    t = trial
    t.start(capture_delay_ms=1000, frame_count=1)
    t.sensor(1, 0)
    with t.app.state.sensor_ocr.lock:
        t.app.state.sensor_ocr.jobs[0]["trigger_ns"] -= 4_000_000_000
    wait_for(lambda: not t.state()["active"])
    assert t.state()["error"] == "새 프레임 수집 시간 초과"
    assert all(t.values[pin] == 0 for pin in (50, 51, 52))


def test_ocr_runtime_exception_still_stops_conveyor(trial, monkeypatch):
    t = trial

    def broken_ocr(*args, **kwargs):
        raise RuntimeError("OCR 처리 오류")

    monkeypatch.setattr(t.vision, "test_auto", broken_ocr)
    t.start(capture_delay_ms=0, frame_count=1)
    t.sensor(1, 0)
    wait_for(lambda: not t.state()["active"])
    assert t.state()["error"] == "OCR 처리 오류"
    assert all(t.values[pin] == 0 for pin in (50, 51, 52))


def test_model_load_failure_never_enables_outputs(trial):
    t = trial
    t.vision.load_error = "모델 파일 없음"
    response = t.client.post("/api/bench/pipeline/start", json={"conveyor_sync": True})
    assert response.status_code == 422
    assert "모델 파일 없음" in response.text
    assert not t.writes and not t.state()["active"]


def test_48mp_preflight_rejects_camera_before_motor_starts(trial):
    from station.vision import Vision
    trial.vision.prepare_capture = Vision().prepare_capture
    response = trial.client.post("/api/bench/pipeline/start", json={"conveyor_sync": True})
    assert response.status_code == 422 and "48MP" in response.text
    assert not trial.writes and not trial.state()["active"]


def test_trial_restart_waits_five_seconds_without_delaying_stop(trial):
    t = trial
    t.start(frame_count=1)
    assert t.client.post("/api/bench/motor/off", json={}).status_code == 200
    assert t.values[51] == 0
    wait_for(lambda: not t.state()["busy"])
    assert t.state()["stop_reason"] == "모터 끄기로 공정 시험 중지"
    b = t.app.state.bench
    deadline = b.next_output_at["motor"]
    assert 4500 < b.status()["cooldown_ms"]["motor"] <= 5000
    before = sum(pin == 51 and raw == 1 for _, pin, raw in t.writes)
    response = t.client.post("/api/bench/pipeline/start", json=SensorOcrSettings(conveyor_sync=True).model_dump())
    assert response.status_code == 409 and "5초" in response.text
    assert sum(pin == 51 and raw == 1 for _, pin, raw in t.writes) == before
    assert b.next_output_at["motor"] == deadline
    with b.lock:
        b.next_output_at["motor"] = time.monotonic() - .001
    t.start(frame_count=1)
    assert t.values[51] == 1
    assert t.state()["stop_reason"] is None


def test_cancelled_ocr_does_not_leave_frame_label_reading(trial):
    t = trial
    t.vision.release.clear()
    t.start(capture_delay_ms=0, frame_count=1)
    t.sensor(1, 0)
    wait_for(t.vision.entered.is_set)
    assert t.client.post("/api/bench/pipeline/stop", json={}).status_code == 200
    result = t.state()
    assert result["busy"] and not result["active"]
    assert result["stop_reason"] == "공정 시험 중지"
    assert result["jobs"][0]["frames"][0]["state"] == "cancelled"
    assert all(t.values[pin] == 0 for pin in (50, 51, 52))
    t.vision.release.set()
    wait_for(lambda: not t.state()["busy"])
    assert t.state()["jobs"][0]["frames"][0]["result"] is None


def test_sensor_images_preserve_full_resolution_and_pixels(trial):
    import cv2
    t = trial
    # Fine detail above the previous 1280-pixel limit catches both resizing and JPEG loss.
    original = np.random.default_rng(12).integers(0, 256, (1100, 1920, 3), dtype=np.uint8)
    crop = original[400:500, 100:1700].copy()
    with t.app.state.sensor_ocr.lock:
        t.app.state.sensor_ocr.jobs.append({"id": "image-check", "frames": [
            {"seq": 42, "image": original, "crops": [crop]}]})
    try:
        url = "/api/bench/pipeline/frames/image-check/42"
        for query, expected in (("", original), ("?crop=0", crop), ("?original=true", original)):
            response = t.client.get(url + query)
            assert response.status_code == 200 and response.headers["content-type"] == "image/png"
            decoded = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
            np.testing.assert_array_equal(decoded, expected)
            assert ("attachment" in response.headers.get("content-disposition", "")) == (query == "?original=true")
        assert t.client.get(url + "?crop=99").status_code == 410
    finally:
        with t.app.state.sensor_ocr.lock:
            t.app.state.sensor_ocr.jobs.clear()


def test_sensor_trial_can_compare_existing_locator(trial):
    trial.start(frame_count=1, capture_delay_ms=0, locator="opencv")
    trial.sensor(1, 0)
    wait_for(lambda: trial.state()["passed"] == 1)
    assert trial.vision.locators == ["opencv"]
    assert trial.app.state.store.get("sensor_ocr_settings")["locator"] == "opencv"


def test_sensor_trial_passes_the_chosen_text_finder(trial):
    trial.start(frame_count=1, capture_delay_ms=0, text_finder="lines")
    trial.sensor(1, 0)
    wait_for(lambda: trial.state()["passed"] == 1)
    assert trial.vision.text_finders == ["lines"]
    assert trial.app.state.store.get("sensor_ocr_settings")["text_finder"] == "lines"


def test_sensor_trial_stops_before_capture_when_the_text_detector_cannot_load(trial, monkeypatch):
    import tagreader.text_detector as detector

    def broken():
        raise RuntimeError("글자 검출 모델 파일이 없습니다.")
    monkeypatch.setattr(detector, "get_detector", broken)
    body = SensorOcrSettings(conveyor_sync=True, frame_count=1, text_finder="detector").model_dump()
    response = trial.client.post("/api/bench/pipeline/start", json=body)
    assert response.status_code == 409 and "글자 검출 모델" in response.text
    assert not trial.state()["active"]


@pytest.mark.parametrize('frame_count', [1, 2])
def test_di2_during_copy_accepts_frame_received_before_departure(trial, monkeypatch, frame_count):
    t = trial
    entered, release = threading.Event(), threading.Event()
    original = t.camera.read_latest
    def copying():
        image, metadata = original()
        job = t.app.state.sensor_ocr.jobs[0]
        if metadata['host_received_ns'] >= job['trigger_ns'] and len(job['frames']) == frame_count - 1:
            entered.set()
            assert release.wait(2)
        return image, metadata
    monkeypatch.setattr(t.camera, 'read_latest', copying)
    try:
        t.start(capture_delay_ms=0, capture_interval_ms=0, frame_count=frame_count)
        t.sensor(1, 0)
        assert entered.wait(1)
        t.sensor(2, 0)
        assert t.values[52] == 0  # DI2 always switches the LED off immediately.
        assert t.state()['error'] is None
        assert t.state()['active']
        release.set()
        wait_for(lambda: len(t.state()['jobs'][0]['frames']) == frame_count)
        job = t.state()['jobs'][0]
        assert all(job['trigger_ns'] <= f['received_ns'] <= job['released_ns'] for f in job['frames'])
        assert job['counted'] and not job['collecting']
    finally:
        release.set()


def test_frame_received_after_di2_is_rejected_even_if_copy_started_earlier(trial, monkeypatch):
    t = trial
    entered, release = threading.Event(), threading.Event()
    original = t.camera.read_latest
    def waiting_for_frame():
        entered.set()
        assert release.wait(2)
        # The USB read supplied a frame only after the product had departed.
        t.camera.publish()
        return original()
    monkeypatch.setattr(t.camera, 'read_latest', waiting_for_frame)
    try:
        t.start(capture_delay_ms=0, frame_count=1)
        t.sensor(1, 0)
        assert entered.wait(1)
        t.sensor(2, 0)
        release.set()
        wait_for(lambda: not t.state()['active'])
        assert 'DI2 도착 전 촬영 프레임' in t.state()['error']
        assert not t.state()['jobs'][0]['frames']
        assert all(t.values[pin] == 0 for pin in (50, 51, 52))
    finally:
        release.set()


def test_manual_stop_during_frame_copy_cannot_accept_late_result(trial, monkeypatch):
    t = trial
    entered, release = threading.Event(), threading.Event()
    original = t.camera.read_latest
    def copying():
        result = original()
        entered.set()
        assert release.wait(2)
        return result
    monkeypatch.setattr(t.camera, 'read_latest', copying)
    try:
        t.start(capture_delay_ms=0, frame_count=1)
        t.sensor(1, 0)
        assert entered.wait(1)
        assert t.client.post('/api/bench/stop', json={}).status_code == 200
        assert all(t.values[pin] == 0 for pin in (50, 51, 52))
        release.set()
        wait_for(lambda: not t.state()['busy'])
        assert not t.state()['jobs'][0]['frames']
    finally:
        release.set()


def test_trial_opens_inputs_and_turns_on_saved_camera_itself(trial):
    t = trial
    assert t.client.post("/api/bench/io/disconnect", json={}).status_code == 200
    camera = t.camera
    camera.connected = False
    camera.saved = {"device": "/dev/video0"}
    camera.connect = lambda: setattr(camera, "connected", True)
    t.start(frame_count=1)
    assert t.app.state.bench.io is not None and camera.connected
    assert t.values[51] == 1 and t.state()["active"]


def test_trial_takes_over_manual_led_and_keeps_running_motor(trial):
    t = trial
    def manual(target):
        state = t.client.get("/api/bench").json()
        response = t.client.post("/api/bench/output", json={
            "target": target, "seconds": None, "generation": state["generation"],
            "request_id": f"manual-{target}-request", "issued_at": time.time()})
        assert response.status_code == 200, response.text
    manual("motor")
    with t.app.state.bench.lock:
        t.app.state.bench.next_output_at["led"] = time.monotonic() - .001
    manual("led")
    motor = t.app.state.bench.runs["motor"]["id"]
    t.start(frame_count=1)
    runs = t.app.state.bench.runs
    assert set(runs) == {"motor"} and runs["motor"]["id"] == motor
    # The sensor sequence now owns the LED: off until DI1.
    assert t.values[52] == 0 and t.state()["active"]


def test_process_test_says_at_once_that_the_models_are_still_loading(trial):
    trial.vision.loading = lambda: True
    body = SensorOcrSettings(conveyor_sync=True, frame_count=1).model_dump()
    response = trial.client.post("/api/bench/pipeline/start", json=body)
    assert response.status_code == 409 and "불러오는 중" in response.text
    assert not trial.state()["active"] and not trial.app.state.bench.runs


def test_conveyor_trial_takes_a_short_sensor_flicker_as_the_same_product(trial):
    trial.start(frame_count=1, capture_delay_ms=0, sensor_gap_ms=5000)
    for raw in (0, 1, 0):
        trial.sensor(1, raw)
    assert trial.state()["detected"] == 1 and trial.state()["active"]
    trial.sensor(1, 1)
    trial.sensor(2, 0)
    wait_for(lambda: trial.state()["count"] == 1)
    assert trial.state()["error"] is None
