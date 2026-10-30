"""Linux UVC capture and controls with bounded subprocesses and one camera owner."""
from __future__ import annotations

import multiprocessing as mp
from multiprocessing import shared_memory
import platform
import logging
import re
import subprocess
import threading
import time
from pathlib import Path

from pydantic import Field, model_validator
from .schema import Model
from .controller import Conflict


def frame_at(camera, minimum_ns, timeout, previous_seq=-1, cancelled=None):
    """Read a distinct frame received at/after a moving capture's due time.

    The stopped-capture after() method discards two frames for settling. Moving
    products instead need the available frame from their scheduled position.
    Run this wait in a worker, keeping sensor and output monitoring responsive.
    """
    deadline = time.monotonic() + timeout
    checked = previous_seq
    while time.monotonic() < deadline:
        if cancelled is not None and cancelled.is_set():
            raise RuntimeError("촬영이 취소되었습니다.")
        status = camera.status()
        if not status.get("connected"):
            raise RuntimeError("카메라 연결이 끊겼습니다.")
        if status.get("frames", 0) > checked:
            frame, metadata = camera.read_latest()
            sequence = int(metadata["seq"])
            if sequence > previous_seq and metadata["host_received_ns"] >= minimum_ns:
                return frame, metadata
            checked = max(checked, sequence)
        time.sleep(0.002)
    raise TimeoutError("새 카메라 영상 대기 시간 초과")


class CameraProfile(Model):
    device: str = Field(min_length=1, max_length=240)
    width: int = Field(ge=320, le=8000)
    height: int = Field(ge=240, le=6000)
    fps: float = Field(ge=1, le=120)
    pixel_format: str = Field(default="YUYV", pattern=r"^[A-Z0-9]{4}$")
    controls: dict[str, int] = Field(default_factory=dict, max_length=40)

    @model_validator(mode="after")
    def names(self):
        if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", k) for k in self.controls):
            raise ValueError("카메라 제어 이름이 올바르지 않습니다.")
        return self


FIXED_CAMERA_CONTROLS = (
    (("focus_auto", "focus_automatic_continuous"), "focus_absolute"),
    (("white_balance_temperature_auto", "white_balance_automatic"), "white_balance_temperature"),
)


def fixed_camera_profile(profile, capabilities):
    """Pin focus and white balance for both preview and capture, including reconnects.

    Older saved profiles can omit manual values or leave automatic mode enabled.
    Preserve an explicit manual value, otherwise freeze the current driver value.
    Unsupported controls are never invented.
    """
    controls = dict(profile.controls)
    actual = {c["name"]: c["value"] for c in capabilities["controls"]}
    for aliases, manual in FIXED_CAMERA_CONTROLS:
        for name in aliases:
            if name in actual:
                controls[name] = 0
                if manual in actual:
                    controls.setdefault(manual, actual[manual])
    return profile.model_copy(update={"controls": controls})


def parse_controls(text):
    result = {}
    current = None
    for line in text.splitlines():
        match = re.match(r"\s*(\w+)\s+0x[0-9a-f]+\s+\(([^)]+)\)\s*:\s*(.*)", line, re.I)
        if match:
            name, kind, rest = match.groups()
            current = {"name": name, "type": kind, "menu": {}}
            for key, value in re.findall(r"(min|max|step|default|value)=(-?\d+)", rest):
                current[key] = int(value)
            flags = re.search(r"flags=(.*)", rest)
            current["flags"] = flags.group(1).strip() if flags else ""
            if kind in ("int", "bool", "menu", "intmenu") and "value" in current:
                if kind == "bool":
                    current.update(min=0, max=1, step=1)
                result[name] = current
            else:
                current = None
        elif current:
            menu = re.match(r"\s*(-?\d+):\s*(.+)", line)
            if menu:
                current["menu"][int(menu.group(1))] = menu.group(2).strip()
    return result


