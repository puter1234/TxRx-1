import uuid
import pytest
from fastapi.testclient import TestClient
from station.app import create_app
from station.schema import Recipe
from test_api import login
from test_controller import execute


def enter(client):
    response = client.post("/api/auth/local", json={})
    assert response.status_code == 200
    assert "txrx_session" in response.cookies


def test_local_work_entry_and_password_locked_settings(tmp_path, brand, recipe):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/status").status_code == 401
        assert (
            client.post(
                "/api/auth/local",
                json={},
                headers={"Origin": "https://outside.example"},
            ).status_code
            == 403
        )
        enter(client)
        assert client.get("/api/status").status_code == 200
        assert app.state.store.get("users") is None
        assert (
            client.post("/api/brands", json={"brand": brand.model_dump()}).status_code
            == 403
        )
        assert client.post("/api/backup", json={}).status_code == 403
        assert client.get("/api/camera/frame").status_code == 503
        assert client.get("/api/users").status_code == 404
        login(client)
        changed = brand.model_copy(update={"id": "additional"})
        assert (
            client.post("/api/brands", json={"brand": changed.model_dump()}).status_code
            == 200
        )
        client.post("/api/auth/logout", json={})
        assert client.get("/api/status").status_code == 200
        assert (
            client.post("/api/brands", json={"brand": changed.model_dump()}).status_code
            == 403
        )
        assert (
            client.post("/api/auth/login", json={"password": "wrong-pass"}).status_code
            == 422
        )
        assert (
            client.post(
                "/api/auth/login", json={"password": "testing-only-123"}
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/auth/password",
                json={"current": "wrong-pass", "next": "new-password"},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/auth/password",
                json={"current": "testing-only-123", "next": "new-password"},
            ).status_code
            == 200
        )
        client.post("/api/auth/logout", json={})
        assert (
            client.post(
                "/api/auth/login", json={"password": "testing-only-123"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/auth/login", json={"password": "new-password"}
            ).status_code
            == 200
        )


def test_work_recovery_and_adjustment_need_no_extra_account(tmp_path, brand, recipe):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        enter(client)
        if not app.state.store.brands():
            app.state.store.save_brand(brand.model_dump(), None, "test")
        status = client.post("/api/sessions", json=recipe.model_dump()).json()
        sid = status["session"]["id"]
        client.post("/api/replay", data={"product_id": "test1"})
        status = client.get("/api/status").json()
        assert status["session"]["phase"] == "HOLD"
        body = {
            "request_id": str(uuid.uuid4()),
            "session_id": sid,
            "action": "reset",
            "expected_revision": status["revision"],
            "reason": "",
        }
        assert client.post("/api/commands", json=body).status_code == 409
        body["reason"] = "제품 상태 확인"
        assert client.post("/api/commands", json=body).status_code == 200
        assert client.get("/api/status").json()["session"]["phase"] == "READY"
        assert (
            client.post(
                "/api/adjustments",
                json={
                    "request_id": str(uuid.uuid4()),
                    "session_id": sid,
                    "delta": 1,
                    "reason": "수량 실측 확인",
                },
            ).status_code
            == 200
        )
        # Closing settings must not stop or restart the work screen.
        client.post("/api/auth/logout", json={})
        assert client.get("/api/status").json()["session"]["phase"] == "READY"


def test_local_websocket_snapshots_and_heartbeat(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        enter(client)
        with client.websocket_connect("/api/ws") as ws:
            payload = ws.receive_json()
            assert payload["state"]["can_start"] is False
            assert payload["state"]["observed_at"]
            ws.send_json({"type": "heartbeat"})
            assert ws.receive_json()["state"]["boot_id"] == payload["state"]["boot_id"]


def test_simple_count_once_and_condition_validation_not_bypassed(controller):
    from station.controller import Conflict
    from test_controller import command

    recipe = Recipe(
        kind="simple", brand_id="__simple__", brand_revision=1, targets={}, channels=[]
    )
    c = controller
    c.new_session(recipe)
    assert c.session["brand"]["name"] == "단순 계수"
    assert execute(c, recipe, observations={})["status"] == "PASS"
    assert c.session["count"] == 1
    c.command(command(c, "release"), "test")
    with pytest.raises(Conflict, match="이미 계수"):
        c.begin("p1")
    with pytest.raises(ValueError):
        Recipe(brand_id="hazzys", brand_revision=1, targets={}, channels=[])
    with pytest.raises(ValueError):
        Recipe(
            kind="simple",
            brand_id="__simple__",
            brand_revision=1,
            targets={"size": "100"},
            channels=["ocr"],
        )


def test_simple_replay_requires_photo_and_hardware_keeps_interlocks(tmp_path):
    from station.schema import StationConfig
    from station.devices import ReplayIO
    from station.controller import Controller, Conflict
    from station.storage import Store
    from test_controller import command

    recipe = Recipe(
        kind="simple", brand_id="__simple__", brand_revision=1, targets={}, channels=[]
    )
    with TestClient(create_app(tmp_path / "replay")) as client:
        enter(client)
        assert client.post("/api/sessions", json=recipe.model_dump()).status_code == 200
        result = client.post("/api/replay", data={"product_id": "no-photo"}).json()
        assert result["status"] == "FAIL"
        assert any(f["code"] == "IMAGE_MISSING" for f in result["failures"])
    store = Store(tmp_path / "hardware")
    try:
        c = Controller(store, ReplayIO(), StationConfig(mode="HARDWARE"))
        c.new_session(recipe)
        assert not c.snapshot()["can_start"]
        with pytest.raises(Conflict):
            c.command(command(c, "start"), "test")
        assert not c.io.motor_requested
    finally:
        store.close()


def test_archive_restore_preserves_evidence_and_counts(controller, recipe, tmp_path):
    from scripts.archive_data import archive, restore
    import sqlite3

    c = controller
    c.new_session(recipe)
    execute(c, recipe)
    directory = c.store.root / "evidence"
    directory.mkdir()
    (directory / "test.png").write_bytes(b"private evidence fixture")
    path = tmp_path / "archive.zip"
    archive(c.store.root, path)
    target = tmp_path / "restored"
    restore(path, target)
    assert (target / "evidence/test.png").read_bytes() == b"private evidence fixture"
    with sqlite3.connect(target / "station.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM counts").fetchone()[0] == 1


def test_pass_photo_policy_retains_failures_and_filtered_history(tmp_path, recipe):
    from PIL import Image
    from io import BytesIO
    from test_api import EPC
    from test_controller import command

    app = create_app(tmp_path)
    photo = BytesIO()
    Image.new("RGB", (8, 8), "white").save(photo, format="PNG")
    with TestClient(app) as client:
        enter(client)
        assert (
            client.put("/api/settings", json={"save_photos": False}).status_code == 403
        )
        login(client)
        assert (
            client.put("/api/settings", json={"save_photos": False}).json()[
                "save_photos"
            ]
            is False
        )
        client.post("/api/sessions", json=recipe.model_dump())
        sid = client.get("/api/status").json()["session"]["id"]
        assert (
            client.put("/api/settings", json={"save_photos": True}).status_code == 409
        )
        result = client.post(
            "/api/replay",
            data={"product_id": "passed", "epcs": EPC},
            files={"image": ("test.png", photo.getvalue(), "image/png")},
        ).json()
        assert result["status"] == "PASS"
        assert result["evidence"]["retained"] is False
        assert "url" not in result["evidence"]
        assert not list((tmp_path / "evidence").glob(result["id"] + ".*"))
        c = app.state.controller
        c.command(command(c, "release"), "test")
        result = client.post(
            "/api/replay",
            data={"product_id": "failed"},
            files={"image": ("test.png", photo.getvalue(), "image/png")},
        ).json()
        assert result["status"] == "FAIL"
        assert client.get(result["evidence"]["url"]).status_code == 200
        rows = client.get("/api/history", params={"session_id": sid}).json()[
            "inspections"
        ]
        assert {row["product_id"] for row in rows} == {"passed", "failed"}
        assert (
            len(
                client.get(
                    "/api/history", params={"session_id": sid, "offset": 1}
                ).json()["inspections"]
            )
            == 1
        )
        assert (
            client.get("/api/history", params={"session_id": "other"}).json()[
                "inspections"
            ]
            == []
        )
        assert client.get("/api/history?offset=-1").status_code == 422


def test_simple_photo_counts_once_and_uncertain_repeat_cannot_add(tmp_path):
    from PIL import Image
    from io import BytesIO
    from test_controller import command

    app = create_app(tmp_path)
    photo = BytesIO()
    Image.new("RGB", (8, 8), "white").save(photo, format="PNG")
    recipe = Recipe(
        kind="simple", brand_id="__simple__", brand_revision=1, targets={}, channels=[]
    )
    with TestClient(app) as client:
        enter(client)
        client.post("/api/sessions", json=recipe.model_dump())
        upload = lambda: client.post(
            "/api/replay",
            data={"product_id": "single-product"},
            files={"image": ("test.png", photo.getvalue(), "image/png")},
        )
        assert upload().json()["status"] == "PASS"
        assert upload().status_code == 409
        c = app.state.controller
        c.command(command(c, "release"), "test")
        assert upload().status_code == 409
        assert client.get("/api/status").json()["session"]["count"] == 1
        assert len(client.get("/api/history").json()["inspections"]) == 1


def test_native_device_check_blocks_work_until_worker_releases(tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    entered, release = threading.Event(), threading.Event()

    class SlowVision:
        def load(self):
            entered.set()
            assert release.wait(5)

        def status(self):
            return {"loaded": release.is_set(), "busy": False}

    app = create_app(tmp_path, vision=SlowVision())
    recipe = Recipe(
        kind="simple", brand_id="__simple__", brand_revision=1, targets={}, channels=[]
    )
    with TestClient(app) as client, ThreadPoolExecutor() as pool:
        enter(client)
        request = pool.submit(client.post, "/api/device/test/ocr", json={})
        try:
            assert entered.wait(3)
            assert client.post("/api/device/test/sensor", json={}).status_code == 409
            assert (
                client.post("/api/sessions", json=recipe.model_dump()).status_code
                == 409
            )
            assert not app.state.controller.io.motor_requested
        finally:
            release.set()
        assert request.result(timeout=3).json()["ok"]
        assert client.post("/api/sessions", json=recipe.model_dump()).status_code == 200
        assert client.post("/api/device/test/sensor", json={}).status_code == 409


def test_event_history_dates_and_cursor_do_not_hide_older_work(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        enter(client)
        with app.state.store.transaction() as c:
            for index in range(205):
                c.execute(
                    "INSERT INTO events(kind,created_at,body) VALUES(?,?,?)",
                    ("TEST", "2020-01-01T15:00:00+00:00", "{}"),
                )
        params = {
            "since": "2020-01-02T00:00:00+09:00",
            "until": "2020-01-03T00:00:00+09:00",
        }
        rows = client.get("/api/event-history", params=params).json()["events"]
        assert len(rows) == 200
        second = client.get(
            "/api/event-history", params={**params, "before_seq": rows[-1]["seq"]}
        ).json()["events"]
        assert len(second) == 5 and second[0]["seq"] < rows[-1]["seq"]
        assert (
            client.get(
                "/api/event-history",
                params={"since": "2020-01-01", "until": "2020-01-02"},
            ).status_code
            == 422
        )
