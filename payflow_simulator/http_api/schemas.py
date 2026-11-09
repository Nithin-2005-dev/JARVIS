"""Typed envelope schemas used by the versioned HTTP interface."""
from __future__ import annotations

from typing import Any, Generic, TypeVar
from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Record(BaseModel):
    """A versioned API resource, allowing additive Stage payload attributes."""
    model_config = ConfigDict(extra="allow")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(ge=0)
    page: int | None = None
    page_size: int | None = None


class ServiceListResponse(Page[Record]):
    service_health_available: bool = False


class OverviewResponse(BaseModel):
    incident_count: int
    active_incident_count: int
    critical_high_count: int
    open_recommendation_count: int
    incidents: list[Record]
    recent_findings: list[Record]
    severity_distribution: dict[str, int]
    incident_trend: list[Record] = Field(default_factory=list)
    services: list[Record]
    service_health_available: bool


class IncidentDetailResponse(BaseModel):
    incident: Record
    events: list[Record]
    correlation_evidence: list[Record]
    history: list[Record]
    rca: dict[str, Any] | None
    rca_history: list[Record] = Field(default_factory=list)
    blast_radius: list[Record]
    intelligence: list[Record]
    recommendations: list[Record]