def parse_modes(text):
    modes, fmt, size = [], None, None
    for line in text.splitlines():
        m = re.search(r"\[\d+\]:\s+'([^']+)'", line)
        if m:
            fmt, size = m.group(1), None
        m = re.search(r"Size: Discrete (\d+)x(\d+)", line)
        if m:
            size = tuple(map(int, m.groups()))
        m = re.search(r"\(([\d.]+) fps\)", line)
        if m and fmt and size:
            value = {"pixel_format": fmt, "width": size[0], "height": size[1], "fps": float(m.group(1))}
            if value not in modes:
                modes.append(value)
    return modes


class V4L2:
    def run(self, *args):
        if platform.system() != "Linux":
            raise ValueError("USB 카메라 설정은 J4012의 Linux에서 사용할 수 있습니다.")
        try:
            proc = subprocess.run(["v4l2-ctl", *args], capture_output=True, text=True, timeout=5)
        except FileNotFoundError as exc:
            raise ValueError("v4l-utils를 설치하세요.") from exc
        except subprocess.TimeoutExpired as exc:
            raise ValueError("카메라 응답 시간이 초과되었습니다.") from exc
        if proc.returncode:
            raise ValueError((proc.stderr or proc.stdout or "카메라 명령 실패").strip()[:600])
        return proc.stdout

    def device(self, value):
        # Accept only Linux video character devices, including persistent symlinks.
        path = Path(value)
        try:
            real = path.resolve(strict=True)
        except OSError as exc:
            raise ValueError(f"카메라 장치를 찾을 수 없습니다: {value}") from exc
        if not re.fullmatch(r"/dev/video\d+", str(real)) or not real.is_char_device():
            raise ValueError("영상 장치를 선택하세요.")
        return str(path)

    def devices(self):
        if platform.system() != "Linux":
            return {"devices": [], "error": "카메라 연결 시험은 J4012에서 사용할 수 있습니다."}
        devices = []
        links = sorted(Path("/dev/v4l/by-id").glob("*")) + sorted(Path("/dev/v4l/by-path").glob("*"))
        for entry in sorted(Path("/sys/class/video4linux").glob("video*")):
            node = Path("/dev") / entry.name
            aliases = [str(p) for p in links if p.resolve() == node]
            try:
                modes = parse_modes(self.run("-d", str(node), "--list-formats-ext"))
                if not modes:  # Exclude metadata-only nodes.
                    continue
                devices.append({"device": aliases[0] if aliases else str(node),
                                "name": (entry / "name").read_text().strip(), "node": str(node)})
            except (ValueError, OSError):
                continue
        return {"devices": devices, "error": None if devices else "영상 장치가 없습니다. USB 연결과 v4l-utils를 확인하세요."}

    def inspect(self, device):
        device = self.device(device)
        modes = parse_modes(self.run("-d", device, "--list-formats-ext"))
        controls = parse_controls(self.run("-d", device, "--list-ctrls-menus"))
        current = self.run("-d", device, "--get-fmt-video", "--get-parm")
        size = re.search(r"Width/Height\s*:\s*(\d+)/(\d+)", current)
        fps = re.search(r"Frames per second\s*:\s*([\d.]+)", current)
        fmt = re.search(r"Pixel Format\s*:\s*'([^']+)'", current)
        active = None
        if size and fps and fmt:
            active = {"device": device, "width": int(size[1]), "height": int(size[2]),
                      "fps": float(fps[1]), "pixel_format": fmt[1],
                      "controls": {k: v["value"] for k, v in controls.items()
                                   if not any(f in v["flags"] for f in ("read-only", "inactive", "disabled"))}}
        identity = self.run("-d", device, "--info")
        return {"device": device, "identity": identity[:3000], "modes": modes,
                "controls": list(controls.values()), "current": active}

    def apply(self, profile):
        return self._apply(profile, configure_mode=True)

    def apply_controls(self, profile):
        return self._apply(profile, configure_mode=False)

    def _apply(self, profile, *, configure_mode):
        info = self.inspect(profile.device)
        if not any(m["width"] == profile.width and m["height"] == profile.height
                   and m["pixel_format"] == profile.pixel_format and abs(m["fps"] - profile.fps) < 0.05 for m in info["modes"]):
            raise ValueError("카메라가 지원하는 해상도와 FPS를 선택하세요.")
        if configure_mode:
            self.run("-d", profile.device, "--set-fmt-video=" +
                     f"width={profile.width},height={profile.height},pixelformat={profile.pixel_format}",
                     f"--set-parm={profile.fps}")
        # Automatic mode controls first; query inactive flags again before manual controls.
        for name in sorted(profile.controls, key=lambda n: ("auto" not in n, n)):
            controls = parse_controls(self.run("-d", profile.device, "--list-ctrls-menus"))
            c, value = controls.get(name), profile.controls[name]
            if not c:
                raise ValueError("지원하지 않는 카메라 설정: " + name)
            if c["value"] == value:
                continue
            if any(f in c["flags"] for f in ("inactive", "read-only", "disabled")):
                raise ValueError("현재 모드에서 변경할 수 없는 설정: " + name)
            if c["menu"]:
                valid = value in c["menu"]
            else:
                valid = c.get("min", value) <= value <= c.get("max", value) and (value - c.get("min", 0)) % max(c.get("step", 1), 1) == 0
            if not valid:
                raise ValueError("카메라 설정 범위를 확인하세요: " + name)
            self.run("-d", profile.device, f"--set-ctrl={name}={value}")
        actual = self.inspect(profile.device)
        cur = actual["current"]
        if not cur or any(cur[k] != getattr(profile, k) for k in ("width", "height", "pixel_format")) or abs(cur["fps"] - profile.fps) > 0.05:
            raise ValueError("카메라가 요청한 해상도 또는 FPS를 적용하지 못했습니다.")
        readback = {c["name"]: c["value"] for c in actual["controls"]}
        if any(readback.get(k) != v for k, v in profile.controls.items()):
            raise ValueError("카메라 설정 재조회 값이 일치하지 않습니다.")
        return actual


