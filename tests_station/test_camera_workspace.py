"""Camera commissioning contracts, without real USB/GPIO or private model files."""
import copy

import pytest

from tests_station.test_bench import FakeBackend, FakeStream, pulse, rig


class AutomaticBackend(FakeBackend):
    def __init__(self):
        super().__init__()
        self.profile.controls.update(focus_auto=1, white_balance_temperature_auto=1,
                                     white_balance_temperature=4500)

    def apply(self, profile):
        # Driver state is independent from the immutable caller's request.
        return super().apply(profile.model_copy(deep=True))

    def inspect(self, device):
        info = super().inspect(device)
        for name in ("focus_auto", "white_balance_temperature_auto", "white_balance_temperature"):
            info["controls"].append({"name": name, "value": self.profile.controls[name],
                                     "type": "bool" if name.endswith("auto") else "int",
                                     "flags": "", "menu": {}})
        return info


def apply(client, app, controls=None, save=True):
    profile = app.state.camera.backend.profile.model_dump()
    if controls is not None:
        profile["controls"] = controls
    result = client.post("/api/bench/camera/apply", json={
        "profile": profile, "save": save, "expected_revision": app.state.camera.revision,
    })
    assert result.status_code == 200, result.text
    return result.json()


def test_preview_capture_and_reconnect_share_fixed_settings(rig):
    c, app = rig
    camera = app.state.camera
    camera.backend = AutomaticBackend()
    result = apply(c, app, {"focus_auto": 1, "white_balance_temperature_auto": 1})
    controls = result["profile"]["controls"]
    assert controls == {"focus_auto": 0, "focus_absolute": 10,
                        "white_balance_temperature_auto": 0, "white_balance_temperature": 4500}
    preview = c.get("/api/camera/frame")
    assert preview.headers["cache-control"] == "no-store"
    assert preview.headers["x-camera-frame"] == "101"
    assert preview.headers["x-camera-revision"] == str(result["revision"])
    capture = c.post("/api/bench/camera/capture", json={}).json()
    assert capture["metadata"]["camera_profile"]["controls"] == controls
    assert capture["metadata"]["camera_settings_revision"] == result["revision"]
    assert c.get(capture["url"]).content.startswith(b"\x89PNG")
    c.post("/api/bench/camera/disconnect", json={})
    camera.backend.profile.controls.update(focus_auto=1, focus_absolute=70,
                                           white_balance_temperature_auto=1, white_balance_temperature=6000)
    reconnected = c.post("/api/bench/camera/connect", json={})
    assert reconnected.status_code == 200, reconnected.text
    assert reconnected.json()["profile"]["controls"] == controls


def test_capture_rejects_actual_control_drift_without_discarding_saved_profile(rig):
    c, app = rig
    app.state.camera.backend = AutomaticBackend()
    saved = copy.deepcopy(apply(c, app)["saved_profile"])
    app.state.camera.backend.profile.controls["focus_auto"] = 1
    for route in ("capture", "batch"):
        result = c.post("/api/bench/camera/" + route, json={"count": 2} if route == "batch" else {})
        assert result.status_code == 409, result.text
        assert "화이트밸런스" in result.json()["detail"]
    assert app.state.store.get("usb_camera_profile") == saved
    assert c.get("/api/bench/captures/latest").json() is None
    assert not app.state.bench.native_busy


def test_driver_reset_after_open_is_not_reported_as_success(rig):
    c, app = rig
    camera = app.state.camera
    camera.backend = AutomaticBackend()

    def reset_controls(profile):
        stream = FakeStream(profile)
        camera.backend.profile.controls["focus_auto"] = 1
        return stream

    camera.stream_factory = reset_controls
    result = c.post("/api/bench/camera/apply", json={
        "profile": camera.backend.profile.model_dump(), "save": True, "expected_revision": 0,
    })
    assert result.status_code == 422
    assert camera.saved is None
    assert not camera.status()["connected"]


