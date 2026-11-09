"""Validated, deterministic settings for event correlation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class CorrelationConfig:
    """Heuristic strategy weights and grouping policy; scores are not probabilities."""

    temporal_window_seconds: int = 60
    max_lateness_seconds: int = 300
    pattern_similarity_threshold: float = 0.82
    incident_min_confidence: float = 0.60
    strategy_weights: Mapping[str, float] = field(default_factory=lambda: {
        "trace": 1.0, "resource": 0.9, "dependency": 0.55,
        "temporal": 0.35, "pattern": 0.30, "cross_service": 0.25,
    })
    service_dependencies: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: {
        "api-gateway": ("authentication-service", "payment-service"),
        "authentication-service": ("payment-service",),
        "payment-service": ("database-service", "notification-service"),
    })
    resource_metadata_keys: tuple[str, ...] = (
        "resource_id", "database", "database_id", "db_instance", "server_id",
        "host", "hostname", "api", "endpoint", "network_component", "resource",
    )
    failure_categories: tuple[str, ...] = (
        "infrastructure_failures", "database_failures", "network_failures",
        "authentication_failures", "application_errors", "performance_degradation", "security_related",
    )
    max_candidates: int = 250_000

    def __post_init__(self) -> None:
        if self.temporal_window_seconds < 0 or self.max_lateness_seconds < 0:
            raise ValueError("time windows must be non-negative")
        if not 0 < self.pattern_similarity_threshold <= 1:
            raise ValueError("pattern_similarity_threshold must be in (0, 1]")
        if not 0 <= self.incident_min_confidence <= 1:
            raise ValueError("incident_min_confidence must be in [0, 1]")
        if self.max_candidates < 1:
            raise ValueError("max_candidates must be positive")
        if any(not 0 <= float(weight) <= 1 for weight in self.strategy_weights.values()):
            raise ValueError("strategy weights must be in [0, 1]")
        supported = {"trace", "resource", "dependency", "temporal", "pattern", "cross_service"}
        if set(self.strategy_weights) - supported:
            raise ValueError("strategy_weights contains an unsupported strategy")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["service_dependencies"] = {key: list(value) for key, value in self.service_dependencies.items()}
        return result


def correlation_config_from_dict(value: Mapping[str, Any]) -> CorrelationConfig:
    """Build config from JSON-compatible mapping, rejecting unknown settings."""
    allowed = set(CorrelationConfig.__dataclass_fields__)
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"unknown correlation config keys: {', '.join(sorted(unknown))}")
    options = dict(value)
    if "service_dependencies" in options:
        options["service_dependencies"] = {str(k): tuple(v) for k, v in options["service_dependencies"].items()}
    for key in ("resource_metadata_keys", "failure_categories"):
        if key in options:
            options[key] = tuple(options[key])
    return CorrelationConfig(**options)