def _capture_process(settings, memory_name, metadata, lock, errors):
    """Native capture lives in a process so a stuck USB read can be terminated."""
    mem, cap = None, None
    try:
        import cv2
        import numpy as np
        cv2.setNumThreads(1)
        mem = shared_memory.SharedMemory(name=memory_name)
        cap = cv2.VideoCapture(settings["device"], cv2.CAP_V4L2)
        if not cap.isOpened():
            raise RuntimeError("카메라를 열 수 없습니다.")
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*settings["pixel_format"]))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, settings["width"])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, settings["height"])
        cap.set(cv2.CAP_PROP_FPS, settings["fps"])
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        target = np.ndarray((settings["height"], settings["width"], 3), dtype=np.uint8, buffer=mem.buf)
        last_frame_at = time.monotonic()
        frame_timeout = max(2.0, 3.0 / settings["fps"])
        read_error = ""
        while True:
            capture_stage(metadata, 1)
            try:
                ok, frame = cap.read()
            except cv2.error as exc:
                ok, frame = False, None
                read_error = str(exc)
            received = time.monotonic_ns()
            if not ok or frame is None:
                metadata[2] += 1
                # A dropped UVC frame is not a request to release the camera.
                # Freshness monitoring still stops a process with no new frames.
                if time.monotonic() - last_frame_at >= frame_timeout:
                    raise RuntimeError(f"카메라 프레임 읽기 실패: {frame_timeout:.1f}초 동안 새 영상 없음 {read_error}")
                time.sleep(0.01)
                continue
            last_frame_at = time.monotonic()
            read_error = ""
            if frame.shape != target.shape:
                raise RuntimeError("실제 영상 크기가 설정과 다릅니다.")
            publish_frame(frame, mem.buf, metadata, lock, received)
    except BaseException as exc:
        try:
            errors.put_nowait(str(exc))
        except Exception:
            pass
    finally:
        if cap:
            cap.release()
        if mem:
            mem.close()


def preview_shape(width, height):
    scale = min(1., 1280 / width)
    return max(1, round(height * scale)), min(width, 1280), 3


