"""Transactional Stage 7 SQLite persistence and read access to Stage 3–6 data."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


class SQLiteIntelligenceStore:
    """Add immutable intelligence runs to the shared local SQLite database."""
    def __init__(self, path: str | Path):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout=30000")
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS intelligence_runs(run_id TEXT PRIMARY KEY,input_fingerprint TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,config_json TEXT NOT NULL,graph_version TEXT,payload_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS intelligence_features(run_id TEXT NOT NULL,service_id TEXT NOT NULL,window_start TEXT NOT NULL,payload_json TEXT NOT NULL,PRIMARY KEY(run_id,service_id,window_start));
        CREATE TABLE IF NOT EXISTS intelligence_baselines(run_id TEXT NOT NULL,baseline_version TEXT NOT NULL,service_id TEXT NOT NULL,target_window_start TEXT NOT NULL,payload_json TEXT NOT NULL,PRIMARY KEY(run_id,baseline_version));
        CREATE TABLE IF NOT EXISTS intelligence_findings(finding_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,finding_type TEXT NOT NULL,created_at TEXT NOT NULL,payload_json TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS intelligence_findings_run_idx ON intelligence_findings(run_id,finding_type);
        CREATE TABLE IF NOT EXISTS intelligence_models(run_id TEXT NOT NULL,artifact_id TEXT NOT NULL,detector_version TEXT NOT NULL,payload_json TEXT NOT NULL,PRIMARY KEY(run_id,artifact_id));
        CREATE TABLE IF NOT EXISTS intelligence_evaluations(evaluation_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,payload_json TEXT NOT NULL);
        """)
        self.connection.commit()

    def load_processed_events(self) -> list[dict[str, Any]]:
        if not self._has_table("processed_events"): return []
        return [json.loads(row[0]) for row in self.connection.execute("SELECT payload FROM processed_events ORDER BY event_id")]

    def load_incidents(self) -> list[dict[str, Any]]:
        if not self._has_table("incidents") or not self._has_table("incident_members"): return []
        result = []
        for row in self.connection.execute("SELECT * FROM incidents ORDER BY created_at,incident_id"):
            ids = [str(item[0]) for item in self.connection.execute("SELECT event_id FROM incident_members WHERE incident_id=? ORDER BY event_id", (row["incident_id"],))]
            services: set[str] = set()
            if ids and self._has_table("processed_events"):
                for start in range(0, len(ids), 900):
                    chunk = ids[start:start+900]; placeholders = ",".join("?" for _ in chunk)
                    for event_row in self.connection.execute(f"SELECT payload FROM processed_events WHERE event_id IN ({placeholders})", chunk):
                        payload = json.loads(event_row[0]); original = payload.get("original_event", payload)
                        if original.get("service"): services.add(str(original["service"]))
            result.append({**dict(row), "event_ids": ids, "service_ids": sorted(services)})
        return result

    def load_dependency_graph(self):
        """Load current Stage 6 graph if its immutable snapshot is present."""
        if not self._has_table("dependency_graph_current"): return None
        row = self.connection.execute("SELECT graph_version FROM dependency_graph_current WHERE singleton_id=1").fetchone()
        if not row: return None
        from ..dependency_graph.graph_builder import DependencyGraphBuilder
        from ..dependency_graph.service_registry import config_from_dict
        snapshot = self.connection.execute("SELECT config_json FROM dependency_graph_versions WHERE graph_version=?", (row[0],)).fetchone()
        if not snapshot: return None
        return DependencyGraphBuilder(config_from_dict(json.loads(snapshot[0]))).build()

    def related_context(self, event_ids: Sequence[str]) -> dict[str, list[str]]:
        if not event_ids or not self._has_table("incident_members"):
            return {"incidents": [], "rca_reports": [], "blast_radius_analyses": [], "rca_context": [], "blast_radius_context": []}
        ids = sorted(set(event_ids)); incident_set: set[str] = set()
        for start in range(0,len(ids),900):
            chunk=ids[start:start+900]; marks=",".join("?" for _ in chunk)
            incident_set.update(str(row[0]) for row in self.connection.execute(f"SELECT DISTINCT incident_id FROM incident_members WHERE event_id IN ({marks})",chunk))
        incidents = sorted(incident_set)
        if not incidents: return {"incidents": [], "rca_reports": [], "blast_radius_analyses": [], "rca_context": [], "blast_radius_context": []}
        imarks = ",".join("?" for _ in incidents)
        rca_context=[]
        if self._has_table("rca_investigations"):
            for row in self.connection.execute(f"SELECT investigation_id,report FROM rca_investigations WHERE incident_id IN ({imarks}) ORDER BY created_at,investigation_id", incidents):
                report=json.loads(row["report"]); candidates=list(report.get("hypotheses",[]))
                if report.get("leading_hypothesis"): candidates.append(report["leading_hypothesis"])
                rca_context.append({"investigation_id":str(row["investigation_id"]),"assessment_status":report.get("assessment_status"),
                    "candidate_service_ids":sorted({str(candidate["candidate_service"]) for candidate in candidates if candidate.get("candidate_service")})})
        blast_context=[]
        if self._has_table("blast_radius_analyses"):
            for row in self.connection.execute(f"SELECT analysis_id,payload FROM blast_radius_analyses WHERE incident_id IN ({imarks}) ORDER BY created_at,analysis_id", incidents):
                report=json.loads(row["payload"])
                blast_context.append({"analysis_id":str(row["analysis_id"]),"graph_version":report.get("graph_version"),
                    "root_service_id":report.get("root_service_id"),
                    "potentially_impacted_service_ids":sorted({str(x.get("service_id")) for x in report.get("impacted_services",[]) if x.get("service_id")})})
        return {"incidents": incidents, "rca_reports": [x["investigation_id"] for x in rca_context],
            "blast_radius_analyses": [x["analysis_id"] for x in blast_context],
            "rca_context":rca_context,"blast_radius_context":blast_context}

    def save_run(self, run_id: str, fingerprint: str, config: Mapping[str, Any], graph_version: str | None,
                 payload: Mapping[str, Any]) -> dict[str, Any]:
        existing = self.get_run_by_fingerprint(fingerprint)
        if existing: return existing
        created = _now(); encoded = _json(payload)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute("INSERT INTO intelligence_runs VALUES(?,?,?,?,?,?)",
                (run_id, fingerprint, created, _json(config), graph_version, encoded))
            for feature in payload.get("features", []):
                self.connection.execute("INSERT INTO intelligence_features VALUES(?,?,?,?)",
                    (run_id, feature["service_id"], feature["window_start"], _json(feature)))
            for baseline in payload.get("baselines", []):
                self.connection.execute("INSERT INTO intelligence_baselines VALUES(?,?,?,?,?)",
                    (run_id, baseline["baseline_version"], baseline["service_id"], baseline["target_window_start"], _json(baseline)))
            for finding in payload.get("findings", []):
                self.connection.execute("INSERT INTO intelligence_findings VALUES(?,?,?,?,?)",
                    (finding["finding_id"], run_id, finding["finding_type"], created, _json(finding)))
            for model in payload.get("model_artifacts", []):
                self.connection.execute("INSERT INTO intelligence_models VALUES(?,?,?,?)",
                    (run_id, model["artifact_id"], model["detector_version"], _json(model)))
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            # If another identical invocation committed first, return its immutable row.
            existing = self.get_run_by_fingerprint(fingerprint)
            if existing: return existing
            raise
        return {"run_id": run_id, "input_fingerprint": fingerprint, "created_at": created,
                "configuration": dict(config), "graph_version": graph_version, **dict(payload)}

    def get_run_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM intelligence_runs WHERE input_fingerprint=?", (fingerprint,)).fetchone()
        return self._run_dict(row) if row else None

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM intelligence_runs WHERE run_id=?", (run_id,)).fetchone()
        return self._run_dict(row) if row else None

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        return [{"run_id": r["run_id"], "input_fingerprint": r["input_fingerprint"], "created_at": r["created_at"], "graph_version": r["graph_version"], "finding_count": self.connection.execute("SELECT COUNT(*) FROM intelligence_findings WHERE run_id=?", (r["run_id"],)).fetchone()[0]} for r in self.connection.execute("SELECT * FROM intelligence_runs ORDER BY created_at DESC,run_id LIMIT ?", (limit,))]

    def save_evaluation(self, evaluation_id: str, payload: Mapping[str, Any]) -> None:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute("INSERT OR IGNORE INTO intelligence_evaluations VALUES(?,?,?)", (evaluation_id, _now(), _json(payload)))
            self.connection.commit()
        except Exception:
            self.connection.rollback(); raise

    def _run_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {"run_id": row["run_id"], "input_fingerprint": row["input_fingerprint"], "created_at": row["created_at"],
            "configuration": json.loads(row["config_json"]), "graph_version": row["graph_version"], **json.loads(row["payload_json"])}

    def _has_table(self, name: str) -> bool:
        return self.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

    def close(self) -> None: self.connection.close()
    def __enter__(self) -> "SQLiteIntelligenceStore": return self
    def __exit__(self, *_: object) -> None: self.close()


def _json(value: Any) -> str: return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
def _now() -> str: return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
