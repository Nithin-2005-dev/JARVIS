"""Configurable PayFlow service and dependency registry."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .models import Dependency, Service
from ..processing.config import DEFAULT_SERVICE_REGISTRY


@dataclass(frozen=True, slots=True)
class DependencyGraphConfig:
    services: tuple[Service, ...]
    dependencies: tuple[Dependency, ...]
    known_dependency_types: tuple[str, ...] = ("synchronous_api", "database", "message_queue", "authentication", "cache", "external_service", "other")
    criticality_factors: Mapping[str, float] = field(default_factory=lambda: {"critical": 1.0, "high": .8, "medium": .55, "low": .3, "unknown": .25})
    verification_factors: Mapping[str, float] = field(default_factory=lambda: {"verified": 1.0, "observed": .8, "configured": .65, "unverified": .4, "unknown": .3})
    depth_decay: float = .85
    fanout_base: float = .7
    fanout_increment: float = .1
    max_paths_per_service: int = 100
    version_label: str = "payflow-v1"

    def __post_init__(self) -> None:
        if not 0 <= self.depth_decay <= 1 or not 0 <= self.fanout_base <= 1 or not 0 <= self.fanout_increment <= 1:
            raise ValueError("scoring factors must be within [0, 1]")
        if self.max_paths_per_service < 1 or not self.version_label:
            raise ValueError("max_paths_per_service and version_label must be valid")
        if any(not 0 <= float(x) <= 1 for x in self.criticality_factors.values()):
            raise ValueError("criticality factors must be within [0, 1]")
        if any(not 0 <= float(x) <= 1 for x in self.verification_factors.values()):
            raise ValueError("verification factors must be within [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["services"] = [s.to_dict() for s in self.services]
        value["dependencies"] = [d.to_dict() for d in self.dependencies]
        return value


def default_config() -> DependencyGraphConfig:
    """PayFlow topology based only on calls and outcomes emitted by the simulator."""
    services = (
        Service("api-gateway", "API Gateway", "Accepts payment requests and returns responses.", "edge", "high", "payment checkout", metadata=dict(DEFAULT_SERVICE_REGISTRY["api-gateway"])),
        Service("authentication-service", "Authentication Service", "Authenticates the merchant before payment handling.", "backend", "high", "identity and access", metadata=dict(DEFAULT_SERVICE_REGISTRY["authentication-service"])),
        Service("payment-service", "Payment Service", "Creates and authorizes payment intents.", "backend", "critical", "payment processing", metadata=dict(DEFAULT_SERVICE_REGISTRY["payment-service"])),
        Service("database-service", "Database Service", "Persists payment records and can exhaust its connection pool.", "storage", "critical", "payment data persistence", metadata=dict(DEFAULT_SERVICE_REGISTRY["database-service"])),
        Service("notification-service", "Notification Service", "Sends receipts; failures are queued for retry.", "backend", "medium", "customer notifications", metadata=dict(DEFAULT_SERVICE_REGISTRY["notification-service"])),
    )
    dependencies = (
        Dependency("api-gateway", "authentication-service", "authentication", .9,
                   "Gateway authenticates the merchant before processing.", "simulator_flow", .85, "observed"),
        Dependency("api-gateway", "payment-service", "synchronous_api", 1.0,
                   "Gateway forwards payment requests and returns payment results.", "simulator_flow", .9, "observed"),
        Dependency("payment-service", "database-service", "database", 1.0,
                   "Payment records are persisted by the database service.", "simulator_flow", .95, "observed"),
        Dependency("notification-service", "payment-service", "message_queue", .45,
                   "Receipt work is generated only after payment authorization; the simulator shows notification retry queued after delivery failure.", "simulator_flow", .75, "observed",
                   {"failure_blocks_payment": False, "retry_behavior": "queued", "queue_is_simulated": True}),
    )
    return DependencyGraphConfig(services=services, dependencies=dependencies)


def config_from_dict(value: Mapping[str, Any]) -> DependencyGraphConfig:
    allowed = set(DependencyGraphConfig.__dataclass_fields__)
    unknown = set(value) - allowed
    if unknown: raise ValueError(f"unknown dependency graph config keys: {', '.join(sorted(unknown))}")
    options = {k: v for k, v in value.items() if k not in {"services", "dependencies"}}
    if "known_dependency_types" in options: options["known_dependency_types"] = tuple(options["known_dependency_types"])
    return DependencyGraphConfig(
        services=tuple(Service(**dict(item)) for item in value.get("services", [])),
        dependencies=tuple(Dependency(**dict(item)) for item in value.get("dependencies", [])),
        **options,
    )


def load_config(path: str | Path | None = None) -> DependencyGraphConfig:
    if path is None: return default_config()
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict): raise ValueError("dependency graph config must be a JSON object")
    return config_from_dict(value)
