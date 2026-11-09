"""SQLite-backed processing state, output, history, watermarks, and observations."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Protocol


@dataclass(frozen=True, slots=True)
class ClaimedEvent:
    """An ingested payload claimed for one processing attempt."""

    event_id: str
    payload: dict[str, Any]
    attempt: int
    source_order: int


class ProcessingStore(Protocol):
    """Persistence interface for replaceable local or future remote backends."""

    def claim_batch(self, limit: int, stale_after_seconds: int = 300, reprocess: bool = False, run_id: str = "default") -> list[ClaimedEvent]: ...
    def current_watermark(self) -> str | None: ...
    def watermark_before(self, source_order: int) -> str | None: ...
    def get_processed(self, event_id: str) -> dict[str, Any] | None: ...
    def pattern_context(self, window_start: str, current: Mapping[str, Any]) -> dict[str, Any]: ...
    def complete(self, event_id: str, attempt: int, payload: Mapping[str, Any], observation: Mapping[str, Any], watermark: str, stage_history: list[dict[str, str]]) -> None: ...
    def fail(self, event_id: str, attempt: int, stage: str, error: str, stage_history: list[dict[str, str]]) -> None: ...


class SQLiteProcessingStore:
    """Durable local queue/status store sharing the ingestion SQLite database."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout = 30000")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.executescript(
            "CREATE TABLE IF NOT EXISTS events ("
            "event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, adapter TEXT NOT NULL, "
            "locator TEXT NOT NULL, ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);"
            "CREATE TABLE IF NOT EXISTS processing_state ("
            "event_id TEXT PRIMARY KEY, status TEXT NOT NULL, current_stage TEXT NOT NULL, "
            "attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, updated_at REAL NOT NULL, last_run_id TEXT, "
            "previous_watermark TEXT, watermark_captured INTEGER NOT NULL DEFAULT 0);"
            "CREATE TABLE IF NOT EXISTS processed_events ("
            "event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, processed_at TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS processing_history ("
            "history_id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL, attempt INTEGER NOT NULL, "
            "stage TEXT NOT NULL, status TEXT NOT NULL, detail TEXT, recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);"
            "CREATE INDEX IF NOT EXISTS processing_history_event_idx ON processing_history(event_id, history_id);"
            "CREATE TABLE IF NOT EXISTS processing_watermark ("
            "watermark_id INTEGER PRIMARY KEY CHECK(watermark_id = 1), event_timestamp TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS processing_event_watermarks ("
            "event_id TEXT PRIMARY KEY, source_order INTEGER NOT NULL, event_time_epoch REAL NOT NULL, event_timestamp TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS pattern_observations ("
            "event_id TEXT PRIMARY KEY, source_order INTEGER NOT NULL DEFAULT 0, window_start TEXT NOT NULL, service TEXT NOT NULL, "
            "event_type TEXT NOT NULL, severity TEXT NOT NULL, signature TEXT NOT NULL, is_failure INTEGER NOT NULL);"
            "CREATE INDEX IF NOT EXISTS pattern_window_idx ON pattern_observations(window_start);"
        )
        self.connection.execute("CREATE INDEX IF NOT EXISTS pattern_signature_idx ON pattern_observations(window_start,signature,is_failure)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS pattern_service_idx ON pattern_observations(window_start,service)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS processing_event_watermark_event_time_idx ON processing_event_watermarks(event_time_epoch DESC,source_order)")
        state_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(processing_state)")}
        if "last_run_id" not in state_columns:
            self.connection.execute("ALTER TABLE processing_state ADD COLUMN last_run_id TEXT")
        observation_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(pattern_observations)")}
        if "source_order" not in observation_columns:
            self.connection.execute("ALTER TABLE pattern_observations ADD COLUMN source_order INTEGER NOT NULL DEFAULT 0")
        self.connection.commit()

    def claim_batch(self, limit: int, stale_after_seconds: int = 300, reprocess: bool = False, run_id: str = "default") -> list[ClaimedEvent]:
        """Atomically claim pending/failed/stale events; optionally force replay."""
        if limit < 1:
            raise ValueError("limit must be positive")
        now = time.time()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute(
                "INSERT OR IGNORE INTO processing_state(event_id, status, current_stage, attempts, updated_at) "
                "SELECT event_id, 'pending', 'pending', 0, ? FROM events", (now,),
            )
            if reprocess:
                condition = "(s.last_run_id IS NULL OR s.last_run_id != ?)"
                parameters: list[Any] = [run_id]
            else:
                condition = "(s.status IN ('pending','failed') OR (s.status = 'processing' AND s.updated_at < ?)) AND (s.last_run_id IS NULL OR s.last_run_id != ?)"
                parameters = [now - stale_after_seconds, run_id]
            parameters.append(limit)
            rows = self.connection.execute(
                f"SELECT e.event_id, e.payload, e.rowid AS source_order, s.attempts FROM events e "
                f"JOIN processing_state s USING(event_id) WHERE {condition} "
                "ORDER BY e.rowid LIMIT ?", tuple(parameters),
            ).fetchall()
            claimed: list[ClaimedEvent] = []
            for row in rows:
                attempt = int(row["attempts"]) + 1
                self.connection.execute(
                    "UPDATE processing_state SET status='processing', current_stage='claimed', attempts=?, last_error=NULL, updated_at=?,last_run_id=? WHERE event_id=?",
                    (attempt, now, run_id, row["event_id"]),
                )
                self.connection.execute(
                    "INSERT INTO processing_history(event_id,attempt,stage,status,detail) VALUES(?,?, 'claim','started',?)",
                    (row["event_id"], attempt, "forced reprocess" if reprocess else "claimed for processing"),
                )
                claimed.append(ClaimedEvent(row["event_id"], json.loads(row["payload"]), attempt, int(row["source_order"])))
            self.connection.commit()
            return claimed
        except Exception:
            self.connection.rollback()
            raise

    def current_watermark(self) -> str | None:
        """Return the maximum successfully processed event time."""
        row = self.connection.execute("SELECT event_timestamp FROM processing_watermark WHERE watermark_id=1").fetchone()
        return str(row[0]) if row else None

    def watermark_before(self, source_order: int) -> str | None:
        """Return the maximum completed event time among earlier source records."""
        row = self.connection.execute(
            "SELECT event_timestamp FROM processing_event_watermarks WHERE source_order<? "
            "ORDER BY event_time_epoch DESC LIMIT 1", (source_order,),
        ).fetchone()
        return str(row[0]) if row else None

    def pattern_context(self, window_start: str, current: Mapping[str, Any]) -> dict[str, Any]:
        """Return indexed aggregate counts and bounded evidence for one new event."""
        event_id = str(current["event_id"])
        service = str(current["service"])
        signature = str(current["signature"])
        signature_rows = self.connection.execute(
            "SELECT event_id,service FROM pattern_observations WHERE window_start=? AND signature=? AND is_failure=1 AND source_order<? AND event_id!=? ORDER BY event_id LIMIT 20",
            (window_start, signature, int(current["source_order"]), event_id),
        ).fetchall()
        signature_count = int(self.connection.execute(
            "SELECT COUNT(*) FROM pattern_observations WHERE window_start=? AND signature=? AND is_failure=1 AND source_order<? AND event_id!=?",
            (window_start, signature, int(current["source_order"]), event_id),
        ).fetchone()[0])
        signature_services = [str(row[0]) for row in self.connection.execute(
            "SELECT DISTINCT service FROM pattern_observations WHERE window_start=? AND signature=? AND is_failure=1 AND source_order<? AND event_id!=? ORDER BY service",
            (window_start, signature, int(current["source_order"]), event_id),
        ).fetchall()]
        service_count = int(self.connection.execute(
            "SELECT COUNT(*) FROM pattern_observations WHERE window_start=? AND service=? AND source_order<? AND event_id!=?",
            (window_start, service, int(current["source_order"]), event_id),
        ).fetchone()[0])
        service_rows = self.connection.execute(
            "SELECT event_id FROM pattern_observations WHERE window_start=? AND service=? AND source_order<? AND event_id!=? ORDER BY event_id LIMIT 20",
            (window_start, service, int(current["source_order"]), event_id),
        ).fetchall()
        return {
            "signature_failure_count": signature_count,
            "signature_services": signature_services,
            "signature_evidence_ids": [str(row["event_id"]) for row in signature_rows],
            "service_event_count": service_count,
            "service_evidence_ids": [str(row["event_id"]) for row in service_rows],
        }

    def complete(self, event_id: str, attempt: int, payload: Mapping[str, Any], observation: Mapping[str, Any], watermark: str, stage_history: list[dict[str, str]]) -> None:
        """Atomically persist output, evidence, watermark, history, and success state."""
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            processed_at = str(payload["processing_timestamp"])
            self.connection.execute(
                "INSERT INTO processed_events(event_id,payload,processed_at) VALUES(?,?,?) "
                "ON CONFLICT(event_id) DO UPDATE SET payload=excluded.payload,processed_at=excluded.processed_at",
                (event_id, json.dumps(payload, sort_keys=True, separators=(",", ":")), processed_at),
            )
            self.connection.execute(
                "INSERT INTO pattern_observations(event_id,source_order,window_start,service,event_type,severity,signature,is_failure) "
                "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET source_order=excluded.source_order,window_start=excluded.window_start, "
                "service=excluded.service,event_type=excluded.event_type,severity=excluded.severity, "
                "signature=excluded.signature,is_failure=excluded.is_failure",
                (observation["event_id"], observation["source_order"], observation["window_start"], observation["service"], observation["event_type"], observation["severity"], observation["signature"], int(observation["is_failure"])),
            )
            event_time = datetime.fromisoformat(str(payload["temporal"]["event_timestamp"]).replace("Z", "+00:00"))
            self.connection.execute(
                "INSERT INTO processing_event_watermarks(event_id,source_order,event_time_epoch,event_timestamp) VALUES(?,?,?,?) "
                "ON CONFLICT(event_id) DO UPDATE SET source_order=excluded.source_order,event_time_epoch=excluded.event_time_epoch,event_timestamp=excluded.event_timestamp",
                (event_id, observation["source_order"], event_time.timestamp(), payload["temporal"]["event_timestamp"]),
            )
            prior = self.connection.execute("SELECT event_timestamp FROM processing_watermark WHERE watermark_id=1").fetchone()
            chosen_watermark = watermark
            if prior:
                prior_value = datetime.fromisoformat(str(prior[0]).replace("Z", "+00:00"))
                next_value = datetime.fromisoformat(watermark.replace("Z", "+00:00"))
                if prior_value > next_value:
                    chosen_watermark = str(prior[0])
            self.connection.execute(
                "INSERT INTO processing_watermark(watermark_id,event_timestamp) VALUES(1,?) "
                "ON CONFLICT(watermark_id) DO UPDATE SET event_timestamp=excluded.event_timestamp", (chosen_watermark,),
            )
            self.connection.execute(
                "UPDATE processing_state SET status='processed',current_stage='complete',last_error=NULL,updated_at=? WHERE event_id=?",
                (time.time(), event_id),
            )
            for item in stage_history:
                self.connection.execute(
                    "INSERT INTO processing_history(event_id,attempt,stage,status,detail) VALUES(?,?,?,?,?)",
                    (event_id, attempt, item["stage"], item["status"], item.get("detail")),
                )
            self.connection.execute(
                "INSERT INTO processing_history(event_id,attempt,stage,status,detail) VALUES(?,?, 'complete','succeeded',NULL)",
                (event_id, attempt),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def fail(self, event_id: str, attempt: int, stage: str, error: str, stage_history: list[dict[str, str]]) -> None:
        """Persist failure state and attempt history; input event remains queued."""
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute(
                "UPDATE processing_state SET status='failed',current_stage=?,last_error=?,updated_at=? WHERE event_id=?",
                (stage, error, time.time(), event_id),
            )
            for item in stage_history:
                self.connection.execute(
                    "INSERT INTO processing_history(event_id,attempt,stage,status,detail) VALUES(?,?,?,?,?)",
                    (event_id, attempt, item["stage"], item["status"], item.get("detail")),
                )
            self.connection.execute(
                "INSERT INTO processing_history(event_id,attempt,stage,status,detail) VALUES(?,?,?,?,?)",
                (event_id, attempt, stage, "failed", error),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def get_processed(self, event_id: str) -> dict[str, Any] | None:
        """Load a processed event payload, if successfully produced."""
        row = self.connection.execute("SELECT payload FROM processed_events WHERE event_id=?", (event_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def get_state(self, event_id: str) -> dict[str, Any] | None:
        """Inspect lifecycle state for one input event."""
        row = self.connection.execute("SELECT * FROM processing_state WHERE event_id=?", (event_id,)).fetchone()
        return dict(row) if row else None

    def history(self, event_id: str) -> list[dict[str, Any]]:
        """Return ordered processing history for one event."""
        rows = self.connection.execute("SELECT * FROM processing_history WHERE event_id=? ORDER BY history_id", (event_id,)).fetchall()
        return [dict(row) for row in rows]

    def state_counts(self) -> dict[str, int]:
        """Return counts grouped by processing state."""
        rows = self.connection.execute("SELECT status,COUNT(*) AS count FROM processing_state GROUP BY status").fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def close(self) -> None:
        """Close the SQLite connection."""
        self.connection.close()

    def __enter__(self) -> "SQLiteProcessingStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
