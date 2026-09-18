"""Windows DirectShow adapter for the same camera profile and bench API as Linux.

COM objects stay inside bounded child processes. The capture graph owns settings
and images together, so readback describes the camera actually producing frames.
"""
from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import re
import threading
import time

from .usb_camera import CameraManager, CameraProfile, UVCStream


def device_id(index, name):
    return f"dshow:{index}:" + hashlib.sha256(name.encode()).hexdigest()[:12]


def _open(device=None):
    from pygrabber.dshow_graph import FilterGraph
    graph = FilterGraph()
    names = graph.get_input_devices()
    if device is not None:
        match = re.fullmatch(r"dshow:(\d+):[0-9a-f]{12}", device)
        if not match or int(match[1]) >= len(names) or device_id(int(match[1]), names[int(match[1])]) != device:
            raise ValueError("카메라 목록을 다시 읽고 장치를 선택하세요.")
        graph.add_video_input_device(int(match[1]))
    return graph, names


def _interfaces():
    from ctypes import POINTER, c_long
    from comtypes import COMMETHOD, GUID, HRESULT, IUnknown
    def methods():
        return [
            COMMETHOD([], HRESULT, "GetRange", (["in"], c_long, "property"),
                      *[(["out"], POINTER(c_long), name) for name in ("minimum", "maximum", "step", "default", "caps")]),
            COMMETHOD([], HRESULT, "Set", (["in"], c_long, "property"), (["in"], c_long, "value"), (["in"], c_long, "flags")),
            COMMETHOD([], HRESULT, "Get", (["in"], c_long, "property"), (["out"], POINTER(c_long), "value"), (["out"], POINTER(c_long), "flags")),
        ]
    class ProcAmp(IUnknown):
        _iid_ = GUID("{C6E13360-30AC-11D0-A18C-00A0C9118956}")
        _methods_ = methods()
    class CameraControl(IUnknown):
        _iid_ = GUID("{C6E13370-30AC-11D0-A18C-00A0C9118956}")
        _methods_ = methods()
    return ProcAmp, CameraControl


PROC = {"brightness": 0, "contrast": 1, "hue": 2, "saturation": 3, "sharpness": 4,
        "gamma": 5, "white_balance_temperature": 7, "backlight_compensation": 8, "gain": 9}
CAMERA = {"zoom_absolute": 3, "exposure_absolute": 4, "focus_absolute": 6}
AUTO = {"exposure_absolute": "exposure_auto", "focus_absolute": "focus_auto",
        "white_balance_temperature": "white_balance_temperature_auto", "gain": "gain_auto"}


def _controls(graph):
    controls, bindings = [], {}
    for interface, properties in zip(_interfaces(), (PROC, CAMERA)):
        try:
            api = graph.get_input_device().instance.QueryInterface(interface)
        except Exception:
            continue
        for name, prop in properties.items():
            try:
                low, high, step, default, caps = api.GetRange(prop)
                value, flags = api.Get(prop)
            except Exception:
                continue
            control = {"name": name, "type": "int", "value": value, "min": low, "max": high,
                       "step": max(1, step), "default": default, "menu": {},
                       "flags": "inactive" if flags & 1 else ""}
            if not caps & 2:
                control["flags"] = "read-only"
            controls.append(control)
            bindings[name] = (api, prop, caps)
            if caps & 1 and caps & 2 and name in AUTO:
                auto = AUTO[name]
                controls.append({"name": auto, "type": "menu" if auto == "exposure_auto" else "bool",
                                 "value": (3 if flags & 1 else 1) if auto == "exposure_auto" else int(bool(flags & 1)),
                                 "min": 0, "max": 1, "step": 1, "flags": "",
                                 "menu": {1: "Manual Mode", 3: "Auto Mode"} if auto == "exposure_auto" else {}})
                bindings[auto] = (api, prop, caps)
    return controls, bindings


def _set_controls(graph, requested):
    for name in sorted(requested, key=lambda key: (key not in AUTO.values(), key)):
        controls, bindings = _controls(graph)
        control = next((c for c in controls if c["name"] == name), None)
        if control is None:
            raise ValueError("지원하지 않는 카메라 설정: " + name)
        value = requested[name]
        if value == control["value"]:
            continue
        if control["flags"]:
            raise ValueError("수동 모드로 변경한 뒤 조절하세요: " + name)
        api, prop, _ = bindings[name]
        if name in AUTO.values():
            if value not in (control["menu"] or (0, 1)):
                raise ValueError("카메라 자동 설정값이 올바르지 않습니다.")
            previous, _ = api.Get(prop)
            auto = value == 3 if name == "exposure_auto" else value == 1
            api.Set(prop, previous, 1 if auto else 2)
        else:
            if not control["min"] <= value <= control["max"] or (value - control["min"]) % control["step"]:
                raise ValueError("카메라 설정 범위를 확인하세요: " + name)
            api.Set(prop, value, 2)
    actual = {c["name"]: c for c in _controls(graph)[0]}
    for name, value in requested.items():
        if not actual[name]["flags"] and actual[name]["value"] != value:
            raise ValueError("카메라 적용값이 일치하지 않습니다: " + name)


