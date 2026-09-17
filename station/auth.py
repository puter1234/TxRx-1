import hashlib
import hmac
import re
import secrets
import threading
import time


class Auth:
    def __init__(self, store):
        self.store = store
        self.sessions = {}
        self.failures = []
        self.lock = threading.RLock()
        legacy = store.get("admin_pin")
        if legacy and store.get("users") is None:
            store.put(
                "users",
                {
                    "admin": {
                        "username": "admin",
                        "role": "admin",
                        "enabled": True,
                        **legacy,
                    }
                },
            )

    def configured(self):
        return bool(self.store.get("users", {}))

    @staticmethod
    def password(pin):
        if not 6 <= len(pin) <= 64:
            raise ValueError("비밀번호는 6~64자로 지정하세요.")
        salt = secrets.token_hex(16)
        digest = hashlib.scrypt(
            pin.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1
        ).hex()
        return {"salt": salt, "digest": digest}

    def set_pin(self, pin):
        with self.lock:
            if self.configured():
                raise ValueError("이미 초기 설정을 완료했습니다.")
            self.store.put(
                "users",
                {
                    "admin": {
                        "username": "admin",
                        "role": "admin",
                        "enabled": True,
                        **self.password(pin),
                    }
                },
            )

    def users(self):
        return [
            {k: v for k, v in row.items() if k in ("username", "role", "enabled")}
            for row in self.store.get("users", {}).values()
        ]

    def save_user(self, username, role, enabled, password, actor, reason):
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,40}", username):
            raise ValueError("사용자 ID 형식 오류")
        if role not in ("admin", "engineer", "operator"):
            raise ValueError("권한 형식 오류")
        with self.lock:
            users = self.store.get("users", {})
            prior = users.get(username)
            if not prior and not password:
                raise ValueError("새 사용자는 비밀번호가 필요합니다.")
            row = {
                **(prior or {}),
                "username": username,
                "role": role,
                "enabled": enabled,
            }
            if password:
                row.update(self.password(password))
            users[username] = row
            if not any(u["enabled"] and u["role"] == "admin" for u in users.values()):
                raise ValueError("활성 관리자 한 명 이상이 필요합니다.")
            from .storage import dump

            with self.store.transaction() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO meta VALUES(?,?)", ("users", dump(users))
                )
                clean = lambda u: {
                    k: v
                    for k, v in (u or {}).items()
                    if k in ("username", "role", "enabled")
                }
                self.store.event(
                    "USER_CHANGED",
                    {
                        "actor": actor,
                        "reason": reason,
                        "before": clean(prior),
                        "after": clean(row),
                        "password_changed": bool(password),
                    },
                    conn,
                )
            self.sessions = {
                t: s for t, s in self.sessions.items() if s["username"] != username
            }
            return self.users()

    def login(self, pin, username="admin"):
        with self.lock:
            now = time.monotonic()
            self.failures = [t for t in self.failures if now - t < 60]
            if len(self.failures) >= 8:
                raise ValueError("잠시 후 다시 로그인하세요.")
            saved = self.store.get("users", {}).get(username)
            dummy = {"salt": "00" * 16, "digest": "00" * 64}
            check = saved or dummy
            digest = hashlib.scrypt(
                pin.encode(), salt=bytes.fromhex(check["salt"]), n=16384, r=8, p=1
            ).hex()
            if (
                not saved
                or not saved["enabled"]
                or not hmac.compare_digest(digest, check["digest"])
            ):
                self.failures.append(now)
                raise ValueError("사용자 ID 또는 비밀번호를 확인하세요.")
            self.failures.clear()
            token = secrets.token_urlsafe(32)
            self.sessions = {
                t: s for t, s in self.sessions.items() if s["expires"] > now
            }
            self.sessions[token] = {
                "username": username,
                "role": saved["role"],
                "expires": now + 12 * 3600,
            }
            self.store.event("LOGIN", {"actor": username, "role": saved["role"]})
            return token

    def profile(self, token):
        with self.lock:
            session = self.sessions.get(token)
            if not session or session["expires"] <= time.monotonic():
                return None
            return {"username": session["username"], "role": session["role"]}

    def valid(self, token):
        return self.profile(token) is not None
