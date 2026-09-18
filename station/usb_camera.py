"""Linux UVC capture and controls with bounded subprocesses and one camera owner."""
from __future__ import annotations

import multiprocessing as mp
from multiprocessing import shared_memory
import platform
import re
import subprocess
import threading
import time
from pathlib import Path

from pydantic import Field, model_validator
from .schema import Model
from .controller import Conflict


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
            raise ValueError("카메라 연결을 확인하세요.") from exc
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
        info = self.inspect(profile.device)
        if not any(m["width"] == profile.width and m["height"] == profile.height
                   and m["pixel_format"] == profile.pixel_format and abs(m["fps"] - profile.fps) < 0.05 for m in info["modes"]):
            raise ValueError("카메라가 지원하는 해상도와 FPS를 선택하세요.")
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
        while True:
            ok, frame = cap.read()
            received = time.monotonic_ns()
            if not ok or frame is None:
                raise RuntimeError("카메라 영상이 끊겼습니다.")
            if frame.shape != target.shape:
                raise RuntimeError("실제 영상 크기가 설정과 다릅니다.")
            with lock:
                np.copyto(target, frame)
                metadata[0] += 1
                metadata[1] = received
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


class UVCStream:
    def __init__(self, profile):
        self.profile = profile
        ctx = mp.get_context("spawn")
        self.lock = ctx.Lock()
        self.metadata = ctx.Array("q", 2, lock=False)
        self.errors = ctx.Queue(maxsize=1)
        self.mem = shared_memory.SharedMemory(create=True, size=profile.width * profile.height * 3)
        self.started = time.monotonic()
        self.error = None
        self.closed = False
        self.process = ctx.Process(target=_capture_process, args=(profile.model_dump(), self.mem.name, self.metadata, self.lock, self.errors), daemon=True)
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
        return {"connected": bool(alive and seq and not self.error and age < max(2000, 3000 / self.profile.fps)),
                "frames": seq, "last_frame_age_ms": age, "error": self.error,
                "width": self.profile.width, "height": self.profile.height,
                "requested_fps": self.profile.fps, "mean_received_fps": seq / max(0.001, time.monotonic() - self.started),
                "source": self.profile.device, "dropped_frames": None, "sensor_timestamp": None}

    def read_latest(self):
        import numpy as np
        if not self.status()["connected"]:
            raise ValueError(self.error or "새 카메라 영상이 없습니다.")
        if not self.lock.acquire(timeout=0.5):
            raise TimeoutError("카메라 프레임 읽기 시간이 초과되었습니다.")
        try:
            img = np.ndarray((self.profile.height, self.profile.width, 3), dtype=np.uint8, buffer=self.mem.buf).copy()
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
        self.revision = int(store.get("camera_settings_revision", 0))

    def status(self):
        # Do not block the UI or output STOP while a configuration operation is running.
        stream = self.stream
        status = stream.status() if stream else {"connected": False, "frames": 0}
        return {**status, "error": self.error or status.get("error"),
                "profile": self.profile, "saved_profile": self.saved,
                "revision": self.revision, "identity": self.identity}

    def inspect(self, device):
        return self.backend.inspect(device)

    def apply(self, profile, persist=False, actor="local-operator"):
        with self.lock:
            previous, was_open = self.profile, self.stream is not None
            original = self.backend.inspect(profile.device).get("current")
            self._close_stream()
            self.error = None
            try:
                info = self.backend.apply(profile)
                stream = self.stream_factory(profile)
                self.stream = stream
                # Opening a native capture backend can renegotiate mode or reset controls.
                current = self.backend.inspect(profile.device)
                actual = current["current"]
                if not actual or any(actual[k] != getattr(profile, k) for k in ("width", "height", "pixel_format")) or abs(actual["fps"] - profile.fps) > 0.05:
                    raise ValueError("영상 연결 후 해상도 또는 FPS가 달라졌습니다.")
                values = {c["name"]: c["value"] for c in current["controls"]}
                if any(values.get(k) != v for k, v in profile.controls.items()):
                    raise ValueError("영상 연결 후 카메라 설정이 달라졌습니다.")
                accepted = {**profile.model_dump(), "controls": actual["controls"]}
                revision = self.revision + 1
                if persist:
                    import json
                    with self.store.transaction() as c:
                        c.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", ("usb_camera_profile", json.dumps(accepted)))
                        c.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", ("camera_settings_revision", str(revision)))
                        self.store.event("CAMERA_SETTINGS_SAVED", {"actor": actor, "profile": accepted, "revision": revision}, c)
                    self.saved = accepted
                self.profile, self.revision, self.identity = accepted, revision, info["identity"]
                return {**self.status(), "capabilities": current}
            except Exception as exc:
                self._close_stream()
                self.profile = None
                self.error = str(exc)
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
        if self.saved:
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
        with self.lock:
            if not self.stream:
                raise ValueError("카메라가 연결되지 않았습니다.")
            return self.stream.read_latest()

    def after(self, minimum_ns, timeout):
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
            self._close_stream()
