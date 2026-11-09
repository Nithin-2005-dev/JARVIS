"""Transactional local persistence for graph definitions and analysis snapshots."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .models import DependencyGraph


class SQLiteDependencyGraphStore:
    """Add versioned dependency records to the shared Stage 2–5 SQLite file."""
    def __init__(self, path: str | Path):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout=30000")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS dependency_services(service_id TEXT PRIMARY KEY,payload TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS dependency_definitions(dependency_id TEXT PRIMARY KEY,source_service_id TEXT NOT NULL,target_service_id TEXT NOT NULL,payload TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS dependency_graph_versions(graph_version TEXT PRIMARY KEY,created_at TEXT NOT NULL,fingerprint TEXT NOT NULL,services_json TEXT NOT NULL,dependencies_json TEXT NOT NULL,findings_json TEXT NOT NULL,config_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS dependency_graph_current(singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1),graph_version TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS blast_radius_analyses(analysis_id TEXT PRIMARY KEY,graph_version TEXT NOT NULL,root_service_id TEXT NOT NULL,incident_id TEXT,rca_investigation_id TEXT,created_at TEXT NOT NULL,input_fingerprint TEXT NOT NULL,payload TEXT NOT NULL,UNIQUE(input_fingerprint));
        CREATE INDEX IF NOT EXISTS blast_radius_incident_idx ON blast_radius_analyses(incident_id,created_at);
        CREATE INDEX IF NOT EXISTS blast_radius_root_idx ON blast_radius_analyses(root_service_id,created_at);
        """)
        self.connection.commit()

    def save_graph(self, graph: DependencyGraph) -> None:
        now = _now(); value = graph.to_dict()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute("INSERT OR IGNORE INTO dependency_graph_versions VALUES(?,?,?,?,?,?,?)",
                (graph.graph_version, now, graph.graph_version,
                 _json(value["services"]), _json(value["dependencies"]), _json(value["findings"]), _json(value["config"])))
            self.connection.execute("INSERT INTO dependency_graph_current(singleton_id,graph_version) VALUES(1,?) ON CONFLICT(singleton_id) DO UPDATE SET graph_version=excluded.graph_version", (graph.graph_version,))
            self.connection.execute("DELETE FROM dependency_services")
            self.connection.executemany("INSERT INTO dependency_services VALUES(?,?,?)",
                [(s["service_id"], _json(s), now) for s in value["services"]])
            self.connection.execute("DELETE FROM dependency_definitions")
            self.connection.executemany("INSERT INTO dependency_definitions VALUES(?,?,?,?,?)",
                [(f"{d['source_service_id']}->{d['target_service_id']}:{d['dependency_type']}", d["source_service_id"], d["target_service_id"], _json(d), now) for d in value["dependencies"]])
            self.connection.commit()
        except Exception:
            self.connection.rollback(); raise

    def graph_snapshot(self, graph_version: str | None = None) -> dict[str, Any] | None:
        if graph_version:
            row = self.connection.execute("SELECT * FROM dependency_graph_versions WHERE graph_version=?", (graph_version,)).fetchone()
        else:
            row = self.connection.execute("SELECT v.* FROM dependency_graph_versions v JOIN dependency_graph_current c ON c.graph_version=v.graph_version WHERE c.singleton_id=1").fetchone()
            if row is None:
                row = self.connection.execute("SELECT * FROM dependency_graph_versions ORDER BY created_at DESC,graph_version DESC LIMIT 1").fetchone()
        if not row: return None
        return {"graph_version": row["graph_version"], "created_at": row["created_at"],
                "services": json.loads(row["services_json"]), "dependencies": json.loads(row["dependencies_json"]),
                "findings": json.loads(row["findings_json"]), "config": json.loads(row["config_json"])}

    def load_graph(self, graph_version: str | None = None):
        """Reconstruct a validated graph snapshot; no current definitions are rewritten."""
        snapshot = self.graph_snapshot(graph_version)
        if snapshot is None: return None
        from .graph_builder import DependencyGraphBuilder
        from .service_registry import config_from_dict
        graph = DependencyGraphBuilder(config_from_dict(snapshot["config"])).build()
        if graph.graph_version != snapshot["graph_version"]:
            raise ValueError("stored dependency graph snapshot failed version verification")
        return graph

    def graph_history(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.connection.execute("SELECT graph_version,created_at,fingerprint FROM dependency_graph_versions ORDER BY created_at,graph_version")]

    def incident_context(self, incident_id: str) -> dict[str, Any] | None:
        if not _has_table(self.connection, "incidents"): return None
        incident = self.connection.execute("SELECT * FROM incidents WHERE incident_id=?", (incident_id,)).fetchone()
        if not incident: return None
        events: list[dict[str, Any]] = []
        if _has_table(self.connection, "processed_events"):
            events = [json.loads(r["payload"]) for r in self.connection.execute("SELECT p.payload FROM incident_members m JOIN processed_events p USING(event_id) WHERE m.incident_id=? ORDER BY p.event_id", (incident_id,))]
        rca = None
        if _has_table(self.connection, "rca_investigations"):
            row = self.connection.execute("SELECT investigation_id,report,created_at FROM rca_investigations WHERE incident_id=? ORDER BY created_at DESC,investigation_id DESC LIMIT 1", (incident_id,)).fetchone()
            if row: rca = {"investigation_id": row["investigation_id"], "created_at": row["created_at"], "report": json.loads(row["report"])}
        return {"incident": dict(incident), "events": events, "rca": rca}

    def save_analysis(self, analysis_id: str, graph_version: str, root_service_id: str, incident_id: str | None,
                      rca_investigation_id: str | None, fingerprint: str, payload: Mapping[str, Any]) -> None:
        now = str(payload.get("analysis_timestamp") or _now())
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute("INSERT OR IGNORE INTO blast_radius_analyses VALUES(?,?,?,?,?,?,?,?)",
                (analysis_id, graph_version, root_service_id, incident_id, rca_investigation_id, now, fingerprint, _json(payload)))
            self.connection.commit()
        except Exception:
            self.connection.rollback(); raise

    def analysis(self, analysis_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT payload FROM blast_radius_analyses WHERE analysis_id=?", (analysis_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def analysis_history(self, *, incident_id: str | None = None, service_id: str | None = None) -> list[dict[str, Any]]:
        clauses=[]; params=[]
        if incident_id is not None: clauses.append("incident_id=?"); params.append(incident_id)
        if service_id is not None: clauses.append("root_service_id=?"); params.append(service_id)
        query="SELECT analysis_id,graph_version,root_service_id,incident_id,rca_investigation_id,created_at,input_fingerprint FROM blast_radius_analyses"
        if clauses: query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at,analysis_id"
        return [dict(r) for r in self.connection.execute(query, params)]

    def close(self) -> None: self.connection.close()
    def __enter__(self) -> "SQLiteDependencyGraphStore": return self
    def __exit__(self, *_: object) -> None: self.close()


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

def _json(value: Any) -> str: return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
def _now() -> str: return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
