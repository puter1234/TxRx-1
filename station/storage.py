from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path


def utc():
    return datetime.now(timezone.utc).isoformat()


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        from .ownership import Ownership

        self.ownership = Ownership(root / ".station.lock")
        self.path = root / "station.sqlite3"
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(
            self.path, check_same_thread=False, isolation_level=None
        )
        self.conn.row_factory = sqlite3.Row
        if self.conn.execute("PRAGMA user_version").fetchone()[0] not in (0, 1):
            self.conn.close()
            self.ownership.close()
            raise RuntimeError(
                "지원하지 않는 DB 버전입니다. 이전 DB를 덮어쓰지 않습니다."
            )
        if self.conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            self.conn.close()
            self.ownership.close()
            raise RuntimeError("DB 무결성 오류입니다. 확인된 백업으로 복원하세요.")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(
            """
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS brands(id TEXT PRIMARY KEY, revision INTEGER NOT NULL, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS brand_revisions(id TEXT, revision INTEGER, body TEXT NOT NULL, created_at TEXT,
          PRIMARY KEY(id, revision));
        CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, body TEXT NOT NULL, created_at TEXT);
        CREATE TABLE IF NOT EXISTS inspections(id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
          product_id TEXT NOT NULL, attempt INTEGER NOT NULL, status TEXT NOT NULL, body TEXT NOT NULL,
          created_at TEXT, UNIQUE(session_id,product_id,attempt));
        CREATE TABLE IF NOT EXISTS counts(session_id TEXT, product_id TEXT, inspection_id TEXT UNIQUE,
          PRIMARY KEY(session_id,product_id));
        CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
          created_at TEXT NOT NULL, body TEXT NOT NULL);
        PRAGMA user_version=1;
        """
        )

    @contextmanager
    def transaction(self):
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise

    def get(self, key, default=None):
        with self.lock:
            row = self.conn.execute(
                "SELECT value FROM meta WHERE key=?", (key,)
            ).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        with self.transaction() as c:
            c.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, dump(value)))

    def event(self, kind, body, c=None):
        if c is None:
            with self.transaction() as c:
                return self.event(kind, body, c)
        return c.execute(
            "INSERT INTO events(kind,created_at,body) VALUES(?,?,?)",
            (kind, utc(), dump(body)),
        ).lastrowid

    def events(self, after=None, limit=200):
        with self.lock:
            if after is None:
                rows = list(
                    reversed(
                        self.conn.execute(
                            "SELECT * FROM events ORDER BY seq DESC LIMIT ?", (limit,)
                        ).fetchall()
                    )
                )
            else:
                rows = self.conn.execute(
                    "SELECT * FROM events WHERE seq>? ORDER BY seq LIMIT ?",
                    (after, limit),
                ).fetchall()
        return [{**dict(r), "body": json.loads(r["body"])} for r in rows]

    def brands(self):
        with self.lock:
            return [
                json.loads(r[0])
                for r in self.conn.execute("SELECT body FROM brands ORDER BY id")
            ]

    def last_event_seq(self):
        with self.lock:
            return self.conn.execute(
                "SELECT COALESCE(MAX(seq),0) FROM events"
            ).fetchone()[0]

    def metrics(self):
        rows = self.inspection_rows(2000)
        values = sorted(
            r["elapsed_ms"] for r in rows if r.get("elapsed_ms") is not None
        )

        def percentile(p):
            if not values:
                return None
            index = (len(values) - 1) * p
            lo = int(index)
            hi = min(lo + 1, len(values) - 1)
            return values[lo] + (values[hi] - values[lo]) * (index - lo)

        decisions = {
            key: sum(r["status"] == key for r in rows)
            for key in ("PASS", "FAIL", "ABORTED", "PENDING")
        }
        channels = {
            key: {
                "requested": sum(key in r["recipe"]["channels"] for r in rows),
                "read": sum(bool(r.get("observations", {}).get(key)) for r in rows),
            }
            for key in ("ocr", "rfid", "barcode")
        }
        with self.lock:
            restarts = self.conn.execute(
                "SELECT COUNT(*) FROM events WHERE kind='PROCESS_RESTART'"
            ).fetchone()[0]
        return {
            "sample_count": len(rows),
            "sample_limit": 2000,
            "decisions": decisions,
            "channels": channels,
            "latency_ms": {
                "p50": percentile(0.5),
                "p95": percentile(0.95),
                "p99": percentile(0.99),
            },
            "recovery_restarts": restarts,
            "inference_queue_capacity": 1,
            "db_bytes": self.path.stat().st_size,
            "wal_bytes": (
                Path(str(self.path) + "-wal").stat().st_size
                if Path(str(self.path) + "-wal").exists()
                else 0
            ),
        }

    def brand(self, ident):
        with self.lock:
            row = self.conn.execute(
                "SELECT body FROM brands WHERE id=?", (ident,)
            ).fetchone()
        if row is None:
            raise KeyError("메이커를 찾을 수 없습니다.")
        return json.loads(row[0])

    def save_brand(
        self,
        brand: dict,
        expected_revision: int | None,
        actor: str,
        reason="메이커 설정 저장",
    ):
        with self.transaction() as c:
            existing = c.execute(
                "SELECT revision FROM brands WHERE id=?", (brand["id"],)
            ).fetchone()
            before = self.brand(brand["id"]) if existing else None
            if existing and existing[0] != expected_revision:
                raise ValueError("메이커 설정 충돌: 다시 불러오세요.")
            if not existing and expected_revision is not None:
                raise ValueError("등록되지 않은 메이커입니다.")
            previous = c.execute(
                "SELECT COALESCE(MAX(revision),0) FROM brand_revisions WHERE id=?",
                (brand["id"],),
            ).fetchone()[0]
            brand = {**brand, "revision": previous + 1}
            body = dump(brand)
            c.execute(
                "INSERT OR REPLACE INTO brands VALUES(?,?,?)",
                (brand["id"], brand["revision"], body),
            )
            c.execute(
                "INSERT INTO brand_revisions VALUES(?,?,?,?)",
                (brand["id"], brand["revision"], body, utc()),
            )
            self.event(
                "BRAND_SAVED",
                {
                    "id": brand["id"],
                    "revision": brand["revision"],
                    "actor": actor,
                    "reason": reason,
                    "before": before,
                    "after": brand,
                },
                c,
            )
        return brand

    def delete_brand(self, ident, revision, actor, reason="메이커 설정 삭제"):
        with self.transaction() as c:
            before = self.brand(ident)
            if (
                c.execute(
                    "DELETE FROM brands WHERE id=? AND revision=?", (ident, revision)
                ).rowcount
                != 1
            ):
                raise ValueError("설정이 변경되었거나 이미 삭제되었습니다.")
            self.event(
                "BRAND_DELETED",
                {
                    "id": ident,
                    "revision": revision,
                    "actor": actor,
                    "reason": reason,
                    "before": before,
                    "after": None,
                },
                c,
            )

    def session(self, session, c=None):
        if c is None:
            with self.transaction() as c:
                return self.session(session, c)
        c.execute(
            "INSERT OR REPLACE INTO sessions VALUES(?,?,?)",
            (session["id"], dump(session), session["created_at"]),
        )
        c.execute(
            "INSERT OR REPLACE INTO meta VALUES(?,?)", ("last_session", dump(session))
        )

    def histories(self, limit=100, offset=0):
        with self.lock:
            rows = self.conn.execute(
                "SELECT body FROM sessions ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def inspection_rows(self, limit=100, offset=0):
        with self.lock:
            rows = self.conn.execute(
                "SELECT body FROM inspections ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def command_result(self, ident, fingerprint):
        with self.lock:
            row = self.conn.execute(
                "SELECT fingerprint,body FROM commands WHERE id=?", (ident,)
            ).fetchone()
        if row and row[0] != fingerprint:
            raise ValueError("같은 요청 ID로 다른 명령을 실행할 수 없습니다.")
        return json.loads(row[1]) if row else None

    def backup(self):
        directory = self.root / "backups"
        directory.mkdir(exist_ok=True)
        path = directory / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".sqlite3")
        with self.lock, closing(sqlite3.connect(path)) as target:
            self.conn.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("백업 무결성 검사 실패")
        return {
            "name": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }

    def daily_backup(self):
        day = datetime.now().date().isoformat()
        if self.get("last_daily_backup", {}).get("day") == day:
            return None
        result = self.backup()
        self.put("last_daily_backup", {"day": day, **result})
        self.event("DAILY_BACKUP_CREATED", result)
        return result

    def close(self):
        with self.lock:
            try:
                self.conn.close()
            finally:
                self.ownership.close()
