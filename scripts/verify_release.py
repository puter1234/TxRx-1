"""Verify a release before executing its application. Standard library only."""

import argparse, hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify(root, allow_source=False):
    manifest = root / "release-manifest.json"
    if not manifest.exists():
        if allow_source and (root / ".git").exists():
            return {"kind": "source-tree", "release_manifest": False}
        raise ValueError("release-manifest.json missing")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    for name, digest in data["files"].items():
        path = (root / name).resolve()
        if root.resolve() not in path.parents or not path.is_file():
            raise ValueError("Invalid/missing path: " + name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Hash mismatch: " + name)
    return {
        "kind": "release",
        "verified_files": len(data["files"]),
        "version": data["version"],
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--allow-source-tree", action="store_true")
    args = p.parse_args()
    print(json.dumps(verify(ROOT, args.allow_source_tree)))
