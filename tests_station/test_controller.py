import uuid
import time
import pytest
from station.schema import Command, Adjustment, StationConfig
from station.controller import Controller, Conflict
from station.devices import ReplayIO


def command(c, action, reason="작업자 확인 완료", request_id=None):
    return Command(
        request_id=request_id or str(uuid.uuid4()),
        session_id=c.session["id"],
        action=action,
        reason=reason,
        expected_revision=c.revision,
        issued_at=time.time(),
    )


def execute(c, recipe, product="p1", observations=None):
    inspection, epoch, _ = c.begin(product)
    assert c.session["phase"] == "STOPPING"
    c.inspecting(epoch)
    return c.complete(
        inspection,
        epoch,
        observations if observations is not None else {"rfid": recipe.targets},
    )


def test_one_product_counts_once(controller, recipe):
    c = controller
    c.new_session(recipe)
    assert execute(c, recipe)["status"] == "PASS"
    assert c.session["count"] == 1 and c.session["phase"] == "PASSED"
    c.command(command(c, "release"), "test")
    with pytest.raises(Conflict, match="이미 계수"):
        c.begin("p1")
    assert c.session["count"] == 1


def test_failure_latches_stop_until_explicit_reset(controller, recipe):
    c = controller
    c.new_session(recipe)
    assert execute(c, recipe, observations={})["status"] == "FAIL"
    assert c.session["phase"] == "HOLD" and c.session["count"] == 0
    c.command(command(c, "stop"), "test")
    assert c.session["phase"] == "HOLD"
    with pytest.raises(Conflict):
        c.command(command(c, "start"), "test")
    with pytest.raises(Conflict):
        c.command(command(c, "release"), "test")
    c.command(command(c, "reset"), "test")
    assert c.session["phase"] == "READY"
    assert execute(c, recipe)["attempt"] == 2
    assert c.session["count"] == 1


def test_cancel_inference_late_result_never_counts(controller, recipe):
    c = controller
    c.new_session(recipe)
    inspection, epoch, _ = c.begin("p1")
    c.inspecting(epoch)
    c.command(command(c, "stop"), "test")
    result = c.complete(inspection, epoch, {"rfid": recipe.targets})
    assert result["status"] == "ABORTED"
    assert c.session["count"] == 0 and c.session["phase"] == "PAUSED"


def test_idempotent_commands_and_adjustment_audit(controller, recipe):
    c = controller
    c.new_session(recipe)
    cmd = command(c, "pause")
    c.command(cmd, "operator")
    assert c.command(cmd, "operator")["duplicate"]
    cmd.action = "start"
    with pytest.raises(ValueError):
        c.command(cmd, "operator")
    adjust = Adjustment(
        request_id=str(uuid.uuid4()),
        session_id=c.session["id"],
        delta=2,
        reason="실제 수량 대조",
    )
    c.adjust(adjust, "operator")
    c.adjust(adjust, "operator")
    assert c.session["count"] == 2
    assert len([e for e in c.store.events() if e["kind"] == "MANUAL_ADJUSTMENT"]) == 1


def test_target_reached_after_departure(controller, recipe):
    recipe.target_count = 1
    c = controller
    c.new_session(recipe)
    execute(c, recipe)
    assert c.session["phase"] == "PASSED"
    c.command(command(c, "release"), "test")
    assert c.session["phase"] == "DONE"


def test_restart_aborts_pending_and_does_not_autostart(controller, recipe):
    c = controller
    c.new_session(recipe)
    c.begin("p1")
    restored = Controller(c.store, ReplayIO(), StationConfig())
    assert restored.session["phase"] == "ABORTED"
    assert restored.session["count"] == 0
    assert restored.store.inspection_rows()[0]["status"] == "ABORTED"


def test_snapshot_recipe_does_not_change_when_catalog_changes(controller, recipe):
    c = controller
    c.new_session(recipe)
    b = c.store.brand("hazzys")
    b["options"][0]["values"] = ["OTHER"]
    c.store.save_brand(b, 1, "test")
    assert c.session["brand"]["options"][0]["values"] == ["HUTS6C612"]


def test_two_products_cannot_overlap(controller, recipe):
    c = controller
    c.new_session(recipe)
    c.begin("p1")
    with pytest.raises(Conflict):
        c.begin("p2")


def test_hardware_not_enabled_by_mode_flag(controller, recipe):
    c = controller
    c.config.mode = "HARDWARE"
    c.new_session(recipe)
    with pytest.raises(Conflict, match="현장 확인"):
        c.command(command(c, "start"), "test")
    with pytest.raises(Conflict):
        c.begin("manual-upload")


def test_backup_integrity(controller, recipe):
    import sqlite3

    c = controller
    c.new_session(recipe)
    execute(c, recipe)
    backup = c.store.backup()
    with sqlite3.connect(c.store.root / "backups" / backup["name"]) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM counts").fetchone()[0] == 1