def _format(media):
    from ctypes import POINTER, cast
    from pygrabber.dshow_core import VIDEOINFOHEADER
    from pygrabber.dshow_ids import FormatTypes
    from comtypes import GUID
    if media.contents.formattype != GUID(FormatTypes.FORMAT_VideoInfo):
        return None
    header = cast(media.contents.pbFormat, POINTER(VIDEOINFOHEADER)).contents
    bitmap = header.bmi_header
    fmt = int(bitmap.biCompression).to_bytes(4, "little").decode("ascii", errors="replace")
    if bitmap.biCompression == 0:
        fmt = "RGB3" if bitmap.biBitCount == 24 else "RGB4"
    if not re.fullmatch(r"[A-Z0-9]{4}", fmt) or header.avg_time_per_frame <= 0:
        return None
    return {"width": bitmap.biWidth, "height": abs(bitmap.biHeight), "pixel_format": fmt,
            "fps": round(10000000 / header.avg_time_per_frame, 2)}


def _free_media(media):
    from ctypes import windll, c_void_p, cast
    # IAMStreamConfig allocates both AM_MEDIA_TYPE and its format block.
    if media:
        if media.contents.cbFormat:
            windll.ole32.CoTaskMemFree(cast(media.contents.pbFormat, c_void_p))
        if media.contents.pUnk:
            media.contents.pUnk.Release()
        windll.ole32.CoTaskMemFree(cast(media, c_void_p))


def _stream_config(graph):
    from pygrabber.dshow_core import IAMStreamConfig
    return graph.get_input_device().get_out().QueryInterface(IAMStreamConfig)


def _mode_list(graph):
    api = _stream_config(graph)
    count, _ = api.GetNumberOfCapabilities()
    result = []
    for index in range(count):
        media, _ = api.GetStreamCaps(index)
        try:
            mode = _format(media)
            if mode and 320 <= mode["width"] <= 8000 and 240 <= mode["height"] <= 6000 and 1 <= mode["fps"] <= 120:
                result.append((index, mode))
        finally:
            _free_media(media)
    return result


def _info(graph, device):
    media = _stream_config(graph).GetFormat()
    try:
        current = _format(media)
    finally:
        _free_media(media)
    controls, _ = _controls(graph)
    if current:
        current.update(device=device, controls={c["name"]: c["value"] for c in controls if not c["flags"]})
    return {"device": device, "identity": graph.get_input_device().get_name(),
            "modes": [mode for _, mode in _mode_list(graph)], "controls": controls, "current": current,
            "unsupported_controls": [name for name in ("gain",) if not any(c["name"] == name for c in controls)]}


def _select_mode(graph, profile):
    for index, mode in _mode_list(graph):
        if all(mode[key] == profile[key] for key in ("width", "height", "pixel_format")) and abs(mode["fps"] - profile["fps"]) < 0.05:
            graph.get_input_device().set_format(index)
            return
    raise ValueError("지원 목록에서 해상도와 FPS를 선택하세요.")


def _probe(pipe, device):
    graph = None
    try:
        graph, names = _open(device)
        value = _info(graph, device) if device else {"devices": [
            {"device": device_id(i, name), "name": name, "node": device_id(i, name)} for i, name in enumerate(names)
        ], "error": None if names else "연결된 카메라가 없습니다."}
        pipe.send((True, value))
    except Exception as exc:
        pipe.send((False, str(exc)))
    finally:
        if graph:
            graph.remove_filters()
        pipe.close()


def probe(device=None):
    ctx = mp.get_context("spawn")
    parent, child = ctx.Pipe()
    process = ctx.Process(target=_probe, args=(child, device), daemon=True)
    process.start()
    child.close()
    try:
        if not parent.poll(15):
            raise ValueError("카메라 응답 시간이 초과되었습니다.")
        ok, value = parent.recv()
        if not ok:
            raise ValueError(value)
        return value
    finally:
        parent.close()
        process.join(1)
        if process.is_alive():
            process.terminate()
            process.join(1)


