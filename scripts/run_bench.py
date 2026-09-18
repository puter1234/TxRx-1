"""Start component tests without requiring the separate AI environment."""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.chdir(ROOT)
    local_config = ROOT / "runtime/station-local.json"
    default_config = local_config if local_config.is_file() else ROOT / "config/station.json"
    config_path = Path(os.environ.get("TXRX_CONFIG", default_config)).resolve()
    os.environ["TXRX_CONFIG"] = str(config_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("mode") != "REPLAY":
        raise SystemExit("Component tests require REPLAY mode. Production configuration was not changed.")
    python = ROOT / ".venv-bench/bin/python"
    if not python.is_file():
        raise SystemExit("Run python3 scripts/install_bench.py first.")
    print("Open http://127.0.0.1:8000/ on the J4012. Device tests control real hardware.", flush=True)
    os.execv(str(python), [str(python), "-m", "uvicorn", "station.app:create_app",
                         "--factory", "--host", "127.0.0.1", "--port", "8000", "--workers", "1"])


if __name__ == "__main__":
    main()
