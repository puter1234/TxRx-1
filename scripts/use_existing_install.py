"""Connect a fresh Git checkout to an existing local Jetson installation."""

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def connect(source, target=ROOT):
    source, target = Path(source).expanduser().resolve(), Path(target).resolve()
    if source == target:
        raise ValueError("Use a separate Git checkout folder.")
    for name in (".venv-bench/bin/python", "runtime", "config/station.json"):
        if not (source / name).exists():
            raise ValueError("Existing installation is missing: " + str(source / name))
    names = (".venv-bench", "runtime", "models/parseq", "wheelhouse",
             "config/brands/hazzys.samples.json")
    links = []
    for name in names:
        src, dst = source / name, target / name
        if not src.exists():
            continue
        if dst.exists() or dst.is_symlink():
            if dst.resolve() != src.resolve():
                raise ValueError("Destination already exists, left unchanged: " + str(dst))
        else:
            links.append((src, dst))
    for src, dst in links:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.symlink_to(src, target_is_directory=src.is_dir())
    local_config = source / "runtime/station-local.json"
    if not local_config.exists():
        shutil.copyfile(source / "config/station.json", local_config)
    print("Existing environment, settings, records and assets connected.")
    print("Keep the original installation folder: " + str(source))
    print("Start with: python3 scripts/run_bench.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    try:
        connect(args.source)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