def test_ready_job_can_adjust_camera_without_ending_or_unlocking_other_settings(rig):
    c, app = rig
    apply(c, app)
    job = c.post("/api/sessions", json={"kind": "simple", "brand_id": "__simple__",
                                       "brand_revision": 1, "targets": {}, "channels": []})
    assert job.status_code == 200, job.text
    ident = job.json()["session"]["id"]
    inspect = c.post("/api/bench/camera/inspect", json={"device": "/dev/video0"})
    assert inspect.status_code == 200
    assert inspect.json()["revision"] == 1
    apply(c, app, {"focus_absolute": 42})
    assert c.post("/api/bench/camera/capture", json={}).status_code == 200
    assert c.post("/api/bench/io/connect", json={}).status_code == 409
    session = c.get("/api/status").json()["session"]
    assert session["id"] == ident and session["phase"] == "READY"
    assert session["count"] == 0


@pytest.mark.parametrize("phase, product", [("FEEDING", None), ("HOLD", "product"),
                                            ("PAUSED", None), ("FAULT", None), ("READY", "product")])
def test_camera_adjustment_never_bypasses_an_active_or_held_product(rig, phase, product):
    c, app = rig
    c.post("/api/sessions", json={"kind": "simple", "brand_id": "__simple__",
                                  "brand_revision": 1, "targets": {}, "channels": []})
    app.state.controller.session.update(phase=phase, active_product=product)
    assert c.post("/api/bench/camera/inspect", json={"device": "/dev/video0"}).status_code == 409
    assert c.post("/api/bench/close", json={}).status_code == 409


def test_photo_and_ocr_can_run_with_motor_and_led_but_settings_cannot(rig):
    c, app = rig
    apply(c, app)
    c.post("/api/bench/io/connect", json={})
    assert pulse(c, "motor", None).status_code == 200
    assert pulse(c, "led", None).status_code == 200
    before = {key: run["id"] for key, run in app.state.bench.runs.items()}
    assert c.post("/api/bench/camera/capture", json={}).status_code == 200
    app.state.vision.test_auto = lambda frame, **kwargs: {"ok": True, "reads": []}
    assert c.post("/api/bench/ocr/read", json={}).status_code == 200
    assert c.post("/api/bench/camera/inspect", json={"device": "/dev/video0"}).status_code == 409
    assert c.post("/api/bench/camera/disconnect", json={}).status_code == 409
    assert {key: run["id"] for key, run in app.state.bench.runs.items()} == before
    assert app.state.bench.io.motor and app.state.bench.io.led
    assert c.get("/api/history").json()["inspections"] == []


def test_batch_interval_rejects_invalid_and_overlong_requests(rig):
    c, _ = rig
    for body in ({"count": 2, "interval_ms": -1}, {"count": 31, "interval_ms": 10000},
                 {"count": 3, "interval_ms": 0.5}):
        assert c.post("/api/bench/camera/batch", json=body).status_code == 422


def test_leaving_workspace_releases_inputs_so_next_production_job_can_be_created(rig):
    c, app = rig
    c.post("/api/bench/io/connect", json={})
    assert pulse(c, "motor", None).status_code == 200
    assert pulse(c, "led", None).status_code == 200
    gpio = app.state.bench.io
    result = c.post("/api/bench/close", json={})
    assert result.status_code == 200, result.text
    assert not gpio.motor and not gpio.led
    assert app.state.bench.io is None and not app.state.bench.busy()
    job = c.post("/api/sessions", json={"kind": "simple", "brand_id": "__simple__",
                                       "brand_revision": 1, "targets": {}, "channels": []})
    assert job.status_code == 200, job.text
    assert job.json()["session"]["phase"] == "READY"
    assert c.post("/api/bench/close", json={}).status_code == 200
    assert c.get("/api/status").json()["session"]["phase"] == "READY"


def test_saving_same_profile_and_connecting_keeps_live_stream(rig):
    client, app = rig
    apply(client, app)
    camera = app.state.camera
    stream = camera.stream
    apply(client, app, save=True)
    assert camera.stream is stream and not stream.closed
    assert client.post('/api/bench/camera/connect', json={}).status_code == 200
    assert camera.stream is stream and not stream.closed