def capture_stage(metadata, value):
    if len(metadata) >= 5:
        metadata[3], metadata[4] = value, time.monotonic_ns()


def usb_link(device):
    """Read the camera's current USB identity at a loss, without running commands."""
    try:
        node = Path(device).resolve()
        info = {"node": str(node), "device_present": node.exists()}
        sys_device = Path("/sys/class/video4linux") / node.name / "device"
        if not sys_device.exists():
            return info
        for parent in sys_device.resolve().parents:
            if (parent / "idVendor").is_file():
                for field in ("idVendor", "idProduct", "speed", "busnum", "devnum", "power/control", "power/runtime_status"):
                    try:
                        info[field] = (parent / field).read_text().strip()
                    except OSError:
                        pass
                break
        return info
    except OSError as exc:
        return {"error": str(exc)}


def publish_frame(frame, buffer, metadata, lock, received):
    """Publish the original and a small preview from the same camera frame."""
    import cv2
    import numpy as np
    target = np.ndarray(frame.shape, dtype=np.uint8, buffer=buffer)
    shape = preview_shape(frame.shape[1], frame.shape[0])
    preview = None
    capture_stage(metadata, 2)
    if len(buffer) > frame.nbytes:
        preview = cv2.resize(frame, (shape[1], shape[0])) if shape != frame.shape else frame
    capture_stage(metadata, 3)
    with lock:
        capture_stage(metadata, 4)
        np.copyto(target, frame)
        if preview is not None:
            np.copyto(np.ndarray(shape, dtype=np.uint8, buffer=buffer, offset=frame.nbytes), preview)
        metadata[0] += 1
        metadata[1] = received


class UVCStream:
    def __init__(self, profile, capture_target=_capture_process, extra_args=()):
        self.profile = profile
        ctx = mp.get_context("spawn")
        self.lock = ctx.Lock()
        self.metadata = ctx.Array("q", 5, lock=False)
        self.errors = ctx.Queue(maxsize=1)
        self.preview_shape = preview_shape(profile.width, profile.height)
        self.mem = shared_memory.SharedMemory(create=True, size=profile.width * profile.height * 3
                                             + self.preview_shape[0] * self.preview_shape[1] * 3)
        self.started = time.monotonic()
        self.error = None
        self.closed = False
        self.process = ctx.Process(target=capture_target, args=(profile.model_dump(), self.mem.name, self.metadata, self.lock, self.errors, *extra_args), daemon=True)
        try:
            self.process.start()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if self.status()["connected"]:
                    return
                if self.error:
                    raise RuntimeError(self.error)
                time.sleep(0.05)
            raise TimeoutError("카메라 영상 응답이 없습니다.")
        except BaseException:
            self.close()
            raise

    def status(self):
        try:
            self.error = self.errors.get_nowait()
        except Exception:
            pass
        seq, ns = self.metadata[0], self.metadata[1]
        age = (time.monotonic_ns() - ns) / 1e6 if ns else None
        alive = not self.closed and self.process.is_alive()
        if not alive and not self.closed:
            self.error = self.error or "카메라 처리기가 종료되었습니다."
        stale = bool(alive and ns and age >= max(2000, 3000 / self.profile.fps))
        detail = self.error or (f"카메라 새 프레임 수신 지연: {age / 1000:.1f}초" if stale else None)
        return {"connected": bool(alive and seq and not detail),
                "frames": seq, "last_frame_age_ms": age, "error": detail, "process_alive": alive,
                "process_exitcode": self.process.exitcode,
                "read_failures": self.metadata[2] if len(self.metadata) > 2 else 0,
                "capture_stage": ({1: "device_read", 2: "preview_resize", 3: "frame_lock", 4: "frame_copy"}
                                  .get(self.metadata[3], "starting") if len(self.metadata) >= 5 else None),
                "capture_stage_ms": ((time.monotonic_ns() - self.metadata[4]) / 1e6
                                     if len(self.metadata) >= 5 and self.metadata[4] else None),
                "width": self.profile.width, "height": self.profile.height,
                "requested_fps": self.profile.fps, "mean_received_fps": seq / max(0.001, time.monotonic() - self.started),
                "source": self.profile.device, "dropped_frames": None, "sensor_timestamp": None}

    def read_latest(self):
        return self._read(False)

    def read_preview(self):
        return self._read(True)

    def _read(self, preview):
        import numpy as np
        if not self.status()["connected"]:
            raise ValueError(self.error or "새 카메라 영상이 없습니다.")
        if not self.lock.acquire(timeout=0.5):
            raise TimeoutError("카메라 프레임 읽기 시간이 초과되었습니다.")
        try:
            shape = self.preview_shape if preview else (self.profile.height, self.profile.width, 3)
            offset = self.profile.width * self.profile.height * 3 if preview else 0
            img = np.ndarray(shape, dtype=np.uint8, buffer=self.mem.buf, offset=offset).copy()
            return img, {"seq": self.metadata[0], "host_received_ns": self.metadata[1], "sensor_timestamp": None}
        finally:
            self.lock.release()

    def after(self, minimum_ns, timeout):
        baseline = self.metadata[0]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.error or self.closed:
                raise RuntimeError(self.error or "카메라 연결 종료")
            if self.metadata[0] >= baseline + 2 and self.metadata[1] > minimum_ns:
                return self.read_latest()
            self.status()
            time.sleep(0.01)
        raise TimeoutError("새 카메라 영상 대기 시간 초과")

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.process.pid:
            self.process.terminate()
            self.process.join(timeout=1)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=1)
        self.mem.close()
        self.mem.unlink()
        self.errors.close()


