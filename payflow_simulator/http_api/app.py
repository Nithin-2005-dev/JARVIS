"""FastAPI boundary for the local J.A.R.V.I.S. Command Center."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .service import DashboardService
from .schemas import IncidentDetailResponse, OverviewResponse, Page, Record, ServiceListResponse

logger = logging.getLogger("jarvis.http_api")


class StatusUpdate(BaseModel):
    status: Literal["acknowledged", "in_progress", "completed", "dismissed", "superseded"]
    reason: str = Field(default="", max_length=1000)
    notes: str = Field(default="", max_length=4000)


class Feedback(BaseModel):
    outcome_status: Literal["successful", "unsuccessful", "inconclusive", "not_attempted"]
    observed_evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    responder_notes: str = Field(default="", max_length=4000)
    actual_result: str = Field(default="", max_length=2000)
    related_incident_state: str | None = Field(default=None, max_length=100)


def create_app(database: str | None = None, *, allowed_origins: list[str] | None = None) -> FastAPI:
    app = FastAPI(title="J.A.R.V.I.S. Command Center API", version="1.0.0", docs_url="/api/docs")
    origins = allowed_origins if allowed_origins is not None else [x.strip() for x in os.getenv("JARVIS_CORS_ORIGINS", "http://localhost:3000").split(",") if x.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "PATCH", "POST"], allow_headers=["Content-Type"], allow_credentials=False)
    service = DashboardService(database)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.exception("Unhandled API error on %s", request.url.path)
        return __import__("fastapi").responses.JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "The request could not be completed."}})

    def missing(kind: str, identifier: str):
        raise HTTPException(404, detail={"code": "not_found", "message": f"{kind} '{identifier}' was not found."})

    @app.get("/api/v1/health")
    def health(): return {"status": "ok", "storage": "sqlite", "database_configured": True}

    @app.get("/api/v1/overview", response_model=OverviewResponse)
    def overview(): return service.overview()

    @app.get("/api/v1/incidents", response_model=Page[Record])
    def incidents(status: str | None = None, severity: str | None = None, service_id: str | None = None,
                  search: str | None = Query(default=None, max_length=200), sort: Literal["activity", "severity"] = "activity",
                  start_time: datetime | None = None, end_time: datetime | None = None,
                  page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)):
        rows = service.incidents(status=status)
        if severity: rows = [x for x in rows if str(x.get("severity", "")).lower() == severity.lower()]
        if service_id: rows = [x for x in rows if service_id in _incident_service_ids(service, x["incident_id"])]
        if search: rows = [x for x in rows if search.lower() in str(x.get("summary", "")).lower() or search.lower() in x["incident_id"].lower()]
        if start_time: rows = [x for x in rows if _time_in_range(x.get("first_observed_at"), start_time, lower=True)]
        if end_time: rows = [x for x in rows if _time_in_range(x.get("last_observed_at"), end_time, lower=False)]
        ranks = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        if sort == "severity": rows.sort(key=lambda x: (ranks.get(str(x.get("severity", "unknown")).lower(), 4), x.get("updated_at", "")))
        else: rows.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        start = (page - 1) * page_size
        return {"items": rows[start:start + page_size], "page": page, "page_size": page_size, "total": len(rows)}

    @app.get("/api/v1/incidents/{incident_id}", response_model=IncidentDetailResponse)
    def incident(incident_id: str):
        result = service.incident(incident_id)
        if result is None: missing("incident", incident_id)
        return result

    @app.get("/api/v1/incidents/{incident_id}/events")
    def incident_events(incident_id: str):
        result = service.incident(incident_id)
        if result is None: missing("incident", incident_id)
        return {"items": result["events"], "correlation_evidence": result["correlation_evidence"]}

    @app.get("/api/v1/incidents/{incident_id}/rca")
    def incident_rca(incident_id: str):
        result = service.incident(incident_id)
        if result is None: missing("incident", incident_id)
        return {"report": result["rca"]}

    @app.get("/api/v1/incidents/{incident_id}/blast-radius")
    def incident_blast_radius(incident_id: str):
        result = service.incident(incident_id)
        if result is None: missing("incident", incident_id)
        return {"items": result["blast_radius"]}

    @app.get("/api/v1/incidents/{incident_id}/intelligence")
    def incident_intelligence(incident_id: str):
        result = service.incident(incident_id)
        if result is None: missing("incident", incident_id)
        return {"items": result["intelligence"]}

    @app.get("/api/v1/incidents/{incident_id}/recommendations")
    def incident_recommendations(incident_id: str):
        result = service.incident(incident_id)
        if result is None: missing("incident", incident_id)
        return {"items": result["recommendations"]}

    @app.get("/api/v1/services", response_model=ServiceListResponse)
    def services():
        items = service.services()
        return {"items": items, "total": len(items), "service_health_available": False}

    @app.get("/api/v1/services/{service_id}")
    def service_detail(service_id: str):
        result = service.service(service_id)
        if result is None: missing("service", service_id)
        return result

    @app.get("/api/v1/services/{service_id}/dependencies")
    def service_dependencies(service_id: str):
        result = service.service(service_id)
        if result is None: missing("service", service_id)
        return {"incoming": result["incoming_dependencies"], "outgoing": result["outgoing_dependencies"], "direction": "A -> B means A depends on B"}

    @app.get("/api/v1/services/{service_id}/recommendations")
    def service_recommendations(service_id: str):
        result = service.service(service_id)
        if result is None: missing("service", service_id)
        return {"items": result["recommendations"]}

    @app.get("/api/v1/intelligence/findings")
    def findings(limit: int = Query(100, ge=1, le=500), service_id: str | None = None, finding_type: str | None = None):
        rows = service.findings(limit=limit)
        if service_id: rows = [x for x in rows if service_id in x.get("affected_service_ids", [])]
        if finding_type: rows = [x for x in rows if x.get("finding_type") == finding_type]
        return {"items": rows, "total": len(rows)}

    @app.get("/api/v1/intelligence/findings/{finding_id}")
    def finding(finding_id: str):
        result = service.finding(finding_id)
        if result is None: missing("finding", finding_id)
        return result

    @app.get("/api/v1/recommendations")
    def recommendations(status: str | None = None, category: str | None = None, priority: str | None = None,
                        risk: str | None = None, service_id: str | None = None, incident_id: str | None = None,
                        limit: int = Query(100, ge=1, le=500)):
        rows = service.recommendations(status=status, service_id=service_id, incident_id=incident_id, limit=limit)
        for field, value in (("recommendation_type", category), ("priority", priority), ("risk_level", risk)):
            if value: rows = [x for x in rows if x.get(field) == value]
        return {"items": rows, "total": len(rows)}

    @app.get("/api/v1/recommendations/{recommendation_id}")
    def recommendation(recommendation_id: str):
        result = service.recommendation(recommendation_id)
        if result is None: missing("recommendation", recommendation_id)
        return {"recommendation": result, "history": service.recommendation_history(recommendation_id)}

    @app.patch("/api/v1/recommendations/{recommendation_id}/status")
    def update_status(recommendation_id: str, payload: StatusUpdate):
        try: return service.update_recommendation(recommendation_id, payload.status, payload.reason, payload.notes)
        except KeyError: missing("recommendation", recommendation_id)
        except ValueError as exc: raise HTTPException(409, detail={"code": "invalid_transition", "message": str(exc)}) from exc

    @app.post("/api/v1/recommendations/{recommendation_id}/feedback", status_code=201)
    def feedback(recommendation_id: str, payload: Feedback):
        data = payload.model_dump() | {"recommendation_id": recommendation_id}
        try: return service.feedback(data)
        except KeyError: missing("recommendation", recommendation_id)

    @app.get("/api/v1/history")
    def history(limit: int = Query(100, ge=1, le=500)): return service.history(limit)

    return app


def _incident_service_ids(service: DashboardService, incident_id: str) -> set[str]:
    value = service.incident(incident_id)
    return {str((e.get("original_event") or e).get("service") or e.get("service_id")) for e in (value or {}).get("events", [])}


def _time_in_range(value: str | None, bound: datetime, *, lower: bool) -> bool:
    if not value: return False
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if observed.tzinfo is None: observed = observed.replace(tzinfo=timezone.utc)
        if bound.tzinfo is None: bound = bound.replace(tzinfo=timezone.utc)
        return observed >= bound if lower else observed <= bound
    except ValueError:
        return False


app = create_app()
