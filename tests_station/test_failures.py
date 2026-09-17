import threading
import time
import uuid
from contextlib import contextmanager
import pytest
from station.controller import Conflict
from station.schema import Command
from station.devices import LeaseGuard
from test_controller import execute, command


def test_database_commit_failure_never_increments_memory_count(
    controller, recipe, monkeypatch
):
    c = controller
    c.new_session(recipe)
    i, e, _ = c.begin("p1")
    c.inspecting(e)
    original = c.store.transaction

    @contextmanager
    def failing():
        with original() as conn:
            yield conn
            raise OSError("disk full at commit")

    monkeypatch.setattr(c.store, "transaction", failing)
    with pytest.raises(OSError):
        c.complete(i, e, {"rfid": recipe.targets})
    assert c.session["count"] == 0 and c.session["phase"] == "FAULT"
    assert c.store.conn.execute("SELECT COUNT(*) FROM counts").fetchone()[0] == 0


def test_discard_does_not_convert_failed_item_to_pass(controller, recipe):
    c = controller
    c.new_session(recipe)
    execute(c, recipe, observations={})
    c.command(command(c, "discard"), "operator")
    assert c.session["active_product"] is None and c.session["count"] == 0
    assert c.store.inspection_rows()[0]["status"] == "FAIL"
    execute(c, recipe, "next-product")
    assert c.session["count"] == 1


def test_expired_or_old_revision_start_cannot_energize(controller, recipe):
    c = controller
    c.config.mode = "HARDWARE"
    c.new_session(recipe)
    cmd = command(c, "start")
    cmd.issued_at = time.time() - 10
    with pytest.raises(Conflict, match="만료"):
        c.command(cmd, "test")
    cmd = command(c, "start")
    cmd.expected_revision = 0
    with pytest.raises(Conflict, match="변경"):
        c.command(cmd, "test")


def test_stop_invalidates_an_already_admitted_motor_command(controller, recipe):
    c = controller
    c.new_session(recipe)
    generation = c.stop_serial
    c.command(command(c, "stop"), "operator")
    with pytest.raises(Conflict, match="정지 요청"):
        c._motor_on(generation)


def test_lease_guard_stops_without_controller_progress():
    class IO:
        def __init__(self):
            self.stopped = threading.Event()

        def stop(self):
            self.stopped.set()

    io = IO()
    guard = LeaseGuard(io, 100)
    try:
        assert io.stopped.wait(1)
    finally:
        guard.close()
