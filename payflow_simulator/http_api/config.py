"""Validated environment configuration for the API and deployment entry points."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Environment = Literal["development", "testing", "demo", "production"]


@dataclass(frozen=True, slots=True)
class Settings:
    environment: Environment
    database_path: Path
    secret_key: str
    frontend_origins: tuple[str, ...]
    log_level: str
    auth_enabled: bool
    session_ttl_seconds: int
    rate_limit_per_minute: int
    max_request_bytes: int

    @property
    def production(self) -> bool:
        return self.environment == "production"


def load_settings(*, environ: dict[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ
    environment = env.get("JARVIS_ENV", "development").strip().lower()
    if environment not in {"development", "testing", "demo", "production"}:
        raise ValueError("JARVIS_ENV must be development, testing, demo, or production")
    raw_url = env.get("JARVIS_DATABASE_URL") or env.get("JARVIS_DATABASE", "data/events.sqlite")
    if raw_url.startswith("sqlite:///"):
        raw_path = raw_url[len("sqlite:///"):]
    elif "://" in raw_url:
        raise ValueError("Only SQLite is supported by this release; database URL must use sqlite:/// or a local path")
    else:
        raw_path = raw_url
    database_path = Path(raw_path).expanduser().resolve()
    origins = tuple(x.strip().rstrip("/") for x in env.get("JARVIS_FRONTEND_ORIGINS", env.get("JARVIS_CORS_ORIGINS", "http://localhost:3000")).split(",") if x.strip())
    secret = env.get("JARVIS_SECRET_KEY", "")
    if environment == "production" and len(secret) < 32:
        raise ValueError("Production requires JARVIS_SECRET_KEY with at least 32 characters")
    if environment == "production" and secret.lower().startswith(("replace", "change-me", "example")):
        raise ValueError("Production JARVIS_SECRET_KEY must not be a placeholder")
    if not secret:
        # This ephemeral key is only suitable for local/test sessions and invalidates them on restart.
        import secrets
        secret = secrets.token_urlsafe(48)
    auth_default = "false" if environment == "testing" else "true"
    auth_enabled = _bool(env.get("JARVIS_AUTH_ENABLED", auth_default), "JARVIS_AUTH_ENABLED")
    if environment == "production" and not auth_enabled:
        raise ValueError("Authentication cannot be disabled in production")
    if environment == "production" and (not origins or any(not origin.startswith("https://") for origin in origins)):
        raise ValueError("Production JARVIS_FRONTEND_ORIGINS must contain HTTPS origins")
    return Settings(
        environment=environment, database_path=database_path, secret_key=secret,
        frontend_origins=origins, log_level=env.get("JARVIS_LOG_LEVEL", "INFO").upper(),
        auth_enabled=auth_enabled,
        session_ttl_seconds=_bounded_int(env.get("JARVIS_SESSION_TTL", "3600"), "JARVIS_SESSION_TTL", 60, 86400),
        rate_limit_per_minute=_bounded_int(env.get("JARVIS_RATE_LIMIT", "60"), "JARVIS_RATE_LIMIT", 1, 10000),
        max_request_bytes=_bounded_int(env.get("JARVIS_MAX_REQUEST_BYTES", "1048576"), "JARVIS_MAX_REQUEST_BYTES", 1024, 10485760),
    )


def _bool(value: str, name: str) -> bool:
    if value.lower() not in {"true", "false", "1", "0", "yes", "no"}:
        raise ValueError(f"{name} must be true or false")
    return value.lower() in {"true", "1", "yes"}


def _bounded_int(value: str, name: str, low: int, high: int) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not low <= result <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return result
