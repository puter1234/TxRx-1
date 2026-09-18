"""Import an existing Jetson installation into one independent Git folder."""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def detect_source():
    candidates = [Path.home() / name for name in ("TxRx-1-git", "TxRx-1-bench")]
    valid = [p for p in candidates if (p / "runtime").is_dir() and (p / "wheelhouse").is_dir()]
    if not valid:
        raise ValueError("Existing installation not found. Pass its folder path as an argument.")
    if len({(p / "runtime").resolve() for p in valid}) > 1:
        raise ValueError("Multiple independent installations found. Pass the folder to import.")
    return valid[0]


def connect(source, target=ROOT):
    source, target = Path(source).expanduser().resolve(), Path(target).resolve()
    if source == target:
        raise ValueError("Import into a fresh Git folder.")
    for name in ("runtime", "config/station.json", "wheelhouse"):
        if not (source / name).exists():
            raise ValueError("Existing installation is missing: " + str(source / name))
    if not list((source / "wheelhouse").glob("*.whl")):
        raise ValueError("Existing installation has no offline dependency wheels.")
    marker = target / "runtime/git-import-source.json"
    names = ("runtime", "models/parseq", "wheelhouse", "config/brands/hazzys.samples.json")
    if marker.is_file() and json.loads(marker.read_text(encoding="utf-8"))["source"] == str(source):
        print("Local data already imported. Continuing environment installation.")
        return
    copies = []
    for name in names:
        src, dst = source / name, target / name
        if not src.exists():
            continue
        if dst.exists() or dst.is_symlink():
            raise ValueError("Destination already exists, left unchanged: " + str(dst))
        copies.append((src.resolve(), dst))
    for src, dst in copies:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, symlinks=False)
        else:
            shutil.copy2(src, dst)
    local_config = target / "runtime/station-local.json"
    if not local_config.exists():
        shutil.copyfile(source / "config/station.json", local_config)
    marker.write_text(json.dumps({"source": str(source)}, ensure_ascii=False), encoding="utf-8")
    print("Settings, records, models and offline packages copied into: " + str(target))
    print("The original folders were left unchanged. The new folder does not link to them.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", type=Path)
    args = parser.parse_args()
    try:
        connect(args.source or detect_source())
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    subprocess.run([sys.executable, str(ROOT / "scripts/install_bench.py")], check=True)
