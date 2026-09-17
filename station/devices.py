"""No simulated device health is advertised as a physical measurement."""

from __future__ import annotations

import threading
import time


class ReplayIO:
    def __init__(self):
        self.motor_requested = False

    def stop(self):
        self.motor_requested = False

    def motor(self, value, allowed=None):
        if value:
            raise RuntimeError("REPLAY에서는 장비 출력을 지원하지 않습니다.")
        self.stop()

    def snapshot(self):
        return {
            "source": "REPLAY",
            "connected": False,
            "motor_requested": False,
            "km2_on": None,
            "di_raw": None,
            "led_requested": False,
            "physical_permit": None,
            "supports_en_reset": False,
            "fault": None,
            "observed_at": time.time(),
        }

    def blockers(self):
        return ["실물 I/O가 연결되지 않았습니다."]

    def close(self):
        self.stop()


class UnavailableIO(ReplayIO):
    def __init__(self, reason):
        super().__init__()
        self.reason = reason

    def snapshot(self):
        return {**super().snapshot(), "source": "HARDWARE", "fault": self.reason}

    def blockers(self):
        return [self.reason]

    def motor(self, value, allowed=None):
        if value:
            raise RuntimeError(self.reason)


class LeaseGuard:
    """Independent thread drops software request on stale controller leases.

    This is not an OS-hang/SIGKILL safety guarantee. HARDWARE readiness requires
    those physical tests and a verified independent stop mechanism.
    """

    def __init__(self, io, lease_ms):
        self.io = io
        self.lease = lease_ms / 1000
        self.last = time.monotonic()
        self.closed = threading.Event()
        self.failed = None
        self.thread = threading.Thread(target=self.run, daemon=True, name="io-lease")
        self.thread.start()

    def renew(self):
        self.last = time.monotonic()
        if hasattr(self.io, "renew"):
            self.io.renew()

    def run(self):
        while not self.closed.wait(min(self.lease / 4, 0.05)):
            if time.monotonic() - self.last > self.lease:
                self.failed = "IO_LEASE_EXPIRED"
                try:
                    self.io.stop()
                except Exception as exc:
                    self.failed = str(exc)

    def close(self):
        self.closed.set()
        try:
            self.io.stop()
        finally:
            self.thread.join(timeout=1)
