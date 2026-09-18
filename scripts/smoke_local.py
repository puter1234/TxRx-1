"""Real loopback HTTP/WebSocket smoke, temporary REPLAY data, no browser."""

import argparse, json, os, re, secrets, socket, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run():
    import httpx
    from websockets.sync.client import connect

    with tempfile.TemporaryDirectory(prefix="txrx-smoke-") as tmp:
        data = Path(tmp)
        config = data / "config.json"
        config.write_text('{"mode":"REPLAY"}')
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        env = {
            **os.environ,
            "TXRX_DATA": str(data / "data"),
            "TXRX_CONFIG": str(config),
        }
        stop_file = data / "stop"
        log = (data / "server.log").open("w", encoding="utf-8")
        process = subprocess.Popen(
            [sys.executable, __file__, "--serve", str(port), str(stop_file)],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        checks = []
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}", timeout=10
            ) as client:
                for _ in range(100):
                    try:
                        if client.get("/api/health/live").status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    if process.poll() is not None:
                        raise RuntimeError("Server exited early")
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Server startup timeout")
                html = client.get("/")
                assert html.status_code == 200
                assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html.text)
                assert assets and all(
                    client.get(path).status_code == 200 for path in assets
                )
                checks.append("production_static_assets")
                assert client.get("/api/status").status_code == 401
                assert client.post("/api/auth/local", json={}).status_code == 200
                assert client.get("/api/status").status_code == 200
                assert (
                    client.put("/api/settings", json={"save_photos": False}).status_code
                    == 403
                )
                assert client.get("/api/users").status_code == 404
                checks.append("main_without_account_and_password_only_settings")
                password = secrets.token_urlsafe(20)
                assert (
                    client.post(
                        "/api/auth/setup", json={"password": password}
                    ).status_code
                    == 200
                )
                brand = {
                    "id": "smoke",
                    "name": "통합 검사",
                    "options": [
                        {"key": k, "label": k, "values": [v]}
                        for k, v in {
                            "style": "HUTS6C612",
                            "color": "N3",
                            "size": "095",
                        }.items()
                    ],
                    "decoder": {"kind": "hazzys_6bit_crc8"},
                }
                result = client.post("/api/brands", json={"brand": brand})
                assert result.status_code == 200, result.text
                saved = result.json()
                color = next(
                    option for option in saved["options"] if option["key"] == "color"
                )
                color.update(display="colors", colors={"N3": "#142B49"})
                result = client.post(
                    "/api/brands",
                    json={"brand": saved, "expected_revision": saved["revision"]},
                )
                assert result.status_code == 200, result.text
                saved = result.json()
                assert client.post("/api/brands/validate", json=saved).json() == saved
                checks.append("display_color_mapping_roundtrip")
                assert client.post("/api/auth/logout", json={}).status_code == 200
                recipe = {
                    "brand_id": "smoke",
                    "brand_revision": saved["revision"],
                    "targets": {"style": "HUTS6C612", "color": "N3", "size": "095"},
                    "channels": ["rfid"],
                }
                result = client.post("/api/sessions", json=recipe)
                assert result.status_code == 200, result.text
                result = client.post(
                    "/api/replay",
                    data={
                        "product_id": "one-product",
                        "epcs": "1D44D280281B70D75A8DF0000E114D7A",
                    },
                )
                assert result.json()["status"] == "PASS", result.text
                assert client.get("/api/status").json()["session"]["count"] == 1
                checks.append("local_rfid_session_counts_once")
                cookie = "; ".join(
                    f"{key}={value}" for key, value in client.cookies.items()
                )
                with connect(
                    f"ws://127.0.0.1:{port}/api/ws",
                    additional_headers={"Cookie": cookie},
                    origin=f"http://127.0.0.1:{port}",
                ) as ws:
                    message = json.loads(ws.recv(timeout=5))
                    assert message["state"]["session"]["count"] == 1
                    ws.send(json.dumps({"type": "heartbeat"}))
                    assert (
                        json.loads(ws.recv(timeout=5))["event_seq"]
                        >= message["event_seq"]
                    )
                checks.append("authenticated_websocket_heartbeat")
                assert client.post("/api/backup", json={}).status_code == 403
                assert (
                    client.post(
                        "/api/auth/login", json={"password": password}
                    ).status_code
                    == 200
                )
                backup = client.post("/api/backup", json={})
                assert backup.status_code == 200, backup.text
                assert client.get(
                    "/api/backups/" + backup.json()["name"]
                ).content.startswith(b"SQLite format 3")
                assert client.get("/api/equipment").json()["io"]["source"] == "REPLAY"
                assert client.get("/api/camera/frame").status_code == 503
                assert not client.post("/api/device/test/sensor", json={}).is_success
                import uuid

                def command(action, reason="제품 상태 확인 완료"):
                    state = client.get("/api/status").json()
                    result = client.post(
                        "/api/commands",
                        json={
                            "request_id": str(uuid.uuid4()),
                            "session_id": state["session"]["id"],
                            "expected_revision": state["revision"],
                            "action": action,
                            "reason": reason,
                        },
                    )
                    assert result.status_code == 200, result.text

                command("release")
                failed = client.post(
                    "/api/replay", data={"product_id": "unread-product"}
                )
                assert failed.json()["status"] == "FAIL"
                assert client.get("/api/status").json()["session"]["phase"] == "HOLD"
                command("reset")
                assert client.get("/api/status").json()["session"]["phase"] == "READY"
                command("finish")
                simple = {
                    "kind": "simple",
                    "brand_id": "__simple__",
                    "brand_revision": 1,
                    "targets": {},
                    "channels": [],
                }
                assert client.post("/api/sessions", json=simple).status_code == 200
                from PIL import Image
                import io

                image = io.BytesIO()
                Image.new("RGB", (8, 8), "white").save(image, format="PNG")
                photo = client.post(
                    "/api/replay",
                    data={"product_id": "simple-product"},
                    files={"image": ("sample.png", image.getvalue(), "image/png")},
                ).json()
                assert photo["status"] == "PASS"
                assert client.get(photo["evidence"]["url"]).status_code == 200
                sid = client.get("/api/status").json()["session"]["id"]
                rows = client.get("/api/history", params={"session_id": sid}).json()[
                    "inspections"
                ]
                assert len(rows) == 1 and rows[0]["id"] == photo["id"]
                command("release")
                assert (
                    client.post(
                        "/api/replay",
                        data={"product_id": "simple-product"},
                        files={"image": ("sample.png", image.getvalue(), "image/png")},
                    ).status_code
                    == 409
                )
                assert client.get("/api/status").json()["session"]["count"] == 1
                checks += [
                    "missing_read_holds_without_auto_resume",
                    "simple_count_evidence_and_duplicate_rejection",
                    "history_filters_actual_session",
                    "disconnected_camera_returns_unavailable",
                ]
                checks += [
                    "backup_download",
                    "equipment_no_fake_hardware",
                    "no_browser_opened",
                ]
        finally:
            stop_file.write_text("stop")
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                import psutil

                children = psutil.Process(process.pid).children(recursive=True)
                for child in children:
                    child.terminate()
                process.terminate()
                psutil.wait_procs(children, timeout=5)
                process.wait(timeout=5)
            log.close()
        return {
            "passed": checks,
            "transport": "real HTTP + WebSocket over loopback",
            "hardware": "NOT_VERIFIED",
            "browser_opened": False,
        }


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        sys.path.insert(0, str(ROOT))
        import uvicorn, threading

        server = uvicorn.Server(
            uvicorn.Config(
                "station.app:create_app",
                factory=True,
                host="127.0.0.1",
                port=int(sys.argv[2]),
                workers=1,
            )
        )

        def watch_stop():
            while not Path(sys.argv[3]).exists():
                time.sleep(0.1)
            server.should_exit = True

        threading.Thread(target=watch_stop, daemon=True).start()
        server.run()
        raise SystemExit(0)
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    result = run()
    body = json.dumps(result, ensure_ascii=False, indent=2)
    print(body)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body, encoding="utf-8")
