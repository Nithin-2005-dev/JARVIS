"""Validated domain records for evidence-backed responder recommendations."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

RECOMMENDATION_TYPES = {"investigation", "diagnostic", "mitigation", "recovery", "prevention", "monitoring", "capacity", "configuration", "security"}
PRIORITIES = {"critical", "high", "medium", "low", "informational"}
CONFIDENCE_LABELS = {"strong_evidence", "moderate_evidence", "weak_evidence", "insufficient_evidence"}
STATUSES = {"proposed", "acknowledged", "in_progress", "completed", "dismissed", "superseded"}
RISK_LEVELS = {"low", "medium", "high"}


@dataclass(frozen=True, slots=True)
class Recommendation:
    recommendation_id: str
    incident_id: str | None
    analysis_run_id: str
    title: str
    description: str
    recommendation_type: str
    affected_services: tuple[str, ...]
    priority: str
    urgency: str
    confidence_label: str
    supporting_evidence: tuple[Mapping[str, Any], ...]
    contradictory_evidence: tuple[Mapping[str, Any], ...]
    assumptions: tuple[str, ...]
    expected_benefit: str
    risk_level: str
    possible_side_effects: tuple[str, ...]
    prerequisites: tuple[str, ...]
    implementation_steps: tuple[str, ...]
    verification_steps: tuple[str, ...]
    rollback_guidance: tuple[str, ...]
    source_stage: str
    related_finding_ids: tuple[str, ...] = ()
    related_rca_ids: tuple[str, ...] = ()
    related_blast_radius_ids: tuple[str, ...] = ()
    status: str = "proposed"
    created_at: str = ""
    configuration_version: str = "recommendations-v1"
    rule_id: str = ""
    score: float = 0.0
    score_breakdown: Mapping[str, float] = field(default_factory=dict)
    scenario_key: str = ""

    def __post_init__(self) -> None:
        if not self.recommendation_id or not self.analysis_run_id or not self.title.strip():
            raise ValueError("recommendation id, analysis run id, and title are required")
        if self.recommendation_type not in RECOMMENDATION_TYPES: raise ValueError("invalid recommendation_type")
        if self.priority not in PRIORITIES: raise ValueError("invalid priority")
        if self.confidence_label not in CONFIDENCE_LABELS: raise ValueError("invalid confidence_label")
        if self.status not in STATUSES: raise ValueError("invalid status")
        if self.risk_level not in RISK_LEVELS: raise ValueError("invalid risk_level")
        if not self.supporting_evidence: raise ValueError("recommendation requires at least one supporting evidence reference")
        if self.recommendation_type in {"investigation", "diagnostic", "mitigation", "recovery", "prevention", "monitoring", "capacity", "configuration", "security"} and not self.verification_steps:
            raise ValueError("actionable recommendation requires verification steps")
        if not 0 <= self.score <= 1: raise ValueError("heuristic recommendation score must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True, slots=True)
class RecommendationConfig:
    version: str = "recommendations-v1"
    max_items: int = 30
    max_event_evidence: int = 20
    min_evidence: int = 1
    score_weights: Mapping[str, float] = field(default_factory=lambda: {
        "severity": .18, "evidence": .24, "urgency": .14, "criticality": .12,
        "potential_impact": .10, "benefit": .12, "prerequisites": .10,
    })
    risk_penalties: Mapping[str, float] = field(default_factory=lambda: {"low": 0.0, "medium": .12, "high": .30})

    def __post_init__(self) -> None:
        if self.max_items < 1 or self.max_event_evidence < 1 or self.min_evidence < 1: raise ValueError("recommendation limits must be positive")
        if any(float(v) < 0 for v in self.score_weights.values()): raise ValueError("score weights cannot be negative")
        if any(not 0 <= float(v) <= 1 for v in self.risk_penalties.values()): raise ValueError("risk penalties must be in [0, 1]")
        if not self.version: raise ValueError("configuration version is required")

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True, slots=True)
class RecommendationFeedback:
    recommendation_id: str
    outcome_status: str
    observed_evidence: tuple[Mapping[str, Any], ...] = ()
    responder_notes: str = ""
    actual_result: str = ""
    related_incident_state: str | None = None
    recorded_at: str = ""

    def __post_init__(self) -> None:
        if self.outcome_status not in {"successful", "unsuccessful", "inconclusive", "not_attempted"}:
            raise ValueError("invalid feedback outcome_status")
        if not self.recommendation_id: raise ValueError("recommendation_id is required")

    def to_dict(self) -> dict[str, Any]: return asdict(self)