def _capture(settings, memory_name, metadata, lock, errors, pipe):
    from multiprocessing import shared_memory
    import numpy as np
    from comtypes.client import PumpEvents
    graph, mem = None, None
    try:
        graph, _ = _open(settings["device"])
        _select_mode(graph, settings)
        _set_controls(graph, settings["controls"])
        mem = shared_memory.SharedMemory(name=memory_name)
        target = np.ndarray((settings["height"], settings["width"], 3), dtype=np.uint8, buffer=mem.buf)
        def frame(image):
            if image.shape != target.shape:
                try: errors.put_nowait("실제 영상 크기가 설정과 다릅니다.")
                except Exception: pass
                return
            with lock:
                # pygrabber delivers bottom-up BGR converted to top-down BGR.
                np.copyto(target, image)
                metadata[0] += 1
                metadata[1] = time.monotonic_ns()
            graph.grab_frame()
        graph.add_sample_grabber(frame)
        graph.add_null_render()
        graph.prepare_preview_graph()
        graph.grab_frame()
        graph.run()
        while True:
            PumpEvents(0.01)
            if pipe.poll():
                command = pipe.recv()
                if command == "close": break
                try: pipe.send((True, _info(graph, settings["device"])))
                except Exception as exc: pipe.send((False, str(exc)))
    except BaseException as exc:
        try: errors.put_nowait(str(exc))
        except Exception: pass
    finally:
        if graph:
            graph.stop()
            graph.remove_filters()
        if mem: mem.close()
        pipe.close()


class WindowsStream(UVCStream):
    def __init__(self, profile):
        parent, child = mp.get_context("spawn").Pipe()
        self.pipe = parent
        self.rpc_lock = threading.Lock()
        try:
            super().__init__(profile, capture_target=_capture, extra_args=(child,))
        finally:
            child.close()

    def inspect(self):
        with self.rpc_lock:
            self.pipe.send("inspect")
            if not self.pipe.poll(8):
                self.close()
                raise ValueError("카메라 설정 응답 시간이 초과되었습니다.")
            ok, value = self.pipe.recv()
            if not ok: raise ValueError(value)
            return value

    def close(self):
        if getattr(self, "closed", False): return
        try:
            self.pipe.send("close")
            if getattr(self, "process", None) and self.process.pid: self.process.join(1)
        except (OSError, EOFError): pass
        super().close()
        self.pipe.close()


class WindowsBackend:
    def devices(self): return probe()
    def inspect(self, device): return probe(device)


class WindowsCameraManager(CameraManager):
    def __init__(self, config, store, **kwargs):
        super().__init__(config, store, backend=WindowsBackend(), stream_factory=WindowsStream)

    def inspect(self, device):
        if not isinstance(self.backend, WindowsBackend):
            return super().inspect(device)
        with self.lock:
            if self.stream and self.profile and self.profile["device"] == device:
                return self.stream.inspect()
            return self.backend.inspect(device)

    def apply(self, profile, persist=False, actor="local-operator"):
        if not isinstance(self.backend, WindowsBackend):
            return super().apply(profile, persist=persist, actor=actor)
        with self.lock:
            previous = self.profile if self.stream else None
            self._close_stream()
            self.error = None
            try:
                self.stream = self.stream_factory(profile)
                info = self.stream.inspect()
                actual = info["current"]
                if not actual or any(actual[k] != getattr(profile, k) for k in ("width", "height", "pixel_format")) or abs(actual["fps"] - profile.fps) > 0.05:
                    raise ValueError("카메라의 실제 촬영 설정이 요청값과 다릅니다.")
                values = {c["name"]: c for c in info["controls"]}
                if any(k not in values or (not values[k]["flags"] and values[k]["value"] != v) for k, v in profile.controls.items()):
                    raise ValueError("카메라 설정 재조회 값이 일치하지 않습니다.")
                revision = self.revision + 1
                if persist:
                    with self.store.transaction() as c:
                        c.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", ("usb_camera_profile", json.dumps(actual)))
                        c.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", ("camera_settings_revision", str(revision)))
                        self.store.event("CAMERA_SETTINGS_SAVED", {"actor": actor, "profile": actual, "revision": revision}, c)
                    self.saved = actual
                self.profile, self.revision, self.identity = actual, revision, info["identity"]
                return {**self.status(), "capabilities": info}
            except Exception as exc:
                self._close_stream()
                self.profile = None
                self.error = str(exc)
                if previous:
                    try:
                        self.stream = self.stream_factory(CameraProfile.model_validate(previous))
                        self.profile = previous
                    except Exception as restore:
                        self.error += " / 이전 연결 복원 실패: " + str(restore)
                raise ValueError(self.error) from exc
