import uuid
from fastapi.testclient import TestClient
from station.app import create_app

EPC = "1D44D280281B70D75A8DF0000E114D7A"


def login(client):
    r = client.post("/api/auth/setup", json={"password": "testing-only-123"})
    assert r.status_code == 200, r.text


def test_auth_and_same_origin_boundary(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/status").status_code == 401
        assert (
            client.post(
                "/api/auth/setup",
                json={"password": "123456"},
                headers={"Origin": "http://evil.example"},
            ).status_code
            == 403
        )
        login(client)
        assert client.get("/api/status").status_code == 200
        assert (
            client.get("/api/status", headers={"Host": "evil.example"}).status_code
            == 403
        )
        assert client.get("/api/missing").status_code == 404


def test_chunked_json_request_is_bounded(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        login(client)
        response = client.post(
            "/api/brands/validate",
            content=iter([b" " * 1024 * 1024 for _ in range(23)]),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 413


def test_api_rfid_workflow_missing_stop_and_manual_adjust(tmp_path, brand, recipe):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        login(client)
        # User dataset seed may exist; use its actual revision/catalog or fixture.
        if not app.state.store.brands():
            app.state.store.save_brand(brand.model_dump(), None, "test")
        r = client.post("/api/sessions", json=recipe.model_dump())
        assert r.status_code == 200, r.text
        sid = r.json()["session"]["id"]
        result = client.post(
            "/api/replay", data={"product_id": "product-1", "epcs": EPC}
        )
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "PASS"
        status = client.get("/api/status").json()
        assert status["session"]["count"] == 1
        command = {
            "request_id": str(uuid.uuid4()),
            "session_id": sid,
            "action": "release",
            "expected_revision": status["revision"],
        }
        assert client.post("/api/commands", json=command).status_code == 200
        fail = client.post(
            "/api/replay", data={"product_id": "product-2", "epcs": ""}
        ).json()
        assert (
            fail["status"] == "FAIL" and fail["failures"][0]["code"] == "RFID_MISSING"
        )
        assert client.get("/api/status").json()["session"]["phase"] == "HOLD"
        assert (
            client.post(
                "/api/adjustments",
                json={
                    "request_id": str(uuid.uuid4()),
                    "session_id": sid,
                    "delta": -1,
                    "reason": "수량 실측 보정",
                },
            ).status_code
            == 200
        )
        assert len(client.get("/api/history").json()["inspections"]) == 2
        assert (
            client.post(
                "/api/brands",
                json={"brand": brand.model_dump(), "expected_revision": 1},
            ).status_code
            == 409
        )


def test_schema_and_maker_crud_without_internet(tmp_path, monkeypatch, brand):
    import socket

    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network forbidden")),
    )
    with TestClient(create_app(tmp_path)) as client:
        login(client)
        b = brand.model_copy(update={"id": "other"})
        r = client.post("/api/brands", json={"brand": b.model_dump()})
        assert r.status_code == 200, r.text
        b = r.json()
        b["options"][2]["values"].append("110")
        assert (
            client.post(
                "/api/brands", json={"brand": b, "expected_revision": 1}
            ).json()["revision"]
            == 2
        )
        assert (
            client.post(
                "/api/brands", json={"brand": b, "expected_revision": 1}
            ).status_code
            == 422
        )
        assert client.delete("/api/brands/other?revision=2").status_code == 200
        assert client.get("/api/health/ready").json()["hardware_ready"] is False
