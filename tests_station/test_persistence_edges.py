from fastapi.testclient import TestClient
from station.app import create_app
from test_api import login


def test_deleted_seed_stays_deleted_after_restart(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        login(client)
        for b in client.get("/api/brands").json():
            assert (
                client.delete(
                    f'/api/brands/{b["id"]}?revision={b["revision"]}'
                ).status_code
                == 200
            )
    with TestClient(create_app(tmp_path)) as client:
        client.post("/api/auth/login", json={"password": "testing-only-123"})
        assert client.get("/api/brands").json() == []


def test_recreated_brand_keeps_revision_history(controller, brand):
    store = controller.store
    store.delete_brand(brand.id, 1, "test")
    assert store.save_brand(brand.model_dump(), None, "test")["revision"] == 2
    assert store.conn.execute("SELECT COUNT(*) FROM brand_revisions").fetchone()[0] == 2


def test_daily_backup_once_per_day(controller):
    assert controller.store.daily_backup() is not None
    assert controller.store.daily_backup() is None
    assert len(list((controller.store.root / "backups").glob("*.sqlite3"))) == 1


def test_only_one_server_owns_data_directory(tmp_path):
    import pytest
    from station.storage import Store

    first = Store(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="이미 실행"):
            Store(tmp_path)
    finally:
        first.close()
    reopened = Store(tmp_path)
    reopened.close()
