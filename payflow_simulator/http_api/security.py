"""SQLite schema bootstrap and password/session primitives for the HTTP API."""
from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

SCHEMA_VERSION = 1
PASSWORDS = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def initialize_database(path: str | Path) -> None:
    """Apply the versioned API foundation migration without modifying stage data."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(target, timeout=30)
    try:
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        db.execute("""CREATE TABLE IF NOT EXISTS api_users(
            user_id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','responder','viewer')),
            active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL)""")
        db.execute("CREATE TABLE IF NOT EXISTS api_security_audit(audit_id INTEGER PRIMARY KEY AUTOINCREMENT,recorded_at TEXT NOT NULL,event TEXT NOT NULL,username TEXT,role TEXT,request_id TEXT,details_json TEXT NOT NULL)")
        db.execute("CREATE INDEX IF NOT EXISTS api_security_audit_time_idx ON api_security_audit(recorded_at)")
        row = db.execute("SELECT COALESCE(MAX(version),0) FROM schema_migrations").fetchone()
        current = int(row[0])
        if current > SCHEMA_VERSION:
            raise RuntimeError(f"Database schema version {current} is newer than this application supports ({SCHEMA_VERSION})")
        if current < 1:
            db.execute("INSERT INTO schema_migrations(version,applied_at) VALUES(1,?)", (_now(),))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class AuthStore:
    """Small auth/user store; application data remains in existing stage stores."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        initialize_database(self.path)

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def create_user(self, username: str, password: str, role: str) -> dict[str, Any]:
        username = username.strip()
        if not 3 <= len(username) <= 80 or any(ord(ch) < 33 for ch in username):
            raise ValueError("username must be 3–80 visible characters")
        if len(password) < 12 or len(password) > 1024:
            raise ValueError("password must contain 12–1024 characters")
        if role not in {"admin", "responder", "viewer"}:
            raise ValueError("role must be admin, responder, or viewer")
        now = _now()
        db = self.connect()
        try:
            db.execute("INSERT INTO api_users(user_id,username,password_hash,role,active,created_at,updated_at) VALUES(?,?,?,?,1,?,?)",
                       (secrets.token_urlsafe(18), username, PASSWORDS.hash(password), role, now, now))
            db.commit()
            return self.get_by_username(username) or {}
        except sqlite3.IntegrityError as exc:
            db.rollback()
            raise ValueError("username already exists") from exc
        finally:
            db.close()

    def get_by_username(self, username: str) -> dict[str, Any] | None:
        db = self.connect()
        try:
            row = db.execute("SELECT * FROM api_users WHERE username=? COLLATE NOCASE", (username,)).fetchone()
            return dict(row) if row else None
        finally:
            db.close()

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        db = self.connect()
        try:
            row = db.execute("SELECT user_id,username,role,active,created_at,updated_at FROM api_users WHERE user_id=?", (user_id,)).fetchone()
            return dict(row) if row else None
        finally:
            db.close()

    def list_users(self) -> list[dict[str, Any]]:
        db = self.connect()
        try:
            return [dict(row) for row in db.execute("SELECT user_id,username,role,active,created_at,updated_at FROM api_users ORDER BY username")]
        finally:
            db.close()

    def set_user(self, user_id: str, *, role: str | None = None, active: bool | None = None) -> dict[str, Any] | None:
        if role is not None and role not in {"admin", "responder", "viewer"}:
            raise ValueError("invalid role")
        changes, values = [], []
        if role is not None: changes.append("role=?"); values.append(role)
        if active is not None: changes.append("active=?"); values.append(int(active))
        if not changes: raise ValueError("role or active is required")
        changes.append("updated_at=?"); values.append(_now()); values.append(user_id)
        db = self.connect()
        try:
            db.execute(f"UPDATE api_users SET {','.join(changes)} WHERE user_id=?", values)
            db.commit()
        finally:
            db.close()
        return self.get_user(user_id)

    def verify(self, username: str, password: str) -> dict[str, Any] | None:
        # A fixed dummy hash makes unknown-user login attempts perform a password verify too.
        user = self.get_by_username(username)
        candidate = user["password_hash"] if user else _DUMMY_HASH
        try:
            valid = PASSWORDS.verify(candidate, password)
        except (VerifyMismatchError, InvalidHashError):
            valid = False
        if not valid or not user or not user["active"]:
            return None
        if PASSWORDS.check_needs_rehash(user["password_hash"]):
            db = self.connect()
            try:
                db.execute("UPDATE api_users SET password_hash=?,updated_at=? WHERE user_id=?", (PASSWORDS.hash(password), _now(), user["user_id"]))
                db.commit()
            finally: db.close()
        return {key: user[key] for key in ("user_id", "username", "role", "active", "created_at", "updated_at")}

    def audit(self, event: str, *, username: str | None, role: str | None, request_id: str, details: dict[str, Any] | None = None) -> None:
        db = self.connect()
        try:
            db.execute("INSERT INTO api_security_audit(recorded_at,event,username,role,request_id,details_json) VALUES(?,?,?,?,?,?)",
                       (_now(), event, username, role, request_id, json.dumps(details or {}, sort_keys=True)))
            db.commit()
        finally: db.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# Argon2 hash for a non-existent account, generated once and intentionally never valid.
_DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=2$m2VmErudQnbZyGcB171jrQ$gsOAtJ5ijRUd/IzdMlOR+qw8kWOBqADFIhWwBaOmRIk"
