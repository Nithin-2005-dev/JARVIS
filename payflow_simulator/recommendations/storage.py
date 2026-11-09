"""SQLite persistence for Stage 8 with read-only access to Stage 3–7 snapshots."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


def _json(value: Any) -> str: return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
def _now() -> str: return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class SQLiteRecommendationStore:
    """Persist Stage 8 runs and lifecycle records; previous-stage tables are only read."""
    def __init__(self, path: str | Path):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout=30000")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS recommendation_runs(run_id TEXT PRIMARY KEY,input_fingerprint TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,configuration_json TEXT NOT NULL,rules_json TEXT NOT NULL,payload_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS recommendation_snapshots(run_id TEXT NOT NULL,recommendation_id TEXT NOT NULL,payload_json TEXT NOT NULL,PRIMARY KEY(run_id,recommendation_id));
        CREATE TABLE IF NOT EXISTS recommendations(recommendation_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,incident_id TEXT,service_id TEXT,status TEXT NOT NULL,payload_json TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS recommendation_incident_idx ON recommendations(incident_id,status);
        CREATE INDEX IF NOT EXISTS recommendation_service_idx ON recommendations(service_id,status);
        CREATE TABLE IF NOT EXISTS recommendation_rules(rule_id TEXT NOT NULL,rule_version TEXT NOT NULL,payload_json TEXT NOT NULL,PRIMARY KEY(rule_id,rule_version));
        CREATE TABLE IF NOT EXISTS recommendation_history(history_id INTEGER PRIMARY KEY AUTOINCREMENT,recommendation_id TEXT NOT NULL,action TEXT NOT NULL,recorded_at TEXT NOT NULL,detail_json TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS recommendation_history_idx ON recommendation_history(recommendation_id,history_id);
        CREATE TABLE IF NOT EXISTS recommendation_feedback(feedback_id TEXT PRIMARY KEY,recommendation_id TEXT NOT NULL,recorded_at TEXT NOT NULL,payload_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS recommendation_evaluations(evaluation_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,payload_json TEXT NOT NULL);
        """)
        self.connection.commit()

    def _has(self, table: str) -> bool:
        return self.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None

    def load_context(self, *, incident_id: str | None = None, service_id: str | None = None) -> dict[str, Any]:
        """Read exact existing snapshots and event payloads without updating prior stages."""
        if not incident_id and not service_id: return {"context_status":"insufficient_context", "reason":"incident_id or service_id is required"}
        events: list[dict[str, Any]] = []; incident: dict[str, Any] | None = None
        if incident_id:
            if not self._has("incidents"): return {"context_status":"insufficient_context", "reason":"Stage 4 incident storage is unavailable"}
            row = self.connection.execute("SELECT * FROM incidents WHERE incident_id=?", (incident_id,)).fetchone()
            if not row: return {"context_status":"insufficient_context", "reason":f"unknown incident: {incident_id}"}
            incident = dict(row)
            if self._has("incident_members") and self._has("processed_events"):
                events = [json.loads(r[0]) for r in self.connection.execute("SELECT p.payload FROM incident_members m JOIN processed_events p USING(event_id) WHERE m.incident_id=? ORDER BY p.event_id", (incident_id,))]
        elif service_id and self._has("processed_events"):
            for row in self.connection.execute("SELECT payload FROM processed_events ORDER BY event_id"):
                event = json.loads(row[0]); original = event.get("original_event", event)
                if str(original.get("service", "")) == service_id: events.append(event)
        rca = None
        if incident_id and self._has("rca_investigations"):
            row = self.connection.execute("SELECT investigation_id,report,created_at FROM rca_investigations WHERE incident_id=? ORDER BY created_at DESC,investigation_id DESC LIMIT 1", (incident_id,)).fetchone()
            if row: rca = {"investigation_id":row[0], "report":json.loads(row[1]), "created_at":row[2]}
        findings: list[dict[str, Any]] = []; intelligence_run_id: str | None=None
        if self._has("intelligence_findings"):
            latest_run = None
            if self._has("intelligence_runs"):
                latest = self.connection.execute("SELECT run_id FROM intelligence_runs ORDER BY created_at DESC,run_id DESC LIMIT 1").fetchone()
                if latest:
                    latest_run = str(latest[0]); intelligence_run_id=latest_run
            query = "SELECT payload_json FROM intelligence_findings" + (" WHERE run_id=?" if latest_run else "") + " ORDER BY finding_id"
            findings = [json.loads(r[0]) for r in self.connection.execute(query, (latest_run,) if latest_run else ())]
            if incident_id: findings = [f for f in findings if incident_id in f.get("related_incidents", []) or _finding_overlaps(f, events)]
            elif service_id: findings = [f for f in findings if service_id in f.get("affected_service_ids", [])]
        blast: list[dict[str, Any]] = []
        if self._has("blast_radius_analyses"):
            if incident_id:
                blast = [json.loads(r[0]) | {"analysis_id":r[1]} for r in self.connection.execute("SELECT payload,analysis_id FROM blast_radius_analyses WHERE incident_id=? ORDER BY created_at DESC,analysis_id DESC", (incident_id,))]
            elif service_id:
                blast = [json.loads(r[0]) | {"analysis_id":r[1]} for r in self.connection.execute("SELECT payload,analysis_id FROM blast_radius_analyses WHERE root_service_id=? ORDER BY created_at DESC,analysis_id DESC", (service_id,))]
        selected_service = service_id
        if incident and not selected_service:
            services = sorted({_service(e) for e in events} - {"unknown"})
            selected_service = services[0] if len(services) == 1 else None
        status = "ready" if events or rca or findings or blast else "insufficient_context"
        return {"context_status":status, "incident_id":incident_id, "service_id":service_id,
                "selected_service_id":selected_service, "incident":incident, "events":events,
                "rca":rca, "intelligence_findings":findings, "intelligence_run_id":intelligence_run_id,
                "blast_radius_analyses":blast}

    def save_run(self, run_id: str, fingerprint: str, config: Mapping[str, Any], rules: list[Mapping[str, Any]], payload: Mapping[str, Any]) -> dict[str, Any]:
        existing = self.get_run_by_fingerprint(fingerprint)
        if existing: return existing
        created = _now(); encoded = _json(payload)
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute("INSERT INTO recommendation_runs VALUES(?,?,?,?,?,?)", (run_id,fingerprint,created,_json(config),_json(rules),encoded))
            for rule in rules:
                self.connection.execute("INSERT OR IGNORE INTO recommendation_rules VALUES(?,?,?)", (rule["rule_id"],rule["version"],_json(rule)))
            for item in payload.get("recommendations", []):
                self.connection.execute("INSERT OR IGNORE INTO recommendation_snapshots VALUES(?,?,?)", (run_id,item["recommendation_id"],_json(item)))
                service = item.get("affected_services", [None])[0] if item.get("affected_services") else None
                self.connection.execute("INSERT OR IGNORE INTO recommendations VALUES(?,?,?,?,?,?,?)", (item["recommendation_id"],run_id,item.get("incident_id"),service,item.get("status","proposed"),_json(item),created))
                self.connection.execute("INSERT INTO recommendation_history(recommendation_id,action,recorded_at,detail_json) VALUES(?,?,?,?)", (item["recommendation_id"],"proposed",created,_json({"run_id":run_id,"rule_id":item.get("rule_id")})))
            self.connection.commit()
        except Exception:
            self.connection.rollback(); existing=self.get_run_by_fingerprint(fingerprint)
            if existing: return existing
            raise
        # Return the JSON round-tripped immutable snapshot so the first and every
        # subsequent invocation have identical tuple/list representations.
        return self.get_run(run_id) or {"run_id":run_id,"input_fingerprint":fingerprint,"created_at":created,"configuration":dict(config),**dict(payload)}

    def get_run_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        row=self.connection.execute("SELECT * FROM recommendation_runs WHERE input_fingerprint=?",(fingerprint,)).fetchone()
        return self._run_dict(row) if row else None

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row=self.connection.execute("SELECT * FROM recommendation_runs WHERE run_id=?",(run_id,)).fetchone()
        return self._run_dict(row) if row else None

    def _run_dict(self,row: sqlite3.Row) -> dict[str,Any]:
        return {"run_id":row["run_id"],"input_fingerprint":row["input_fingerprint"],"created_at":row["created_at"],"configuration":json.loads(row["configuration_json"]),**json.loads(row["payload_json"])}

    def list_recommendations(self, *, incident_id: str | None = None, service_id: str | None = None, status: str | None = None, limit: int = 100) -> list[dict[str,Any]]:
        clauses=[]; params=[]
        if incident_id is not None: clauses.append("incident_id=?"); params.append(incident_id)
        if service_id is not None: clauses.append("service_id=?"); params.append(service_id)
        if status is not None: clauses.append("status=?"); params.append(status)
        query="SELECT payload_json,status FROM recommendations"+(" WHERE "+" AND ".join(clauses) if clauses else "")+" ORDER BY updated_at DESC,recommendation_id LIMIT ?"; params.append(limit)
        return [json.loads(r[0]) | {"status":r[1]} for r in self.connection.execute(query,params)]

    def get_recommendation(self, recommendation_id: str) -> dict[str,Any] | None:
        row=self.connection.execute("SELECT payload_json,status FROM recommendations WHERE recommendation_id=?",(recommendation_id,)).fetchone()
        return json.loads(row[0]) | {"status":row[1]} if row else None

    def update_status(self, recommendation_id: str, status: str, *, reason: str = "", notes: str = "") -> dict[str,Any]:
        allowed={"proposed":{"acknowledged","dismissed","superseded"},"acknowledged":{"in_progress","dismissed","superseded"},"in_progress":{"completed","dismissed","superseded"},"completed":set(),"dismissed":set(),"superseded":set()}
        if status not in {"proposed","acknowledged","in_progress","completed","dismissed","superseded"}: raise ValueError("invalid recommendation status")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row=self.connection.execute("SELECT status,payload_json FROM recommendations WHERE recommendation_id=?",(recommendation_id,)).fetchone()
            if not row: raise KeyError(f"unknown recommendation: {recommendation_id}")
            old=str(row[0]); payload=json.loads(row[1])
            if status not in allowed[old]: raise ValueError(f"invalid status transition: {old} -> {status}")
            if status=="dismissed" and not reason.strip(): raise ValueError("dismissal reason is required")
            payload["status"]=status
            if notes: payload.setdefault("lifecycle_notes",[]).append(notes)
            now=_now()
            self.connection.execute("UPDATE recommendations SET status=?,payload_json=?,updated_at=? WHERE recommendation_id=?",(status,_json(payload),now,recommendation_id))
            self.connection.execute("INSERT INTO recommendation_history(recommendation_id,action,recorded_at,detail_json) VALUES(?,?,?,?)",(recommendation_id,status,now,_json({"previous_status":old,"reason":reason,"notes":notes})))
            self.connection.commit(); return payload
        except Exception:
            self.connection.rollback(); raise

    def history(self, recommendation_id: str) -> list[dict[str,Any]]:
        return [{"history_id":r[0],"action":r[1],"recorded_at":r[2],"detail":json.loads(r[3])} for r in self.connection.execute("SELECT history_id,action,recorded_at,detail_json FROM recommendation_history WHERE recommendation_id=? ORDER BY history_id",(recommendation_id,))]

    def record_feedback(self, feedback: Mapping[str,Any]) -> dict[str,Any]:
        if not self.get_recommendation(str(feedback["recommendation_id"])): raise KeyError(f"unknown recommendation: {feedback['recommendation_id']}")
        payload=dict(feedback)
        if not payload.get("recorded_at"): payload["recorded_at"]=_now()
        fingerprint=hashlib.sha256(_json(payload).encode()).hexdigest()
        self.connection.execute("INSERT OR IGNORE INTO recommendation_feedback VALUES(?,?,?,?)",(fingerprint,payload["recommendation_id"],payload["recorded_at"],_json(payload))); self.connection.commit()
        return payload

    def feedback_history(self, recommendation_id: str) -> list[dict[str,Any]]:
        return [json.loads(r[0]) for r in self.connection.execute("SELECT payload_json FROM recommendation_feedback WHERE recommendation_id=? ORDER BY recorded_at,feedback_id",(recommendation_id,))]

    def save_evaluation(self, evaluation_id: str, payload: Mapping[str,Any]) -> None:
        self.connection.execute("INSERT OR IGNORE INTO recommendation_evaluations VALUES(?,?,?)",(evaluation_id,_now(),_json(payload))); self.connection.commit()

    def close(self) -> None: self.connection.close()
    def __enter__(self) -> "SQLiteRecommendationStore": return self
    def __exit__(self,*_: object) -> None: self.close()


def _service(event: Mapping[str,Any]) -> str:
    return str(event.get("original_event",event).get("service",event.get("service_id", "unknown")))

def _finding_overlaps(finding: Mapping[str,Any], events: list[Mapping[str,Any]]) -> bool:
    event_ids={str(e.get("event_id") or e.get("original_event",{}).get("event_id")) for e in events}
    refs=finding.get("evidence_references",[])
    return any(str(ref.get("event_id")) in event_ids for ref in refs if isinstance(ref,Mapping))
