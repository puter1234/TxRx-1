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
