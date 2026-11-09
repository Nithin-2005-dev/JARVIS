"""SQLite persistence for deterministic RCA report snapshots and history."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping


class SQLiteRCAStore:
    """Store RCA snapshots alongside Stage 2–4 data without rewriting events."""
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout=30000")
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS rca_investigations(investigation_id TEXT PRIMARY KEY,incident_id TEXT NOT NULL,fingerprint TEXT NOT NULL,created_at TEXT NOT NULL,report TEXT NOT NULL,UNIQUE(incident_id,fingerprint));
        CREATE INDEX IF NOT EXISTS rca_investigations_incident_idx ON rca_investigations(incident_id,created_at);
        CREATE TABLE IF NOT EXISTS rca_history(history_id INTEGER PRIMARY KEY AUTOINCREMENT,investigation_id TEXT NOT NULL,incident_id TEXT NOT NULL,action TEXT NOT NULL,recorded_at TEXT NOT NULL,detail TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS rca_hypotheses(investigation_id TEXT NOT NULL,rank INTEGER NOT NULL,candidate_event_id TEXT NOT NULL,score REAL NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(investigation_id,rank),FOREIGN KEY(investigation_id) REFERENCES rca_investigations(investigation_id));
        CREATE TABLE IF NOT EXISTS rca_evidence(investigation_id TEXT NOT NULL,candidate_event_id TEXT NOT NULL,evidence_id TEXT NOT NULL,polarity TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(investigation_id,candidate_event_id,evidence_id));
        """)
        self.connection.commit()

    def incident_context(self, incident_id: str) -> dict[str, Any] | None:
        tables = {r[0] for r in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "incidents" not in tables or "incident_members" not in tables:
            return None
        inc = self.connection.execute("SELECT * FROM incidents WHERE incident_id=?", (incident_id,)).fetchone()
        if not inc: return None
        if "processed_events" in tables:
            rows = self.connection.execute("SELECT p.event_id,p.payload FROM incident_members m JOIN processed_events p USING(event_id) WHERE m.incident_id=? ORDER BY p.event_id", (incident_id,)).fetchall()
            events = [json.loads(r["payload"]) for r in rows]
        else: events = []
        correlations = []
        if "correlation_edges" in tables:
            ids = [str(e.get("event_id", e.get("original_event", {}).get("event_id", ""))) for e in events]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                edges = self.connection.execute(f"SELECT * FROM correlation_edges WHERE source_event_id IN ({placeholders}) AND target_event_id IN ({placeholders}) ORDER BY source_event_id,target_event_id,strategy", (*ids, *ids)).fetchall()
                correlations = [dict(x) | {"evidence": json.loads(x["evidence"])} for x in edges]
        return {"incident": dict(inc), "events": events, "correlations": correlations}

    def save_investigation(self, investigation_id: str, incident_id: str, fingerprint: str, report: Mapping[str, Any]) -> None:
        payload = _json(report)
        created = str(report.get("investigated_at", ""))
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            exists = self.connection.execute("SELECT 1 FROM rca_investigations WHERE investigation_id=?", (investigation_id,)).fetchone()
            self.connection.execute("INSERT OR IGNORE INTO rca_investigations(investigation_id,incident_id,fingerprint,created_at,report) VALUES(?,?,?,?,?)", (investigation_id, incident_id, fingerprint, created, payload))
            if not exists:
                self.connection.execute("INSERT INTO rca_history(investigation_id,incident_id,action,recorded_at,detail) VALUES(?,?,?,?,?)", (investigation_id, incident_id, "investigated", created, _json({"assessment_status": report.get("assessment_status")})))
                for h in report.get("hypotheses", []):
                    self.connection.execute("INSERT INTO rca_hypotheses VALUES(?,?,?,?,?)", (investigation_id, h["rank"], h["candidate_event_id"], h["heuristic_score"], _json(h)))
                    idx = 0
                    for key in ("supporting_evidence", "contradictory_evidence", "missing_evidence"):
                        for ev in h.get(key, []):
                            self.connection.execute("INSERT INTO rca_evidence VALUES(?,?,?,?,?)", (investigation_id, h["candidate_event_id"], f"{key}:{idx}", ev["polarity"], _json(ev)))
                            idx += 1
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def get_investigation(self, investigation_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT report FROM rca_investigations WHERE investigation_id=?", (investigation_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def latest_investigation(self, incident_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT report FROM rca_investigations WHERE incident_id=? ORDER BY created_at DESC,investigation_id DESC LIMIT 1", (incident_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def hypothesis(self, investigation_id: str, candidate_event_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT payload FROM rca_hypotheses WHERE investigation_id=? AND candidate_event_id=?", (investigation_id, candidate_event_id)).fetchone()
        return json.loads(row[0]) if row else None

    def evidence(self, investigation_id: str, candidate_event_id: str) -> list[dict[str, Any]]:
        return [json.loads(r[0]) for r in self.connection.execute("SELECT payload FROM rca_evidence WHERE investigation_id=? AND candidate_event_id=? ORDER BY evidence_id", (investigation_id, candidate_event_id))]

    def compare(self, investigation_id: str) -> list[dict[str, Any]]:
        return [dict(r) | {"payload": json.loads(r["payload"])} for r in self.connection.execute("SELECT rank,candidate_event_id,score,payload FROM rca_hypotheses WHERE investigation_id=? ORDER BY rank", (investigation_id,))]

    def history(self, incident_id: str) -> list[dict[str, Any]]:
        return [dict(r) | {"detail": json.loads(r["detail"])} for r in self.connection.execute("SELECT * FROM rca_history WHERE incident_id=? ORDER BY history_id", (incident_id,))]

    def close(self) -> None: self.connection.close()
    def __enter__(self) -> "SQLiteRCAStore": return self
    def __exit__(self, *_: object) -> None: self.close()


def _json(value: Any) -> str: return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
