"""Persistent idempotent local storage for accepted canonical events."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Protocol

from ..models import Event


class EventStore(Protocol):
    """Storage boundary used by the ingestion engine."""

    def insert_if_new(self, event: Event, adapter: str, locator: str) -> bool:
        """Persist an event; return False when its ID already exists."""


class SQLiteEventStore:
    """SQLite store with event ID uniqueness enforced by a primary key."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, timeout=30)
        self._connection.execute("PRAGMA busy_timeout = 30000")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS events ("
            "event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, adapter TEXT NOT NULL, "
            "locator TEXT NOT NULL, ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        self._connection.commit()

    def insert_if_new(self, event: Event, adapter: str, locator: str) -> bool:
        """Insert canonical event once, returning whether a row was added."""
        cursor = self._connection.execute(
            "INSERT OR IGNORE INTO events(event_id, payload, adapter, locator) VALUES (?, ?, ?, ?)",
            (event.event_id, json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":")), adapter, locator),
        )
        self._connection.commit()
        return cursor.rowcount == 1

    def get(self, event_id: str) -> dict[str, object] | None:
        """Return a stored JSON payload for inspection, if present."""
        row = self._connection.execute("SELECT payload FROM events WHERE event_id = ?", (event_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def count(self) -> int:
        """Return the number of distinct stored event IDs."""
        return int(self._connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._connection.close()

    def __enter__(self) -> "SQLiteEventStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
