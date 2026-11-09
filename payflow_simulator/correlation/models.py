"""Immutable correlation evidence, relationships, incidents, and reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class CorrelationEvidence:
    source_event_id: str
    target_event_id: str
    strategy: str
    description: str
    supporting_attributes: dict[str, Any]
    time_difference_seconds: float | None
    strategy_score: float
    confidence_score: float
    evaluated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CorrelationEdge:
    source_event_id: str
    target_event_id: str
    evidence: tuple[CorrelationEvidence, ...]
    confidence_score: float
    heuristic: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"source_event_id": self.source_event_id, "target_event_id": self.target_event_id,
                "evidence": [item.to_dict() for item in self.evidence],
                "confidence_score": self.confidence_score, "score_kind": "heuristic_confidence"}


@dataclass(frozen=True, slots=True)
class CorrelationReport:
    run_id: str
    events_received: int
    candidate_pairs: int
    relationships_accepted: int
    incidents_created: int
    duration_seconds: float
    candidate_generation_seconds: float
    evaluation_seconds: float
    events_per_second: float
    late_events: int
    skipped_events: int
    trace_diagnostics: int = 0
    memory_peak_bytes: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
