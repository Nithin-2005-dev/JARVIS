"""JSON-backed configuration for the local processing pipeline."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ClassificationRule:
    """A configurable, conjunctive match rule with one output category."""

    rule_id: str
    category: str
    priority: int = 100
    event_types: tuple[str, ...] = ()
    severities: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    message_regex: str | None = None


DEFAULT_RULES = (
    ClassificationRule("db-pool", "infrastructure_failures", 10, ("db_pool_exhausted",)),
    ClassificationRule("database-errors", "database_failures", 20, services=("database-service",), severities=("ERROR", "CRITICAL")),
    ClassificationRule("network-downstream", "network_failures", 20, ("downstream_failure",)),
    ClassificationRule("auth-errors", "authentication_failures", 20, severities=("ERROR", "CRITICAL"), services=("authentication-service",)),
    ClassificationRule("security-signals", "security_related", 30, message_regex=r"(?i)unauthori[sz]ed|forbidden|credential|token theft|injection"),
    ClassificationRule("security-event", "security_related", 25, event_types=("security_alert",)),
    ClassificationRule("performance-signals", "performance_degradation", 30, message_regex=r"(?i)slow|latency|timed out|timeout|pool exhausted"),
    ClassificationRule("lifecycle-signals", "service_lifecycle_events", 30, event_types=("service_started", "service_stopped", "service_restarted", "health_check")),
    ClassificationRule("application-errors", "application_errors", 90, severities=("ERROR", "CRITICAL")),
)


DEFAULT_SERVICE_REGISTRY: dict[str, dict[str, Any]] = {
    "api-gateway": {"team": "payments-platform", "tier": 1, "kind": "edge"},
    "authentication-service": {"team": "identity", "tier": 1, "kind": "backend"},
    "payment-service": {"team": "payments", "tier": 1, "kind": "backend"},
    "database-service": {"team": "data-platform", "tier": 1, "kind": "storage"},
    "notification-service": {"team": "messaging", "tier": 2, "kind": "backend"},
}


@dataclass(frozen=True, slots=True)
class PatternThresholds:
    """Deterministic count thresholds for event-time pattern signals."""

    repeated_error: int = 2
    recurring_failure: int = 3
    frequency_spike: int = 10
    repeated_across_services: int = 2

    def __post_init__(self) -> None:
        if min(self.repeated_error, self.recurring_failure, self.frequency_spike, self.repeated_across_services) < 1:
            raise ValueError("pattern thresholds must be positive")


@dataclass(frozen=True, slots=True)
class ProcessingConfig:
    """All tunable metadata, rules, temporal settings, and batch behavior."""

    environment: str = "development"
    application: str = "payflow"
    registry_version: str = "default-v1"
    service_registry: Mapping[str, Mapping[str, Any]] = field(default_factory=lambda: {key: dict(value) for key, value in DEFAULT_SERVICE_REGISTRY.items()})
    classification_rules: tuple[ClassificationRule, ...] = DEFAULT_RULES
    window_seconds: int = 60
    allowed_lateness_seconds: int = 30
    patterns: PatternThresholds = field(default_factory=PatternThresholds)
    batch_size: int = 500
    stale_claim_seconds: int = 300

    def __post_init__(self) -> None:
        if not self.environment or not self.application or not self.registry_version:
            raise ValueError("environment, application, and registry_version must be non-empty")
        if self.window_seconds < 1 or self.allowed_lateness_seconds < 0:
            raise ValueError("window_seconds must be positive and allowed_lateness_seconds non-negative")
        if self.batch_size < 1 or self.stale_claim_seconds < 1:
            raise ValueError("batch_size and stale_claim_seconds must be positive")
        ids = [rule.rule_id for rule in self.classification_rules]
        if any(not rule_id for rule_id in ids) or len(ids) != len(set(ids)):
            raise ValueError("classification rule IDs must be non-empty and unique")
        for rule in self.classification_rules:
            if not rule.category:
                raise ValueError(f"classification rule {rule.rule_id} requires a category")
            if rule.message_regex is not None:
                re.compile(rule.message_regex)

    def to_dict(self) -> dict[str, Any]:
        """Serialize config to JSON-compatible structures."""
        data = asdict(self)
        data["classification_rules"] = [asdict(rule) for rule in self.classification_rules]
        return data


def config_from_dict(data: Mapping[str, Any]) -> ProcessingConfig:
    """Create validated configuration from a decoded JSON object."""
    allowed = {"environment", "application", "registry_version", "service_registry", "classification_rules", "window_seconds", "allowed_lateness_seconds", "patterns", "batch_size", "stale_claim_seconds"}
    extra = set(data) - allowed
    if extra:
        raise ValueError(f"unknown processing config keys: {', '.join(sorted(extra))}")
    rules = tuple(ClassificationRule(
        rule_id=str(raw["rule_id"]), category=str(raw["category"]), priority=int(raw.get("priority", 100)),
        event_types=tuple(raw.get("event_types", ())), severities=tuple(v.upper() for v in raw.get("severities", ())),
        services=tuple(raw.get("services", ())), message_regex=raw.get("message_regex"),
    ) for raw in data.get("classification_rules", ()))
    values = dict(data)
    if "classification_rules" in data:
        values["classification_rules"] = rules
    if "patterns" in data:
        values["patterns"] = PatternThresholds(**data["patterns"])
    return ProcessingConfig(**values)


def load_config(path: str | Path | None = None) -> ProcessingConfig:
    """Load optional JSON settings, otherwise use deterministic defaults."""
    if path is None:
        return ProcessingConfig()
    with Path(path).open(encoding="utf-8") as stream:
        raw = json.load(stream)
    if not isinstance(raw, dict):
        raise ValueError("processing config root must be a JSON object")
    return config_from_dict(raw)
