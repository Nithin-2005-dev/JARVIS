"""Compose existing Stage 3–8 stores for HTTP responses; no analysis is reimplemented."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..correlation.storage import SQLiteCorrelationStore
from ..dependency_graph.graph_store import SQLiteDependencyGraphStore
from ..intelligence.storage import SQLiteIntelligenceStore
from ..rca.storage import SQLiteRCAStore
from ..recommendations.storage import SQLiteRecommendationStore


class DashboardService:
    """Short-lived facade over existing SQLite store APIs."""

    def __init__(self, database: str | Path | None = None):
        self.database = Path(database or os.getenv("JARVIS_DATABASE", "data/events.sqlite"))

    def _stores(self):
        # Stores own SQLite connections. Close every connection at request end.
        return (
            SQLiteCorrelationStore(self.database), SQLiteRCAStore(self.database),
            SQLiteDependencyGraphStore(self.database), SQLiteIntelligenceStore(self.database),
            SQLiteRecommendationStore(self.database),
        )

    def _collect(self, operation):
        stores = self._stores()
        try:
            return operation(*stores)
        finally:
            for store in stores:
                store.close()

    def overview(self) -> dict[str, Any]:
        def read(correlation, rca, graph, intelligence, recommendations):
            incidents = correlation.list_incidents(status=None)
            recs = recommendations.list_recommendations(limit=1000)
            findings = []
            for run in intelligence.history(limit=20):
                payload = intelligence.get_run(run["run_id"]) or {}
                findings.extend(payload.get("findings", []))
            incidents = sorted(incidents, key=lambda x: x.get("updated_at", ""), reverse=True)
            active = [x for x in incidents if x.get("status") == "active"]
            daily: dict[str, int] = {}
            for item in incidents:
                observed = item.get("first_observed_at")
                if observed: daily[str(observed)[:10]] = daily.get(str(observed)[:10], 0) + 1
            return {"incident_count": len(incidents), "active_incident_count": len(active),
                    "critical_high_count": sum(x.get("severity") in {"critical", "high"} for x in active),
                    "open_recommendation_count": sum(x.get("status") in {"proposed", "acknowledged", "in_progress"} for x in recs),
                    "incidents": incidents[:10], "recent_findings": sorted(findings, key=lambda x: x.get("created_at", ""), reverse=True)[:8],
                    "severity_distribution": _counts(x.get("severity", "unknown") for x in incidents),
                    "incident_trend": [{"date": day, "count": daily[day]} for day in sorted(daily)],
                    "services": _graph_services(graph.graph_snapshot()), "service_health_available": False}
        return self._collect(read)

    def incidents(self, *, status: str | None = None) -> list[dict[str, Any]]:
        def read(c, *_):
            rows = c.list_incidents(status=status)
            for row in rows:
                row.update(_observed_bounds(c.incident_events(row["incident_id"])))
            return rows
        return self._collect(read)

    def incident(self, incident_id: str) -> dict[str, Any] | None:
        def read(c, r, g, i, rec):
            incident = c.get_incident(incident_id)
            if incident is None: return None
            graph = g.graph_snapshot()
            analyses = []
            for item in g.analysis_history(incident_id=incident_id):
                report = g.analysis(item["analysis_id"])
                if report is not None:
                    analyses.append(report | {"analysis_id": item["analysis_id"],
                        "services": _graph_services(graph), "dependencies": (graph or {}).get("dependencies", [])})
            events = c.incident_events(incident_id)
            incident = dict(incident) | _observed_bounds(events)
            return {"incident": incident, "events": events,
                    "correlation_evidence": c.incident_evidence(incident_id),
                    "history": c.incident_history(incident_id),
                    "rca": r.latest_investigation(incident_id),
                    "rca_history": r.history(incident_id),
                    "blast_radius": analyses,
                    "intelligence": _findings_for_incident(i, incident_id),
                    "recommendations": rec.list_recommendations(incident_id=incident_id, limit=500)}
        return self._collect(read)

    def services(self) -> list[dict[str, Any]]:
        def read(c, r, g, i, rec):
            snapshot = g.graph_snapshot()
            services = _graph_services(snapshot)
            for service in services:
                service["related_incidents"] = [inc["incident_id"] for inc in c.list_incidents(status=None)
                    if service["service_id"] in _incident_services(c.incident_events(inc["incident_id"]))]
                service["recommendation_count"] = len(rec.list_recommendations(service_id=service["service_id"], limit=500))
            return services
        return self._collect(read)

    def service(self, service_id: str) -> dict[str, Any] | None:
        def read(c, r, g, i, rec):
            snapshot = g.graph_snapshot()
            services = _graph_services(snapshot)
            found = next((x for x in services if x["service_id"] == service_id), None)
            if found is None: return None
            item = dict(found)
            deps = (snapshot or {}).get("dependencies", [])
            item["graph_services"] = [dict(x) for x in services]
            item["graph_dependencies"] = deps
            item["graph_findings"] = (snapshot or {}).get("findings", [])
            item["incoming_dependencies"] = [d for d in deps if d.get("target_service_id") == service_id]
            item["outgoing_dependencies"] = [d for d in deps if d.get("source_service_id") == service_id]
            item["related_incidents"] = [inc for inc in c.list_incidents(status=None)
                if service_id in _incident_services(c.incident_events(inc["incident_id"]))]
            item["analyses"] = g.analysis_history(service_id=service_id)
            item["recommendations"] = rec.list_recommendations(service_id=service_id, limit=200)
            item["findings"] = _findings_for_service(i, service_id)
            return item
        return self._collect(read)

    def findings(self, *, limit: int = 100) -> list[dict[str, Any]]:
        def read(c, r, g, i, rec):
            out = []
            for row in i.history(limit=100):
                out.extend((i.get_run(row["run_id"]) or {}).get("findings", []))
            out.sort(key=lambda x: (x.get("created_at", ""), x.get("finding_id", "")), reverse=True)
            return out[:limit]
        return self._collect(read)

    def finding(self, finding_id: str) -> dict[str, Any] | None:
        return next((x for x in self.findings(limit=10000) if x.get("finding_id") == finding_id), None)

    def recommendations(self, *, status: str | None = None, service_id: str | None = None,
                        incident_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        def read(c, r, g, i, rec):
            rows = rec.list_recommendations(incident_id=incident_id, service_id=service_id, status=status, limit=limit)
            for item in rows:
                rid = item["recommendation_id"]
                item["status_history"] = rec.history(rid)
                item["feedback_history"] = rec.feedback_history(rid)
            return rows
        return self._collect(read)

    def recommendation(self, recommendation_id: str) -> dict[str, Any] | None:
        return self._collect(lambda c, r, g, i, rec: rec.get_recommendation(recommendation_id))

    def update_recommendation(self, recommendation_id: str, status: str, reason: str = "", notes: str = ""):
        return self._collect(lambda c, r, g, i, rec: rec.update_status(recommendation_id, status, reason=reason, notes=notes))

    def recommendation_history(self, recommendation_id: str):
        def read(c, r, g, i, rec):
            if not rec.get_recommendation(recommendation_id): return None
            return {"status_history": rec.history(recommendation_id), "feedback": rec.feedback_history(recommendation_id)}
        return self._collect(read)

    def feedback(self, payload: dict[str, Any]):
        return self._collect(lambda c, r, g, i, rec: rec.record_feedback(payload))

    def history(self, limit: int = 100):
        def read(c, r, g, i, rec):
            return {"incidents": [{"incident_id": x["incident_id"], "history": c.incident_history(x["incident_id"])} for x in c.list_incidents(status=None)],
                    "rca_investigations": [{"incident_id": x["incident_id"], "history": r.history(x["incident_id"])} for x in c.list_incidents(status=None)],
                    "recommendation_runs": rec.list_recommendations(limit=limit),
                    "intelligence_runs": i.history(limit=min(limit, 500)),
                    "blast_radius_analyses": g.analysis_history()[:limit]}
        return self._collect(read)


def _graph_services(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    return (snapshot or {}).get("services", [])


def _incident_services(events: list[dict[str, Any]]) -> set[str]:
    return {str((e.get("original_event") or e).get("service") or e.get("service_id")) for e in events
            if (e.get("original_event") or e).get("service") or e.get("service_id")}


def _counts(values):
    result: dict[str, int] = {}
    for value in values: result[str(value)] = result.get(str(value), 0) + 1
    return result


def _observed_bounds(events: list[dict[str, Any]]) -> dict[str, str | None]:
    timestamps = []
    for event in events:
        original = event.get("original_event") or event
        timestamp = original.get("timestamp")
        if isinstance(timestamp, str) and timestamp:
            timestamps.append(timestamp)
    return {"first_observed_at": min(timestamps) if timestamps else None,
            "last_observed_at": max(timestamps) if timestamps else None}


def _findings_for_incident(store, incident_id: str) -> list[dict[str, Any]]:
    return [f for f in _all_findings(store) if incident_id in f.get("related_incidents", [])]


def _findings_for_service(store, service_id: str) -> list[dict[str, Any]]:
    return [f for f in _all_findings(store) if service_id in f.get("affected_service_ids", [])]


def _all_findings(store) -> list[dict[str, Any]]:
    out = []
    for row in store.history(limit=100): out.extend((store.get_run(row["run_id"]) or {}).get("findings", []))
    return out
