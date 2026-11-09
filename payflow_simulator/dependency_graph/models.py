"""Typed domain records for services, dependencies, graph validation, and impact."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class Service:
    service_id: str
    service_name: str
    description: str = ""
    service_type: str = "unknown"
    criticality: str = "unknown"
    business_capability: str = "unknown"
    environment: str = "development"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True, slots=True)
class Dependency:
    """`source_service_id` depends on `target_service_id` (source -> target)."""
    source_service_id: str
    target_service_id: str
    dependency_type: str = "other"
    importance: float = 1.0
    description: str = ""
    evidence_source: str = "configuration"
    confidence: float | None = None
    verification_status: str = "configured"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]: return asdict(self)

    @property
    def dependency_id(self) -> str:
        return f"{self.source_service_id}->{self.target_service_id}:{self.dependency_type}"


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    code: str
    severity: str
    message: str
    context: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True, slots=True)
class DependencyGraph:
    graph_version: str
    services: Mapping[str, Service]
    dependencies: tuple[Dependency, ...]
    findings: tuple[ValidationFinding, ...]
    config: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"graph_version": self.graph_version,
                "services": [v.to_dict() for _, v in sorted(self.services.items())],
                "dependencies": [d.to_dict() for d in self.dependencies],
                "findings": [f.to_dict() for f in self.findings], "config": dict(self.config)}


@dataclass(frozen=True, slots=True)
class ImpactedService:
    service_id: str
    service_name: str
    depth: int
    dependency_paths: tuple[tuple[str, ...], ...]
    impact_score: float
    score_breakdown: Mapping[str, Any]
    criticality: str
    business_capability: str
    evidence: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]: return asdict(self)
