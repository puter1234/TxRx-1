"""Install the ARM64 component-test environment from bundled wheels only."""

import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from verify_release import verify

ROOT = Path(__file__).resolve().parents[1]


def main():
    if platform.system() != "Linux" or platform.machine() != "aarch64":
        raise SystemExit("This installer requires the J4012 Linux ARM64 environment.")
    if sys.version_info[:2] != (3, 10):
        raise SystemExit("Run with Python 3.10.")
    if os.geteuid() == 0:
        raise SystemExit("Run without sudo. Only setup_jetson_access.py needs sudo.")
    if not importlib.util.find_spec("ensurepip") or not shutil.which("v4l2-ctl"):
        raise SystemExit("Install Ubuntu prerequisites: sudo apt install python3.10-venv v4l-utils")
    print(verify(ROOT, allow_source=True), flush=True)
    env = ROOT / ".venv-bench"
    marker = env / ".txrx-bench-environment"
    if env.exists() and not marker.is_file():
        raise SystemExit(".venv-bench already exists without a TXRX marker. Use a fresh app folder.")
    subprocess.run([sys.executable, "-m", "venv", str(env)], check=True)
    marker.write_text("J4012 component tests, Python 3.10 ARM64\n", encoding="utf-8")
    python = str(env / "bin/python")
    subprocess.run(
        [python, "-m", "pip", "install", "--no-index", "--require-hashes",
         "--find-links", str(ROOT / "wheelhouse"), "-r",
         str(ROOT / "deploy/requirements-bench-arm64.lock")], check=True,
    )
    subprocess.run([python, "-m", "pip", "check"], check=True)
    subprocess.run(
        [python, "-c", "import fastapi, uvicorn, cv2, numpy, serial, gpiod; "
         "assert hasattr(gpiod, 'request_lines'), 'gpiod 2.x API missing'; "
         "assert cv2.videoio_registry.hasBackend(cv2.CAP_V4L2), 'V4L2 backend missing'; "
         "print('Component dependencies ready. Hardware has not been opened.')"],
        check=True,
    )
    print("Start with: python3 scripts/run_bench.py", flush=True)


if __name__ == "__main__":
    main()
