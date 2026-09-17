import uuid
from fastapi.testclient import TestClient
from station.app import create_app
from test_api import login


def test_role_boundary_and_last_admin(tmp_path, brand, recipe):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        login(client)
        for role in ("operator", "engineer"):
            r = client.post(
                "/api/users",
                json={
                    "username": role,
                    "role": role,
                    "password": "testing-123",
                    "reason": "현장 계정 생성",
                },
            )
            assert r.status_code == 200, r.text
        assert (
            client.post(
                "/api/users",
                json={
                    "username": "admin",
                    "role": "operator",
                    "reason": "마지막 관리자 변경",
                },
            ).status_code
            == 422
        )
        for role in ("operator", "engineer"):
            client.post(
                "/api/auth/login", json={"username": role, "password": "testing-123"}
            )
            assert client.get("/api/auth").json()["user"]["role"] == role
            assert client.get("/api/users").status_code == 403
            assert client.post("/api/backup", json={}).status_code == 403
            row = brand.model_copy(update={"id": "new-maker"})
            assert client.post(
                "/api/brands", json={"brand": row.model_dump()}
            ).status_code in (403, 404)
        client.post(
            "/api/auth/login", json={"username": "operator", "password": "testing-123"}
        )
        if not app.state.store.brands():
            app.state.store.save_brand(brand.model_dump(), None, "test")
        status = client.post("/api/sessions", json=recipe.model_dump()).json()
        sid = status["session"]["id"]
        body = {
            "request_id": str(uuid.uuid4()),
            "session_id": sid,
            "action": "reset",
            "expected_revision": status["revision"],
            "reason": "조치 확인 완료",
        }
        assert client.post("/api/commands", json=body).status_code == 403
        body["action"] = "stop"
        assert client.post("/api/commands", json=body).status_code == 200
        assert (
            client.post(
                "/api/adjustments",
                json={
                    "request_id": str(uuid.uuid4()),
                    "session_id": sid,
                    "delta": 1,
                    "reason": "수량 보정 확인",
                },
            ).status_code
            == 403
        )
        assert not client.get("/api/status").json()["can_start"] is None


def test_authenticated_websocket_snapshots_and_heartbeat(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        login(client)
        with client.websocket_connect("/api/ws") as ws:
            payload = ws.receive_json()
            assert payload["event_seq"] > 0
            assert payload["state"]["can_start"] is False
            assert payload["state"]["observed_at"]
            ws.send_json({"type": "heartbeat"})
            assert ws.receive_json()["state"]["boot_id"] == payload["state"]["boot_id"]


def test_archive_restore_preserves_evidence_and_counts(controller, recipe, tmp_path):
    from scripts.archive_data import archive, restore
    from test_controller import execute
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
