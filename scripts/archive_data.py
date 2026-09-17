"""Archive DB + evidence and restore only into a NEW directory; never overwrite live data.
Run after stopping the station so DB and evidence belong to the same completed state.
"""

import argparse, hashlib, json, sqlite3, zipfile
from contextlib import closing
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def archive(source, output):
    if output.exists():
        raise ValueError("Archive already exists")
    if not (source / "station.sqlite3").is_file():
        raise ValueError("Station DB missing")
    # Read-only online backup handles a remaining WAL without copying inconsistent DB pages.
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "station.sqlite3"
        with closing(
            sqlite3.connect(
                (source / "station.sqlite3").resolve().as_uri() + "?mode=ro", uri=True
            )
        ) as conn, closing(sqlite3.connect(db)) as target:
            conn.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("DB integrity failed")
        files = [(db, "station.sqlite3")] + [
            (f, f.relative_to(source).as_posix())
            for f in (source / "evidence").glob("*")
            if f.is_file()
        ]
        manifest = {name: digest(path.read_bytes()) for path, name in files}
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as z:
            for path, name in files:
                z.write(path, name)
            z.writestr("archive-manifest.json", json.dumps(manifest))
    return {
        "file": str(output),
        "files": len(manifest),
        "sha256": digest(output.read_bytes()),
    }


def restore(source, target):
    if target.exists():
        raise ValueError("Restore target must be a NEW directory")
    with zipfile.ZipFile(source) as z:
        manifest = json.loads(z.read("archive-manifest.json"))
        if "station.sqlite3" not in manifest:
            raise ValueError("DB missing")
        if len(set(z.namelist())) != len(z.namelist()):
            raise ValueError("Duplicate archive entries")
        for name, expected in manifest.items():
            path = (target / name).resolve()
            if target.resolve() not in path.parents or not (
                name == "station.sqlite3" or name.startswith("evidence/")
            ):
                raise ValueError("Unsafe archive path")
            if digest(z.read(name)) != expected:
                raise ValueError("Archive hash mismatch")
        target.mkdir(parents=True)
        for name in manifest:
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(z.read(name))
    with closing(sqlite3.connect(target / "station.sqlite3")) as conn:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Restored DB integrity failed")
    return {"restored": str(target), "files": len(manifest), "automatic_run": False}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["backup", "restore"])
    p.add_argument("source", type=Path)
    p.add_argument("target", type=Path)
    args = p.parse_args()
    print(
        json.dumps(
            (
                archive(args.source, args.target)
                if args.action == "backup"
                else restore(args.source, args.target)
            ),
            ensure_ascii=False,
        )
    )
