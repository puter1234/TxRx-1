"""Start the J4012 station with its own settings in runtime/station-local.json."""

import json
import os
import subprocess
import sys
from pathlib import Path

from jetson_ocr_env import cusparselt_environment

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.chdir(ROOT)
    local_config = ROOT / "runtime/station-local.json"
    default_config = local_config if local_config.is_file() else ROOT / "config/station.json"
    config_path = Path(os.environ.get("TXRX_CONFIG", default_config)).resolve()
    os.environ["TXRX_CONFIG"] = str(config_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    marker = ROOT / "runtime/production-mode"
    if config_path == local_config.resolve() and config.get("mode") == "REPLAY" and not marker.exists():
        # The device copy was made while the bench ran photo tests only. Move it
        # to the real board once; a later switch back to REPLAY stays.
        config["mode"] = "HARDWARE"
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        marker.write_text("HARDWARE\n", encoding="utf-8")
    print("Mode: " + config.get("mode", "REPLAY") + " (" + str(config_path) + ")", flush=True)
    python = ROOT / ".venv-bench/bin/python"
    if not python.is_file():
        raise SystemExit("Run python3 scripts/install_bench.py first.")
    pillow = subprocess.run([str(python), "-c", "from PIL import Image"],
                            capture_output=True, text=True)
    if pillow.returncode:
        raise SystemExit("Pillow is missing from .venv-bench. Run: python3 scripts/install_bench.py")
    print("Open the screen with ./open-screen.sh on the J4012. Jobs and device tests control real hardware.", flush=True)
    os.execve(str(python), [str(python), "-m", "uvicorn", "station.app:create_app",
                           "--factory", "--host", "127.0.0.1", "--port", "8000", "--workers", "1"],
              cusparselt_environment(python.parent.parent))


if __name__ == "__main__":
    main()
