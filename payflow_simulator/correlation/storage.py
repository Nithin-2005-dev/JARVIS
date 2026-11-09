"""Transactional SQLite persistence for correlation runs and incident lifecycle."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol
from uuid import NAMESPACE_URL, uuid5

from .models import CorrelationEdge


class CorrelationStore(Protocol):
    def load_processed_events(self) -> list[dict[str, Any]]: ...
    def persist_correlation(self, run_id: str, events: list[Mapping[str, Any]], edges: list[CorrelationEdge], components: list[list[str]], details: Mapping[str, Any]) -> int: ...
    def record_run_metrics(self, run_id: str, metrics: Mapping[str, Any], missing_traces: int) -> None: ...
    def record_failed_run(self, run_id: str, details: Mapping[str, Any]) -> None: ...


class SQLiteCorrelationStore:
    """Extend the Stage 2/3 database without modifying source event payloads."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout=30000")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS correlation_runs(run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, details TEXT NOT NULL, metrics TEXT, status TEXT NOT NULL DEFAULT 'completed');
        CREATE TABLE IF NOT EXISTS correlation_edges(source_event_id TEXT NOT NULL,target_event_id TEXT NOT NULL,run_id TEXT NOT NULL,strategy TEXT NOT NULL,evidence TEXT NOT NULL,confidence_score REAL NOT NULL,PRIMARY KEY(source_event_id,target_event_id,strategy));
        CREATE INDEX IF NOT EXISTS correlation_edges_run_idx ON correlation_edges(run_id);
        CREATE TABLE IF NOT EXISTS incidents(incident_id TEXT PRIMARY KEY,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,severity TEXT NOT NULL,anchor_event_id TEXT NOT NULL,merged_into TEXT,summary TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS incident_members(event_id TEXT PRIMARY KEY,incident_id TEXT NOT NULL REFERENCES incidents(incident_id));
        CREATE INDEX IF NOT EXISTS incident_members_incident_idx ON incident_members(incident_id);
        CREATE TABLE IF NOT EXISTS incident_history(history_id INTEGER PRIMARY KEY AUTOINCREMENT,incident_id TEXT NOT NULL,action TEXT NOT NULL,detail TEXT NOT NULL,recorded_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS incident_history_incident_idx ON incident_history(incident_id,history_id);
        CREATE TABLE IF NOT EXISTS correlation_metrics(run_id TEXT PRIMARY KEY,metrics TEXT NOT NULL,missing_trace_ids INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS trace_diagnostics(run_id TEXT NOT NULL,diagnostic_key TEXT NOT NULL,details TEXT NOT NULL,PRIMARY KEY(run_id,diagnostic_key));
        """)
        run_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(correlation_runs)")}
        if "status" not in run_columns:
            self.connection.execute("ALTER TABLE correlation_runs ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'")
        self.connection.commit()

    def load_processed_events(self) -> list[dict[str, Any]]:
        if not self._has_table("processed_events"):
            return []
        rows = self.connection.execute("SELECT event_id,payload FROM processed_events ORDER BY event_id").fetchall()
        result = []
        for row in rows:
            item = json.loads(row["payload"])
            item.setdefault("event_id", row["event_id"])
            result.append(item)
        return result

    def persist_correlation(self, run_id: str, events: list[Mapping[str, Any]], edges: list[CorrelationEdge], components: list[list[str]], details: Mapping[str, Any]) -> int:
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        event_map = {str(item.get("event_id")): item for item in events}
        edge_details = [{"source_event_id": edge.source_event_id, "target_event_id": edge.target_event_id,
                         "strategies": [item.strategy for item in edge.evidence],
                         "confidence_score": edge.confidence_score} for edge in edges]
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute("INSERT INTO correlation_runs(run_id,created_at,details,status) VALUES(?,?,?,'completed') ON CONFLICT(run_id) DO UPDATE SET created_at=excluded.created_at,details=excluded.details,status='completed'", (run_id, now, _json(details)))
            self.connection.execute("DELETE FROM trace_diagnostics")
            for index, item in enumerate(details.get("trace_diagnostics", [])):
                key = str(item.get("trace_id") or f"missing:{index}")
                self.connection.execute("INSERT INTO trace_diagnostics(run_id,diagnostic_key,details) VALUES(?,?,?)", (run_id, key, _json(item)))
            self.connection.execute("DELETE FROM correlation_edges")
            for edge in edges:
                for evidence in edge.evidence:
                    self.connection.execute("""INSERT INTO correlation_edges(source_event_id,target_event_id,run_id,strategy,evidence,confidence_score)
                    VALUES(?,?,?,?,?,?) ON CONFLICT(source_event_id,target_event_id,strategy) DO UPDATE SET run_id=excluded.run_id,evidence=excluded.evidence,confidence_score=excluded.confidence_score""",
                    (edge.source_event_id, edge.target_event_id, run_id, evidence.strategy, _json(evidence.to_dict()), edge.confidence_score))
            old_members = {str(row["event_id"]): str(row["incident_id"]) for row in self.connection.execute("SELECT event_id,incident_id FROM incident_members")}
            old_incidents = {str(row["incident_id"]): dict(row) for row in self.connection.execute("SELECT * FROM incidents")}
            assigned: dict[str, str] = {}
            component_incident_ids: list[str] = []
            normalized_components = [sorted(set(x)) for x in components]
            normalized_components.sort(key=lambda group: (
                0 if any(incident.get("anchor_event_id") in group for incident in old_incidents.values() if incident.get("status") == "active") else 1,
                group[0],
            ))
            for group in normalized_components:
                overlapping = sorted({old_members[eid] for eid in group if eid in old_members},
                                     key=lambda iid: (old_incidents.get(iid, {}).get("created_at", now), iid))
                # On split, the prior anchor stays with the component containing it.
                anchored = [iid for iid in overlapping if old_incidents.get(iid, {}).get("anchor_event_id") in group]
                incident_id = (anchored or overlapping or [str(uuid5(NAMESPACE_URL, "jarvis-incident:" + group[0]))])[0]
                split_from = None
                if incident_id in component_incident_ids:
                    split_from = incident_id
                    incident_id = str(uuid5(NAMESPACE_URL, f"jarvis-split:{incident_id}:{group[0]}"))
                component_incident_ids.append(incident_id)
                anchor = old_incidents.get(incident_id, {}).get("anchor_event_id") or group[0]
                severity = max((_severity(event_map.get(eid, {})) for eid in group), key=lambda x: _severity_rank(x))
                summary = f"Correlated events across {len({str(_original(event_map.get(eid, {})).get('service', 'unknown')) for eid in group})} services"
                self.connection.execute("""INSERT INTO incidents(incident_id,status,created_at,updated_at,severity,anchor_event_id,merged_into,summary)
                VALUES(?, 'active', ?, ?, ?, ?, NULL, ?) ON CONFLICT(incident_id) DO UPDATE SET status='active',updated_at=excluded.updated_at,severity=excluded.severity,merged_into=NULL,summary=excluded.summary""",
                (incident_id, old_incidents.get(incident_id, {}).get("created_at", now), now, severity, anchor, summary))
                if incident_id not in old_incidents:
                    self._history(incident_id, "created", {"incident_id": incident_id, "event_ids": group,
                                   "split_from": split_from,
                                   "supporting_relationships": [edge for edge in edge_details if edge["source_event_id"] in group and edge["target_event_id"] in group]}, now)
                # Merge competing prior incidents only when component graph directly joins them.
                merged_ids: list[str] = []
                for duplicate in overlapping:
                    if duplicate == incident_id:
                        continue
                    # A prior ID already assigned to another new component is a
                    # split, not a merge. The old anchor component keeps that ID.
                    if duplicate in component_incident_ids:
                        continue
                    self.connection.execute("UPDATE incidents SET status='merged',merged_into=?,updated_at=? WHERE incident_id=?", (incident_id, now, duplicate))
                    merged_ids.append(duplicate)
                    self._history(duplicate, "merged", {"merged_into": incident_id, "event_ids": group,
                                   "supporting_relationships": [edge for edge in edge_details if edge["source_event_id"] in group and edge["target_event_id"] in group]}, now)
                if merged_ids:
                    self._history(incident_id, "incidents_merged", {"merged_incident_ids": sorted(merged_ids),
                                   "supporting_relationships": [edge for edge in edge_details if edge["source_event_id"] in group and edge["target_event_id"] in group]}, now)
                for eid in group:
                    previous = old_members.get(eid)
                    if previous != incident_id:
                        supporting = [edge for edge in edge_details if eid in {edge["source_event_id"], edge["target_event_id"]}
                                      and edge["source_event_id"] in group and edge["target_event_id"] in group]
                        self._history(incident_id, "event_added", {"event_id": eid, "previous_incident_id": previous,
                                       "supporting_relationships": supporting}, now)
                    assigned[eid] = incident_id
            # Lifecycle transitions, removal is transactional and auditable.
            for iid, incident in old_incidents.items():
                prior_ids = {eid for eid, val in old_members.items() if val == iid}
                next_ids = {eid for eid, val in assigned.items() if val == iid}
                removed = sorted(prior_ids - next_ids)
                current_status = self.connection.execute("SELECT status FROM incidents WHERE incident_id=?", (iid,)).fetchone()
                if removed and incident["status"] == "active" and current_status and current_status[0] == "active":
                    action = "split" if next_ids else "resolved"
                    self._history(iid, action, {"removed_event_ids": removed}, now)
                    if not next_ids and not any(val == iid for val in assigned.values()):
                        self.connection.execute("UPDATE incidents SET status='resolved',updated_at=? WHERE incident_id=?", (now, iid))
            self.connection.execute("DELETE FROM incident_members")
            self.connection.executemany("INSERT INTO incident_members(event_id,incident_id) VALUES(?,?)", sorted(assigned.items()))
            self.connection.commit()
            return sum(1 for iid in component_incident_ids if iid not in old_incidents)
        except Exception:
            self.connection.rollback()
            raise

    def _history(self, incident_id: str, action: str, detail: Mapping[str, Any], now: str) -> None:
        exists = self.connection.execute("SELECT 1 FROM incident_history WHERE incident_id=? AND action=? AND detail=?", (incident_id, action, _json(detail))).fetchone()
        if exists:
            return
        self.connection.execute("INSERT INTO incident_history(incident_id,action,detail,recorded_at) VALUES(?,?,?,?)", (incident_id, action, _json(detail), now))

    def record_run_metrics(self, run_id: str, metrics: Mapping[str, Any], missing_traces: int) -> None:
        self.connection.execute("INSERT INTO correlation_metrics(run_id,metrics,missing_trace_ids) VALUES(?,?,?) ON CONFLICT(run_id) DO UPDATE SET metrics=excluded.metrics,missing_trace_ids=excluded.missing_trace_ids", (run_id, _json(metrics), missing_traces))
        self.connection.execute("UPDATE correlation_runs SET metrics=? WHERE run_id=?", (_json(metrics), run_id))
        self.connection.commit()

    def record_failed_run(self, run_id: str, details: Mapping[str, Any]) -> None:
        """Persist a retryable failed-run status after the main transaction rolls back."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.connection.execute("INSERT INTO correlation_runs(run_id,created_at,details,metrics,status) VALUES(?,?,?,NULL,'failed') ON CONFLICT(run_id) DO UPDATE SET created_at=excluded.created_at,details=excluded.details,metrics=NULL,status='failed'", (run_id, now, _json(details)))
        self.connection.execute("DELETE FROM correlation_metrics WHERE run_id=?", (run_id,))
        self.connection.commit()

    def list_incidents(self, status: str | None = "active") -> list[dict[str, Any]]:
        query = "SELECT * FROM incidents" + (" WHERE status=?" if status else "") + " ORDER BY created_at,incident_id"
        rows = self.connection.execute(query, (status,) if status else ()).fetchall()
        return [self._incident_dict(row) for row in rows]

    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM incidents WHERE incident_id=?", (incident_id,)).fetchone()
        return self._incident_dict(row) if row else None

    def _incident_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["event_ids"] = [str(r[0]) for r in self.connection.execute("SELECT event_id FROM incident_members WHERE incident_id=? ORDER BY event_id", (row["incident_id"],))]
        return result

    def incident_events(self, incident_id: str) -> list[dict[str, Any]]:
        if not self._has_table("processed_events"):
            return []
        rows = self.connection.execute("SELECT p.event_id,p.payload FROM incident_members m JOIN processed_events p USING(event_id) WHERE m.incident_id=? ORDER BY p.event_id", (incident_id,)).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def incident_evidence(self, incident_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute("""SELECT e.* FROM correlation_edges e JOIN incident_members a ON a.event_id=e.source_event_id
        JOIN incident_members b ON b.event_id=e.target_event_id AND b.incident_id=a.incident_id WHERE a.incident_id=? ORDER BY e.source_event_id,e.target_event_id,e.strategy""", (incident_id,)).fetchall()
        return [dict(row) | {"evidence": json.loads(row["evidence"])} for row in rows]

    def incident_history(self, incident_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT * FROM incident_history WHERE incident_id=? ORDER BY history_id", (incident_id,)).fetchall()
        return [dict(row) | {"detail": json.loads(row["detail"])} for row in rows]

    def related_events(self, event_id: str) -> list[dict[str, Any]]:
        if not self._has_table("processed_events"):
            return []
        rows = self.connection.execute("""SELECT DISTINCT p.event_id,p.payload FROM correlation_edges e JOIN processed_events p
        ON p.event_id=CASE WHEN e.source_event_id=? THEN e.target_event_id ELSE e.source_event_id END
        WHERE e.source_event_id=? OR e.target_event_id=? ORDER BY p.event_id""", (event_id, event_id, event_id)).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def statistics(self) -> dict[str, Any]:
        processed_count = self.connection.execute("SELECT COUNT(*) FROM processed_events").fetchone()[0] if self._has_table("processed_events") else 0
        result = {"events_processed": processed_count,
                  "correlation_edges": self.connection.execute("SELECT COUNT(*) FROM correlation_edges").fetchone()[0],
                  "incidents_active": self.connection.execute("SELECT COUNT(*) FROM incidents WHERE status='active'").fetchone()[0],
                  "incidents_total": self.connection.execute("SELECT COUNT(*) FROM incidents").fetchone()[0],
                  "strategies": {str(row[0]): int(row[1]) for row in self.connection.execute("SELECT strategy,COUNT(*) FROM correlation_edges GROUP BY strategy")}}
        row = self.connection.execute("SELECT run_id,status,details,metrics FROM correlation_runs ORDER BY created_at DESC,rowid DESC LIMIT 1").fetchone()
        result["last_run"] = ({"run_id": row["run_id"], "status": row["status"], "details": json.loads(row["details"]),
                                "metrics": json.loads(row["metrics"]) if row["metrics"] else None} if row else None)
        result["trace_diagnostics"] = [json.loads(item[0]) for item in self.connection.execute("SELECT details FROM trace_diagnostics ORDER BY diagnostic_key")]
        return result

    def get_trace_diagnostics(self) -> list[dict[str, Any]]:
        """Return current incomplete/inconsistent trace observations."""
        return [json.loads(row[0]) for row in self.connection.execute("SELECT details FROM trace_diagnostics ORDER BY diagnostic_key")]

    def _has_table(self, name: str) -> bool:
        return self.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "SQLiteCorrelationStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _original(event: Mapping[str, Any]) -> Mapping[str, Any]:
    return event.get("original_event", event)


def _severity(event: Mapping[str, Any]) -> str:
    return str(_original(event).get("severity", "INFO")).upper()


def _severity_rank(value: str) -> int:
    return {"INFO": 0, "WARNING": 1, "ERROR": 2, "CRITICAL": 3}.get(value, 0)
