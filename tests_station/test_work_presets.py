from datetime import date
import json
import pytest
from fastapi.testclient import TestClient
from station.app import create_app
from station.schema import WorkPreset
from station.statistics import report, csv_bytes
from test_api import login
from test_roles_stream import enter


def test_presets_are_admin_owned_versioned_and_frozen_in_job(tmp_path, brand):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        enter(client)
        preset = WorkPreset(id="patches", name="와펜", kind="vision", flow={"counter": "cvzone"})
        assert client.post("/api/presets", json={"preset": preset.model_dump()}).status_code == 403
        login(client)
        saved = client.post("/api/presets", json={"preset": preset.model_dump()})
        assert saved.status_code == 200, saved.text
        job = client.post("/api/presets/patches/start", json={"preset_revision": 1})
        assert job.status_code == 200, job.text
        assert job.json()["session"]["recipe"]["flow"]["counter"] == "cvzone"
        changed = saved.json()
        changed["flow"]["capture_delay_ms"] = 200
        assert client.post("/api/presets", json={"preset": changed, "expected_revision": 1}).status_code == 200
        assert client.get("/api/status").json()["session"]["recipe"]["flow"]["capture_delay_ms"] == 100
        assert client.post("/api/presets", json={"preset": changed, "expected_revision": 1}).status_code == 409


def test_operator_cannot_override_preset_algorithm_or_run_test(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        enter(client)
        assert client.post("/api/presets/simple/start", json={"preset_revision": 1, "flow": {"counter": "yolo"}}).status_code == 422
        assert client.post("/api/presets/simple/start", json={"preset_revision": 1, "test_run": True}).status_code == 403
        assert client.post("/api/presets/simple/start", json={"preset_revision": 2}).status_code == 409
        assert client.post("/api/presets/simple/start", json={"preset_revision": 1}).status_code == 200


def test_statistics_split_midnight_seoul_and_export_all_rows(controller):
    store = controller.store
    session = {"id": "s", "created_at": "2026-10-14T14:59:00+00:00", "finished_at": "2026-10-14T15:01:00+00:00", "phase": "FINISHED", "recipe": {"targets": {}, "work_name": "=SUM(A1)"}, "brand": {"name": "브랜드"}, "count": 1, "passed": 1, "failed": 0, "adjustments": 0}
    store.session(session)
    with store.transaction() as db:
        for at, kind, body in [("2026-10-14T14:59:00+00:00", "COMMAND", {"session_id": "s", "phase": "FEEDING"}), ("2026-10-14T15:00:30+00:00", "DI2_DETECTED", {"session_id": "s"}), ("2026-10-14T15:01:00+00:00", "COMMAND", {"session_id": "s", "phase": "FINISHED"})]:
            db.execute("INSERT INTO events(kind,created_at,body) VALUES(?,?,?)", (kind, at, json.dumps(body)))
        body = {"id": "i", "session_id": "s", "product_id": "p", "created_at": "2026-10-14T14:59:30+00:00", "finished_at": "2026-10-14T15:00:30+00:00", "status": "PASS", "attempt": 1, "elapsed_ms": 1000}
        db.execute("INSERT INTO inspections VALUES(?,?,?,?,?,?,?)", ("i", "s", "p", 1, "PASS", json.dumps(body), body["created_at"]))
    data = report(store, date(2026,10,14), date(2026,10,15))
    days = {d["date"]: d for d in data["daily"]}
    assert days["2026-10-14"]["run_seconds"] == 60
    assert days["2026-10-15"]["run_seconds"] == 60
    assert days["2026-10-14"]["count"] == 0 and days["2026-10-15"]["count"] == 1
    assert days["2026-10-15"]["di2"] == 1
    assert "'=SUM(A1)" in csv_bytes(data["jobs"]).decode("utf-8-sig")
    session["recipe"]["test_run"] = True
    store.session(session)
    assert not report(store, date(2026,10,14), date(2026,10,15))["jobs"]
    assert report(store, date(2026,10,14), date(2026,10,15), True)["jobs"]
