"""Configurable transparent heuristic RCA settings."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class RCAConfig:
    """Weights are evidence contributions, not calibrated probabilities."""
    evidence_weights: Mapping[str, float] = field(default_factory=lambda: {
        "initiating_failure": 0.8, "resource_exhaustion": 1.0,
        "infrastructure_failure": 0.9, "dependency_path": 0.45,
        "correlation": 0.35, "resource_context": 0.35, "pattern": 0.35, "temporal_precedence": 0.15,
    })
    contradictory_weight: float = 0.65
    evidence_reliability: Mapping[str, float] = field(default_factory=lambda: {
        "event_fact": 1.0, "stage3_pattern": 0.6, "stage4_correlation": 0.55,
        "configured_dependency": 0.5,
    })
    minimum_supporting_families: int = 2
    minimum_heuristic_score: float = 0.45
    competing_margin: float = 0.12
    service_dependencies: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: {
        "api-gateway": ("authentication-service", "payment-service"),
        "authentication-service": ("payment-service",),
        "payment-service": ("database-service", "notification-service"),
    })
    abnormal_severities: tuple[str, ...] = ("ERROR", "CRITICAL", "FATAL")

    def __post_init__(self) -> None:
        if any(not 0 <= float(x) <= 1 for x in self.evidence_weights.values()):
            raise ValueError("evidence weights must be in [0, 1]")
        if any(not 0 <= float(x) <= 1 for x in self.evidence_reliability.values()):
            raise ValueError("evidence reliability must be in [0, 1]")
        if not 0 <= self.contradictory_weight <= 1 or not 0 <= self.minimum_heuristic_score <= 1:
            raise ValueError("scoring thresholds must be in [0, 1]")
        if self.minimum_supporting_families < 1 or not 0 <= self.competing_margin <= 1:
            raise ValueError("invalid candidate thresholds")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["service_dependencies"] = {k: list(v) for k, v in self.service_dependencies.items()}
        return value


def rca_config_from_dict(value: Mapping[str, Any]) -> RCAConfig:
    allowed = set(RCAConfig.__dataclass_fields__)
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"unknown RCA config keys: {', '.join(sorted(unknown))}")
    options = dict(value)
    for key in ("service_dependencies",):
        if key in options:
            options[key] = {str(k): tuple(v) for k, v in options[key].items()}
    if "abnormal_severities" in options:
        options["abnormal_severities"] = tuple(x.upper() for x in options["abnormal_severities"])
    return RCAConfig(**options)
