"""Expose the cuSPARSELt library installed in the local Jetson virtualenv."""

from __future__ import annotations

import os
from pathlib import Path


def cusparselt_environment(venv: Path, *, required: bool = False) -> dict[str, str]:
    env = os.environ.copy()
    library_dir = venv / "lib/python3.10/site-packages/nvidia/cusparselt/lib"
    if not (library_dir / "libcusparseLt.so.0").is_file():
        if required:
            raise RuntimeError(
                "cuSPARSELt is missing from .venv-bench. Run python3 scripts/install_ocr_jetson.py."
            )
        return env
    current = env.get("LD_LIBRARY_PATH", "")
    entries = current.split(os.pathsep) if current else []
    if str(library_dir) not in entries:
        env["LD_LIBRARY_PATH"] = os.pathsep.join([str(library_dir), *entries])
    return env


GPU_INDEXES = ("https://pypi.jetson-ai-lab.io/jp6/cu126/+simple/", "https://pypi.jetson-ai-lab.io/jp6/cu126")


def _has_cuda_provider(python: Path) -> bool:
    import subprocess
    check = subprocess.run([str(python), "-c", "import onnxruntime as o; "
                            "print('CUDAExecutionProvider' in o.get_available_providers())"],
                           capture_output=True, text=True)
    return check.returncode == 0 and check.stdout.strip().endswith("True")


def ensure_onnxruntime_gpu(python: Path, wheels: Path) -> None:
    """On the Jetson, swap the CPU-only onnxruntime for the JetPack GPU build.

    The wheel is kept in runtime/jetson-ai-wheels, so after one download the swap
    needs no network. Any failure leaves the CPU build in place and the station runs.
    """
    import platform
    import subprocess
    if platform.system() != "Linux" or platform.machine() != "aarch64" or _has_cuda_provider(python):
        return
    pip = [str(python), "-m", "pip"]
    wheels.mkdir(parents=True, exist_ok=True)
    cached = sorted(wheels.glob("onnxruntime_gpu-*.whl"))
    if not cached:
        print("Downloading the GPU build of onnxruntime for the text detector...", flush=True)
        args = [*pip, "download", "--no-deps", "--only-binary", ":all:", "--timeout", "15", "--retries", "1",
                "-d", str(wheels), "--index-url", GPU_INDEXES[0], "--extra-index-url", GPU_INDEXES[1],
                "onnxruntime-gpu"]
        try:
            subprocess.run(args, check=True, timeout=600)
        except Exception as exc:
            print("onnxruntime GPU build not downloaded; text detection stays on the CPU.", exc, flush=True)
            return
        cached = sorted(wheels.glob("onnxruntime_gpu-*.whl"))
        if not cached:
            return
    subprocess.run([*pip, "uninstall", "-y", "onnxruntime"], check=False)
    installed = subprocess.run([*pip, "install", "--no-deps", "--force-reinstall", str(cached[-1])])
    if installed.returncode or not _has_cuda_provider(python):
        print("onnxruntime GPU build did not load; putting the CPU build back.", flush=True)
        subprocess.run([*pip, "uninstall", "-y", "onnxruntime-gpu"], check=False)
        subprocess.run([*pip, "install", "onnxruntime==1.23.2"], check=False)
        return
    print("Text detection runs on the GPU (onnxruntime CUDA).", flush=True)