def test_manual_controls_do_not_reopen_stream_and_rejection_restores_controls(rig):
    client, app = rig
    camera = app.state.camera
    class LiveBackend(AutomaticBackend):
        def apply_controls(self, profile):
            return self.apply(profile)
    camera.backend = LiveBackend()
    apply(client, app)
    stream = camera.stream
    apply(client, app, {"focus_absolute": 25})
    assert camera.stream is stream and not stream.closed
    assert camera.profile['controls']['focus_absolute'] == 25
    profile = camera.backend.profile.model_dump()
    profile['controls']['focus_absolute'] = 77
    result = client.post('/api/bench/camera/apply', json={"profile": profile, "save": True, "expected_revision": camera.revision})
    assert result.status_code == 422, result.text
    assert camera.stream is stream and not stream.closed
    assert camera.backend.profile.controls['focus_absolute'] == 25
    assert camera.saved['controls']['focus_absolute'] == 25


def test_resolution_change_still_restarts_capture(rig):
    client, app = rig
    apply(client, app)
    camera = app.state.camera
    previous = camera.stream
    profile = camera.backend.profile.model_dump()
    profile.update(width=8000, height=6000, fps=3)
    result = client.post('/api/bench/camera/apply', json={"profile": profile, "save": True, "expected_revision": camera.revision})
    assert result.status_code == 200, result.text
    assert previous.closed and camera.stream is not previous


def test_v4l2_control_changes_never_reset_video_format():
    from station.usb_camera import V4L2, CameraProfile
    class Backend(V4L2):
        value = 10
        commands = []
        def inspect(self, device):
            return {"modes": [{"width":640,"height":480,"pixel_format":"YUYV","fps":30}],
                    "current": {"width":640,"height":480,"pixel_format":"YUYV","fps":30},
                    "controls": [{"name":"focus_absolute","value":self.value}]}
        def run(self, *args):
            self.commands.append(args)
            if '--list-ctrls-menus' in args:
                return f'focus_absolute 0x009a090a (int) : min=0 max=100 step=1 value={self.value}'
            if args[-1].startswith('--set-ctrl=focus_absolute='):
                self.value = int(args[-1].split('=')[-1])
            return ''
    backend = Backend()
    backend.apply_controls(CameraProfile(device='/dev/video0',width=640,height=480,fps=30,controls={'focus_absolute':25}))
    assert backend.value == 25
    assert not any('set-fmt' in arg or 'set-parm' in arg for command in backend.commands for arg in command)


def test_stale_frame_status_explains_loss_and_recovers_without_closing_process():
    import queue
    import time
    from types import SimpleNamespace
    from station.usb_camera import UVCStream, CameraProfile
    stream = UVCStream.__new__(UVCStream)
    stream.errors = queue.Queue()
    stream.error = None
    stream.closed = False
    stream.metadata = [100, time.monotonic_ns() - 3_000_000_000]
    stream.profile = CameraProfile(device='/dev/video0',width=640,height=480,fps=30)
    stream.process = SimpleNamespace(is_alive=lambda: True, exitcode=None)
    stream.started = time.monotonic() - 10
    stale = stream.status()
    assert not stale['connected'] and stale['process_alive']
    assert '수신 지연' in stale['error']
    stream.metadata[1] = time.monotonic_ns()
    assert stream.status()['connected']
    assert stream.status()['error'] is None


@pytest.mark.parametrize('failure', [TimeoutError, ValueError, RuntimeError])
def test_preview_failure_does_not_stop_live_outputs_and_next_frame_recovers(rig, monkeypatch, failure):
    from tests_station.test_bench import setup
    client, app = rig
    apply(client, app)
    setup(client)
    assert client.post('/api/bench/io/connect', json={}).status_code == 200
    assert pulse(client, 'led', seconds=None).status_code == 200
    stream = app.state.camera.stream
    original = app.state.camera.read_latest
    def interrupted():
        raise failure('temporary preview failure')
    monkeypatch.setattr(app.state.camera, 'read_latest', interrupted)
    response = client.get('/api/camera/frame')
    assert response.status_code == 503
    assert app.state.camera.stream is stream and not stream.closed
    assert app.state.bench.io.led is True
    assert 'led' in app.state.bench.runs
    monkeypatch.setattr(app.state.camera, 'read_latest', original)
    assert client.get('/api/camera/frame').status_code == 200
    assert app.state.bench.io.led is True
