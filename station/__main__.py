import argparse
import uvicorn


def main():
    parser = argparse.ArgumentParser(description="TXRX offline single-station server")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    from scripts.doctor import inspect

    report = inspect()
    if not report["software_ready"]:
        import json

        raise SystemExit("Preflight failed: " + json.dumps(report, ensure_ascii=False))
    # One process owns controller/SQLite/I/O. No --reload or multi-worker production.
    uvicorn.run(
        "station.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=args.port,
        workers=1,
        ws_max_size=65536,
    )


if __name__ == "__main__":
    main()
