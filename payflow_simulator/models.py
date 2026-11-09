"""Typed event schema and validation helpers for simulated service events."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping
from uuid import UUID


class Severity(str, Enum):
    """Operational impact associated with an event."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class EventType(str, Enum):
    """Kinds of events emitted by the simulated services."""

    REQUEST_RECEIVED = "request_received"
    AUTHENTICATED = "authenticated"
    PAYMENT_CREATED = "payment_created"
    DB_QUERY = "db_query"
    DB_POOL_EXHAUSTED = "db_pool_exhausted"
    PAYMENT_PROCESSED = "payment_processed"
    DOWNSTREAM_FAILURE = "downstream_failure"
    NOTIFICATION_SENT = "notification_sent"
    REQUEST_COMPLETED = "request_completed"
    REQUEST_FAILED = "request_failed"
    SERVICE_STARTED = "service_started"
    SERVICE_STOPPED = "service_stopped"
    SERVICE_RESTARTED = "service_restarted"
    HEALTH_CHECK = "health_check"
    SECURITY_ALERT = "security_alert"


@dataclass(frozen=True, slots=True)
class Event:
    """A single immutable, trace-correlated service event."""

    event_id: str
    timestamp: str
    service: str
    event_type: EventType
    severity: Severity
    message: str
    source: str
    trace_id: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable event mapping."""
        result = asdict(self)
        result["event_type"] = self.event_type.value
        result["severity"] = self.severity.value
        return result


def validate_event(data: Mapping[str, Any]) -> None:
    """Raise ValueError if a mapping does not satisfy the canonical event contract."""
    required = {
        "event_id", "timestamp", "service", "event_type", "severity",
        "message", "source", "trace_id", "metadata",
    }
    missing = required - data.keys()
    extra = data.keys() - required
    if missing or extra:
        raise ValueError(f"event keys mismatch; missing={sorted(missing)}, extra={sorted(extra)}")
    for key in ("event_id", "timestamp", "service", "event_type", "severity", "message", "source", "trace_id"):
        if not isinstance(data[key], str) or not data[key]:
            raise ValueError(f"{key} must be a non-empty string")
    try:
        UUID(data["event_id"])
        UUID(data["trace_id"])
        parsed = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timestamp must include timezone")
        EventType(data["event_type"])
        Severity(data["severity"])
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid event field: {exc}") from exc
    if not isinstance(data["metadata"], dict):
        raise ValueError("metadata must be an object")


def event_from_dict(data: Mapping[str, Any]) -> Event:
    """Validate and construct an Event from a decoded JSON object."""
    validate_event(data)
    return Event(**{**data, "event_type": EventType(data["event_type"]), "severity": Severity(data["severity"])})
