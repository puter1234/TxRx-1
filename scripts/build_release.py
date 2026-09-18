"""Build a local offline-runtime bundle. Optional target wheels allow offline install."""

import argparse, hashlib, json, platform, shutil, sys, zipfile, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from doctor import inspect


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, default=ROOT / "release/txrx-offline.zip")
    p.add_argument("--wheelhouse", type=Path)
    args = p.parse_args()
    check = inspect()
    if not check["software_ready"]:
        raise SystemExit(
            "Software preflight failed: " + json.dumps(check, ensure_ascii=False)
        )
    if args.output.exists():
        raise SystemExit("Output exists. Choose a new release filename.")
    files = []
    # Model verification covers upstream dotfiles too; keep every manifest entry.
    model_files = {
        "models/parseq/" + name
        for name in json.loads(
            (ROOT / "models/parseq/manifest.json").read_text(encoding="utf-8")
        )
    }
    for name in (
        "station",
        "ocr",
        "tagreader",
        "config",
        "models",
        "deploy",
        "scripts",
        "docs",
    ):
        for path in (ROOT / name).rglob("*"):
            rel = path.relative_to(ROOT)
            if not path.is_file() or any(
                x in rel.parts for x in ("node_modules", "__pycache__", ".pytest_cache")
            ):
                continue
            if (
                any(x.startswith(".") for x in rel.parts)
                and rel.as_posix() not in model_files
            ) or path.name in (
                "temp.txt",
                "spec.pdf",
            ):
                continue
            if name == "ocr" and "frontend" in rel.parts and "dist" not in rel.parts:
                continue
            if name == "ocr" and "backend" in rel.parts:
                continue
            files.append((path, rel.as_posix()))
    for name in (
        "pipeline.py",
        "requirements.txt",
        "requirements-station.txt",
        "requirements-lock-windows.txt",
        "README.md",
        "run-station.ps1",
        "run-station.sh",
        "install-offline.ps1",
    ):
        path = ROOT / name
        if path.exists():
            files.append((path, name))
    if args.wheelhouse:
        if not args.wheelhouse.is_dir() or not list(args.wheelhouse.glob("*.whl")):
            raise SystemExit("Wheelhouse missing or empty")
        files.extend(
            (f, "wheelhouse/" + f.name)
            for f in args.wheelhouse.iterdir()
            if f.is_file()
        )
    manifest = {
        name: hashlib.sha256(path.read_bytes()).hexdigest() for path, name in files
    }
    release = {
        "version": "0.3.0",
        "build_platform": platform.platform(),
        "hardware_acceptance": "NOT_VERIFIED",
        "runtime_network_required": False,
        "offline_install_wheels_included": bool(args.wheelhouse),
        "files": manifest,
        "preflight": check,
    }
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    )
    release["source_commit"] = (
        revision.stdout.strip() if revision.returncode == 0 else None
    )
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True
    )
    release["source_worktree_dirty"] = (
        bool(status.stdout.strip()) if status.returncode == 0 else None
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        args.output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=4
    ) as z:
        for path, name in files:
            z.write(path, name)
        z.writestr(
            "release-manifest.json", json.dumps(release, ensure_ascii=False, indent=2)
        )
    print(
        json.dumps(
            {
                "file": str(args.output),
                "bytes": args.output.stat().st_size,
                "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
                "files": len(files),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
