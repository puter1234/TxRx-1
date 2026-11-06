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
        # The one setting is edited in place: an older revision still starts on the current one.
        assert client.post("/api/presets/simple/start", json={"preset_revision": 2}).status_code == 200


def preset_raw(ident, kind="vision", revision=1, **extra):
    flow = {"counter": "cvzone"} if kind == "vision" else {}
    channels = ["ocr"] if kind == "condition" else []
    return {**WorkPreset(id=ident, name=ident, kind=kind, flow=flow, channels=channels, **extra).model_dump(), "revision": revision}


def test_several_stored_settings_of_a_kind_or_brand_start_on_one_without_a_choice(tmp_path):
    from station.storage import Store
    Store(tmp_path).put("work_presets", {
        "simple": preset_raw("simple", "simple"),
        "work-a": preset_raw("work-a", revision=3, enabled=False),
        "work-b": preset_raw("work-b", revision=1),
        "work-c": preset_raw("work-c", "condition", brand_id="hazzys"),
        "work-d": preset_raw("work-d", "condition", brand_id="hazzys"),
        "work-e": preset_raw("work-e", "condition", brand_id="other"),
        "work-f": preset_raw("work-f", "simple"),
    })
    app = create_app(tmp_path)
    with TestClient(app) as client:
        enter(client)
        # The highest revision, then the last in stored order; a disabled one is still the one in use.
        assert sorted(p["id"] for p in client.get("/api/presets").json()) == ["work-a", "work-d", "work-e", "work-f"]
        job = client.post("/api/presets/work-b/start", json={"preset_revision": 1})
        assert job.status_code == 200, job.text
        recipe = job.json()["session"]["recipe"]
        # Moved to the YOLO model once at startup, which is one more revision.
        assert (recipe["preset_id"], recipe["preset_revision"], recipe["work_name"]) == ("work-a", 4, "work-a")


def test_wappen_setting_moves_to_the_yolo_model_once(tmp_path):
    from station.storage import Store
    Store(tmp_path).put("work_presets", {"work-a": preset_raw("work-a", revision=2)})
    with TestClient(create_app(tmp_path)) as client:
        enter(client)
        [wappen] = client.get("/api/presets").json()
        assert (wappen["flow"]["counter"], wappen["flow"]["model_path"], wappen["revision"]) == ("yolo", "", 3)
        login(client)
        wappen["flow"]["counter"] = "cvzone"
        assert client.post("/api/presets", json={"preset": wappen, "expected_revision": 3}).status_code == 200
    with TestClient(create_app(tmp_path)) as client:
        enter(client)
        assert client.get("/api/presets").json()[0]["flow"]["counter"] == "cvzone"


def test_wappen_job_ignores_a_target_quantity(tmp_path):
    from station.storage import Store
    Store(tmp_path).put("work_presets", {"work-a": preset_raw("work-a")})
    with TestClient(create_app(tmp_path)) as client:
        enter(client)
        job = client.post("/api/presets/work-a/start", json={"target_count": 40})
        assert job.status_code == 200, job.text
        assert job.json()["session"]["recipe"]["target_count"] is None


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


def test_legacy_ended_job_without_finish_time_does_not_grow_forever(controller):
    store = controller.store
    session = {"id": "old", "created_at": "2026-10-14T01:00:00+00:00", "phase": "FINISHED",
               "recipe": {"targets": {}}, "brand": {"name": "이전 작업"},
               "count": 0, "passed": 0, "failed": 0, "adjustments": 0}
    store.session(session)
    data = report(store, date(2026, 10, 14), date(2026, 10, 16))
    assert data["jobs"][0]["stopped_seconds"] is None
    assert data["jobs"][0]["run_seconds"] is None
    assert data["timing_unknown_jobs"] == 1
    assert {d["date"] for d in data["daily"]} == {"2026-10-14"}
    assert not report(store, date(2026, 10, 15), date(2026, 10, 16))["jobs"]


def test_statistics_count_mismatched_products_consistently_across_job_and_day(controller):
    store = controller.store
    at = "2026-10-14T01:00:00+00:00"
    store.session({"id": "s", "created_at": at, "finished_at": at, "phase": "FINISHED",
                   "recipe": {"targets": {}}, "brand": {"name": "조건 검사"},
                   "count": 0, "passed": 0, "failed": 1, "adjustments": 0})
    inspection = {"id": "i", "session_id": "s", "product_id": "p", "attempt": 1,
                  "created_at": at, "finished_at": at, "status": "FAIL",
                  "failures": [{"code": "TARGET_MISMATCH", "field": "size"},
                               {"code": "TARGET_MISMATCH", "field": "color"}]}
    with store.transaction() as db:
        db.execute("INSERT INTO inspections VALUES(?,?,?,?,?,?,?)",
                   ("i", "s", "p", 1, "FAIL", json.dumps(inspection), at))
    data = report(store, date(2026, 10, 14), date(2026, 10, 14))
    assert data["jobs"][0]["mismatches"] == data["daily"][0]["mismatches"] == 1


def test_wappen_job_brings_its_camera_settings_and_other_jobs_clear_them(controller):
    from types import SimpleNamespace
    from station.schema import Recipe
    from station.work_api import prepare_session
    used = []
    monitor = SimpleNamespace(camera=SimpleNamespace(use=used.append), prepare=lambda r: None, counter=None)
    vision = SimpleNamespace(loading=lambda: False)
    preset = WorkPreset(id="patches", name="와펜", kind="vision", flow={"counter": "cvzone"})
    assert preset.camera.width == 1920 and preset.camera.height == 1080 and preset.camera.fps == 30
    assert WorkPreset(id="plain", name="옷", camera={"width": 640}).camera is None
    controller.store.put("work_presets", {"patches": preset.model_dump()})
    prepare_session(controller, vision, monitor, Recipe(kind="vision", brand_id="__simple__", brand_revision=1,
        targets={}, channels=[], flow={"counter": "cvzone"}, preset_id="patches", preset_revision=1), "test")
    assert used[-1]["width"] == 1920 and controller.session["recipe"]["camera"]["fps"] == 30
    controller.session["phase"] = "FINISHED"
    prepare_session(controller, vision, monitor, Recipe(kind="simple", brand_id="__simple__", brand_revision=1,
        targets={}, channels=[]), "test")
    assert used[-1] is None