class CameraManager:
    def __new__(cls, *args, **kwargs):
        if cls is CameraManager and platform.system() == "Windows" and kwargs.get("backend") is None and len(args) < 3:
            from .windows_camera import WindowsCameraManager
            return object.__new__(WindowsCameraManager)
        return object.__new__(cls)

    def __init__(self, config, store, backend=None, stream_factory=UVCStream):
        self.config, self.store = config, store
        self.backend = backend or V4L2()
        self.stream_factory = stream_factory
        self.stream = None
        self.lock = threading.RLock()
        self.saved = store.get("usb_camera_profile")
        self.profile = None
        self.error = None
        self.identity = None
        self._health_state = None
        self.revision = int(store.get("camera_settings_revision", 0))
        # The camera stays on once it was turned on, until someone turns it off.
        # Recovery keeps bringing a wanted camera back with its last settings.
        self.wanted = False
        self.reconnect_attempts = 0

    def status(self):
        # Do not block the UI or output STOP while a configuration operation is running.
        stream = self.stream
        status = stream.status() if stream else {"connected": False, "frames": 0}
        health = (status.get("connected"), status.get("process_alive"), status.get("process_exitcode"))
        if stream and health != self._health_state:
            if not status.get("connected"):
                logging.getLogger(__name__).warning(
                    "CAMERA_INTERRUPTED device=%s frames=%s age_ms=%s process_alive=%s exitcode=%s read_failures=%s error=%s capture_stage=%s stage_ms=%s usb=%s",
                    (self.profile or {}).get("device"), status.get("frames"), status.get("last_frame_age_ms"),
                    status.get("process_alive"), status.get("process_exitcode"), status.get("read_failures"), status.get("error"),
                    status.get("capture_stage"), status.get("capture_stage_ms"),
                    usb_link((self.profile or {}).get("device", "")))
            self._health_state = health
        return {**status, "error": self.error or status.get("error"),
                "profile": self.profile, "saved_profile": self.saved,
                "revision": self.revision, "identity": self.identity,
                "wanted": self.wanted,
                "reconnecting": self.wanted and not status.get("connected"),
                "reconnect_attempts": self.reconnect_attempts}

    def inspect(self, device):
        return self.backend.inspect(device)

    def apply(self, profile, persist=False, actor="local-operator"):
        with self.lock:
            previous, was_open = self.profile, self.stream is not None
            initial = self.backend.inspect(profile.device)
            original = initial.get("current")
            profile = fixed_camera_profile(profile, initial)
            mode_keys = ("device", "width", "height", "pixel_format")
            same_mode = bool(previous and original and self.stream and self.stream.status().get("connected")
                             and all(previous[k] == getattr(profile, k) and original[k] == getattr(profile, k) for k in mode_keys)
                             and abs(original["fps"] - profile.fps) < 0.05
                             and abs(previous["fps"] - profile.fps) < 0.05)
            values = {c["name"]: c["value"] for c in initial["controls"]}
            unchanged = same_mode and all(values.get(k) == v for k, v in profile.controls.items())
            reuse_stream = same_mode and (unchanged or hasattr(self.backend, "apply_controls"))
            self.error = None
            try:
                if reuse_stream:
                    info = initial if unchanged else self.backend.apply_controls(profile)
                else:
                    self.store.event("CAMERA_STREAM_RESTART", {"actor": actor, "previous": previous,
                                                              "requested": profile.model_dump()})
                    self._close_stream()
                    info = self.backend.apply(profile)
                    self.stream = self.stream_factory(profile)
                # Opening a native capture backend can renegotiate mode or reset controls.
                current = self.backend.inspect(profile.device)
                actual = current["current"]
                if not actual or any(actual[k] != getattr(profile, k) for k in ("width", "height", "pixel_format")) or abs(actual["fps"] - profile.fps) > 0.05:
                    raise ValueError("영상 연결 후 해상도 또는 FPS가 달라졌습니다.")
                values = {c["name"]: c["value"] for c in current["controls"]}
                if any(values.get(k) != v for k, v in profile.controls.items()) and hasattr(self.backend, "apply_controls"):
                    # UVC drivers can reset focus and white balance when the capture
                    # opens. Put the requested values back once, then verify again.
                    self.backend.apply_controls(profile)
                    current = self.backend.inspect(profile.device)
                    actual = current["current"] or actual
                    values = {c["name"]: c["value"] for c in current["controls"]}
                if any(values.get(k) != v for k, v in profile.controls.items()):
                    raise ValueError("영상 연결 후 카메라 설정이 달라졌습니다.")
                accepted = {**profile.model_dump(), "controls": actual["controls"]}
                # Reconnecting with the same settings keeps the settings revision,
                # so a settings screen opened before a reconnect stays valid.
                same = bool(previous) and all(previous.get(k) == accepted[k] for k in mode_keys) \
                    and abs(previous.get("fps", 0) - accepted["fps"]) < 0.05 \
                    and all(previous["controls"].get(k) == v for k, v in profile.controls.items())
                revision = self.revision if same and not persist else self.revision + 1
                if persist:
                    import json
                    with self.store.transaction() as c:
                        c.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", ("usb_camera_profile", json.dumps(accepted)))
                        c.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", ("camera_settings_revision", str(revision)))
                        self.store.event("CAMERA_SETTINGS_SAVED", {"actor": actor, "profile": accepted, "revision": revision}, c)
                    self.saved = accepted
                self.profile, self.revision, self.identity = accepted, revision, info["identity"]
                self.wanted = True
                self.reconnect_attempts = 0
                return {**self.status(), "capabilities": current}
            except Exception as exc:
                self.error = str(exc)
                if reuse_stream:
                    try:
                        if not unchanged:
                            self.backend.apply_controls(CameraProfile.model_validate(previous))
                    except Exception as restore:
                        self.error += " / 이전 설정 복원 실패: " + str(restore)
                        self._close_stream()
                        self.profile = None
                    raise ValueError(self.error) from exc
                self._close_stream()
                self.profile = None
                try:
                    if original:
                        self.backend.apply(CameraProfile.model_validate(original))
                    if previous and was_open:
                        old = CameraProfile.model_validate(previous)
                        self.backend.apply(old)
                        self.stream = self.stream_factory(old)
                        self.profile = previous
                except Exception as restore:
                    self.error += " / 이전 설정 복원 실패: " + str(restore)
                    self._close_stream()
                raise ValueError(self.error) from exc

    def connect(self):
        if self.status().get("connected"):
            return self.status()
        if self.saved:
            # A failed attempt still counts as a request; recovery keeps trying.
            self.wanted = True
            self.store.put("camera_wanted", True)
            return self.apply(CameraProfile.model_validate(self.saved))
        if self.config.camera_source in ("CSI0", "CSI1"):
            from .hardware import Camera
            with self.lock:
                self._close_stream()
                self.stream = Camera(self.config)
                self.error = None
            return self.status()
        raise Conflict("환경 설정에서 카메라와 촬영 설정을 저장하세요.")

    def read_latest(self):
        return self._read_frame(False)

    def read_preview(self):
        return self._read_frame(True)

    def _read_frame(self, preview):
        with self.lock:
            if not self.stream:
                raise ValueError("카메라가 연결되지 않았습니다.")
            reader = getattr(self.stream, "read_preview", self.stream.read_latest) if preview else self.stream.read_latest
            image, metadata = reader()
            return image, {**metadata, "camera_settings_revision": self.revision,
                           "camera_profile": self.profile}

    def ensure(self):
        """Reconnect a wanted camera with its last settings. Returns True when it tried."""
        with self.lock:
            if not self.wanted or self.status().get("connected"):
                return False
            profile = self.profile or self.saved
            if not profile:
                return False
            self.reconnect_attempts += 1
            try:
                self.apply(CameraProfile.model_validate(profile), persist=False, actor="camera-recovery")
            except Exception as exc:
                # A device that cannot even be opened fails before apply records why.
                self.error = str(exc)
                raise
            self.store.event("CAMERA_RECOVERED", {"device": profile["device"]})
            return True

    def give_up(self):
        """Stop reconnecting by itself; the last error stays for the screen. A restart tries again."""
        with self.lock:
            if not self.status().get("connected"):
                self.wanted = False

    def recover(self, expected_stream):
        with self.lock:
            # A manual disconnect or another apply invalidates the pending retry.
            if self.stream is not expected_stream or not self.profile:
                return
            if self.stream.status().get("connected"):
                return
            profile = CameraProfile.model_validate(self.profile)
            self.apply(profile, persist=False, actor="camera-recovery")
            self.store.event("CAMERA_RECOVERED", {"device": profile.device})

    def _fixed_drift(self):
        info = self.inspect(self.profile["device"])
        actual = {c["name"]: c["value"] for c in info["controls"]}
        expected = self.profile["controls"]
        return {name: actual.get(name) for aliases, manual in FIXED_CAMERA_CONTROLS
                for name in (*aliases, manual) if name in expected and actual.get(name) != expected[name]}

    def verify_fixed_controls(self):
        """Before a capture, put drifted focus and white balance back to the applied values.

        The driver can reset them on its own (USB re-enumeration, capture reopen).
        The restore is recorded; a capture is refused only when it does not stick.
        """
        with self.lock:
            if not self.profile:
                return
            drift = self._fixed_drift()
            if not drift:
                return
            message = "카메라 초점 또는 화이트밸런스를 저장값으로 되돌리지 못했습니다."
            profile = CameraProfile.model_validate(self.profile)
            try:
                if hasattr(self.backend, "apply_controls"):
                    self.backend.apply_controls(profile)
                else:
                    self.apply(profile, persist=False, actor="camera-restore")
            except Exception as exc:
                raise Conflict(f"{message} {exc}") from exc
            self.store.event("CAMERA_CONTROLS_RESTORED", {"device": profile.device, "drift": drift})
            if self.profile and not self._fixed_drift():
                return
            raise Conflict(message)

    def after(self, minimum_ns, timeout):
        with self.lock:
            stream = self.stream
            if not stream:
                raise RuntimeError("카메라가 연결되지 않았습니다.")
            image, metadata = stream.after(minimum_ns, timeout)
            return image, {**metadata, "camera_settings_revision": self.revision, "camera_profile": self.profile}

    def _close_stream(self):
        stream, self.stream = self.stream, None
        if stream:
            stream.close()

    def close(self):
        with self.lock:
            self.wanted = False
            self._close_stream()
