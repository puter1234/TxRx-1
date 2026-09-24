"""Install and verify the complete local PARSeq runtime on JetPack 6.1.

Run on the J4012 after scripts/install_bench.py. Downloads happen only here;
the camera test and production inference never access the network.
"""

from __future__ import annotations

import hashlib
import ctypes
import os
import platform
import subprocess
import sys
import urllib.request
from pathlib import Path

from jetson_ocr_env import cusparselt_environment


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv-bench/bin/python"
WHEELS = ROOT / "runtime/jetson-ai-wheels"

# Matching wheels in the current NVIDIA Jetson AI Lab JP6 / CUDA 12.6 index.
# Exact URLs and hashes were checked against its simple index.
PACKAGES = (
    (
        "torch-2.8.0-cp310-cp310-linux_aarch64.whl",
        "62a1beee9f2f147076a974d2942c90060c12771c94740830327cae705b2595fc",
        "https://pypi.jetson-ai-lab.io/jp6/cu126/+f/62a/1beee9f2f1470/torch-2.8.0-cp310-cp310-linux_aarch64.whl",
    ),
    (
        "torchvision-0.23.0-cp310-cp310-linux_aarch64.whl",
        "907c4c1933789645ebb20dd9181d40f8647978e6bd30086ae7b01febb937d2d1",
        "https://pypi.jetson-ai-lab.io/jp6/cu126/+f/907/c4c1933789645/torchvision-0.23.0-cp310-cp310-linux_aarch64.whl",
    ),
)


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def fetch(name: str, expected: str, url: str) -> Path:
    WHEELS.mkdir(parents=True, exist_ok=True)
    target = WHEELS / name
    if target.is_file() and digest(target) == expected:
        print("Verified cached wheel:", name, flush=True)
        return target
    partial = WHEELS / (name + ".part")
    partial.unlink(missing_ok=True)
    print("Downloading:", name, flush=True)
    try:
        with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as output:
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                output.write(chunk)
        if digest(partial) != expected:
            raise RuntimeError("Wheel SHA256 mismatch: " + name)
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def has_library(name: str) -> bool:
    try:
        ctypes.CDLL(name)
        return True
    except OSError:
        return False


def install_system_libraries() -> None:
    if has_library("libopenblas.so.0"):
        return
    run("sudo", "apt-get", "update")
    run("sudo", "apt-get", "install", "-y", "libopenblas-dev")
    if not has_library("libopenblas.so.0"):
        raise RuntimeError("OpenBLAS is still missing after installation.")


def main() -> None:
    if platform.system() != "Linux" or platform.machine() != "aarch64":
        raise SystemExit("Run this installer on the J4012, not on Windows.")
    if sys.version_info[:2] != (3, 10):
        raise SystemExit("Python 3.10 is required.")
    if not PYTHON.is_file():
        raise SystemExit("Run python3 scripts/install_bench.py first.")
    release = Path("/etc/nv_tegra_release")
    if not release.is_file() or "R36" not in release.read_text(errors="replace"):
        raise SystemExit("This installer is for Jetson Linux R36 / JetPack 6.1 only.")
    if os.geteuid() == 0:
        raise SystemExit("Run without sudo; only OpenBLAS installation may use sudo.")

    install_system_libraries()
    run(str(PYTHON), "-m", "pip", "install", "--no-cache-dir", "nvidia-cusparselt-cu12==0.8.1")
    ocr_env = cusparselt_environment(PYTHON.parent, required=True)

    wheels = [fetch(*package) for package in PACKAGES]
    run(str(PYTHON), "-m", "pip", "install", "--no-cache-dir", str(wheels[0]))
    run(str(PYTHON), "-m", "pip", "install", "--no-cache-dir", "--no-deps", str(wheels[1]))
    run(str(PYTHON), "-m", "pip", "install", "--no-cache-dir",
        "timm==0.9.16", "pytorch-lightning==2.6.6", "PyYAML==6.0.3",
        "lmdb==2.3.0", "nltk==3.10.3", "zxing-cpp==3.1.1")
    # Some NVIDIA-published wheel metadata differs from the pair validated on
    # JetPack 6.1; the actual imports, CUDA check and model load below decide.
    subprocess.run([str(PYTHON), "-m", "pip", "check"], check=False)
    subprocess.run([str(PYTHON), "-c",
        "import torch, torchvision, timm, pytorch_lightning, PIL, zxingcpp; "
        "assert torch.cuda.is_available(), 'Jetson CUDA is unavailable'; "
        "from station.vision import Vision; vision=Vision(); vision.load(); "
        "print('OCR READY:', torch.__version__, torchvision.__version__, "
        "torch.cuda.get_device_name(0), vision.status()['model_hash'])"],
        check=True, env=ocr_env)
    print("OCR dependencies and local model verified in .venv-bench.", flush=True)


if __name__ == "__main__":
    main()
