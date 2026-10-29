"""Wappen counting trial on the live camera, without creating a production job.

REPLAY (bench) mode has no conveyor flow engine, so this is the only way to see
the saved wappen settings count real products. Counts stay on the test screen.
"""
from __future__ import annotations

import threading
import time

from .controller import Conflict
from .schema import WorkPreset


class VisionTrial:
    def __init__(self, camera, store, counter_factory=None):
        self.camera, self.store = camera, store
        self.counter_factory = counter_factory
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.thread = None
        self.state = {"active": False, "total": 0, "boxes": [], "width": 0, "height": 0,
                      "inference_ms": None, "frames": 0, "error": None, "preset": None}

    def busy(self):
        return bool(self.thread and self.thread.is_alive())

    def start(self, preset_id):
        raw = self.store.get("work_presets", {}).get(preset_id)
        if not raw:
            raise Conflict("와펜 계수 설정이 없습니다.")
        preset = WorkPreset.model_validate(raw)
        if preset.kind != "vision":
            raise Conflict("와펜 계수 설정을 고르세요.")
        if not self.camera.status().get("connected") and getattr(self.camera, "saved", None):
            self.camera.connect()
        if not self.camera.status().get("connected"):
            raise Conflict("카메라가 연결되지 않았습니다.")
        factory = self.counter_factory
        if factory is None:
            from .counting import ObjectCounter as factory
        counter = factory(preset.flow)
        with self.lock:
            if self.busy():
                raise Conflict("와펜 계수 시험이 이미 진행 중입니다.")
            self.cancel.clear()
            self.state = {"active": True, "total": 0, "boxes": [], "width": 0, "height": 0,
                          "inference_ms": None, "frames": 0, "error": None,
                          "preset": {"id": preset.id, "name": preset.name, "revision": preset.revision,
                                     "flow": preset.flow.model_dump()}}
            self.thread = threading.Thread(target=self._run, args=(counter,), daemon=True,
                                           name="vision-trial")
            self.thread.start()
        self.store.event("BENCH_VISION_TRIAL_START", {"preset": preset.id, "revision": preset.revision})
        return self.status()

    def _run(self, counter):
        seen = -1
        try:
            while not self.cancel.wait(0.01):
                status = self.camera.status()
                if not status.get("connected"):
                    raise RuntimeError("카메라 연결이 끊겼습니다.")
                if status.get("frames", 0) <= seen:
                    continue
                frame, metadata = self.camera.read_latest()
                seen = int(metadata.get("seq", seen + 1))
                result = counter.update(frame, time.monotonic())
                with self.lock:
                    self.state.update(total=result["total"], boxes=result["boxes"], width=result["width"],
                                      height=result["height"], inference_ms=round(result["inference_ms"], 1),
                                      frames=self.state["frames"] + 1)
        except Exception as exc:
            with self.lock:
                self.state["error"] = str(exc)
        finally:
            with self.lock:
                self.state["active"] = False

    def stop(self, reason=None):
        self.cancel.set()
        thread = self.thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)
        return self.status()

    def status(self):
        with self.lock:
            return {**self.state, "boxes": list(self.state["boxes"])}
