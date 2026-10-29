"""Record the actual OCR operation; capture stalled stacks without ptrace/native unwinding."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import faulthandler
import os
from pathlib import Path
import threading
import time
import uuid

_current = ContextVar("ocr_trace", default=None)
_lock = threading.Lock()
_active = {}
STALL_SECONDS = 10


def _write(report, message):
    try:
        report.write(f"{time.monotonic():.6f} thread={threading.get_ident():x} {message}\n".encode())
    except OSError:
        pass


@contextmanager
def stage(name):
    report = _current.get()
    if report is None:
        yield
        return
    _write(report, "BEGIN " + name)
    started = time.monotonic()
    try:
        yield
    except BaseException as exc:
        _write(report, f"ERROR {name} {type(exc).__name__}: {exc}")
        raise
    finally:
        _write(report, f"END {name} elapsed={time.monotonic() - started:.3f}s")


@contextmanager
def operation(directory, name):
    if _current.get() is not None:
        with stage(name):
            yield
        return
    report = None
    try:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        with _lock:
            old = sorted(directory.glob("ocr-*.log"), key=lambda p: p.stat().st_mtime)
            for path in old[:-7]:
                if str(path) not in _active:
                    path.unlink(missing_ok=True)
            path = directory / f"ocr-{time.time_ns()}-{os.getpid()}-{uuid.uuid4().hex[:6]}.log"
            report = path.open("wb", buffering=0)
            _write(report, f"OPERATION {name} pid={os.getpid()} utc={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
            _active[str(path)] = report
            if len(_active) == 1:
                # CPython's watchdog runs even if a native call holds the GIL.
                # One dump bounds disk usage when a call never returns.
                faulthandler.dump_traceback_later(STALL_SECONDS, file=report)
    except OSError:
        if report is not None:
            report.close()
        report = None
    token = _current.set(report)
    try:
        with stage(name):
            yield
    finally:
        _current.reset(token)
        if report is not None:
            with _lock:
                owner = next(iter(_active)) == str(path)
                _active.pop(str(path), None)
                if owner:
                    faulthandler.cancel_dump_traceback_later()
                    if _active:
                        faulthandler.dump_traceback_later(STALL_SECONDS, file=next(iter(_active.values())))
                report.close()


def record_operation(name):
    def decorate(function):
        @wraps(function)
        def wrapped(self, *args, **kwargs):
            with operation(self.trace_directory, name):
                return function(self, *args, **kwargs)
        return wrapped
    return decorate
