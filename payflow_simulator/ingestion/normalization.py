"""Canonicalization and validation for untrusted event mappings."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID

from ..models import Event, EventType, Severity, validate_event


def normalize_event(value: Any) -> Event:
    """Validate and normalize a mapping while preserving source and metadata."""
    if not isinstance(value, Mapping):
        raise ValueError("record must be a JSON object")
    required = {"event_id", "timestamp", "service", "event_type", "severity", "message", "source", "trace_id", "metadata"}
    missing = required - value.keys()
    if missing:
        raise ValueError(f"missing required fields: {', '.join(sorted(missing))}")
    data = dict(value)
    for field in ("event_id", "trace_id"):
        if not isinstance(data[field], str):
            raise ValueError(f"{field} must be a string UUID")
        try:
            data[field] = str(UUID(data[field]))
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError(f"{field} must be a valid UUID") from exc
    timestamp = data["timestamp"]
    if not isinstance(timestamp, str) or not timestamp.strip():
        raise ValueError("timestamp must be a non-empty ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(timestamp.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be a valid ISO-8601 value") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    data["timestamp"] = parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").rstrip("0").rstrip(".").replace("+00:00", "Z")
    if not isinstance(data["severity"], str):
        raise ValueError("severity must be a string")
    severity = re.sub(r"[\s-]+", "_", data["severity"].strip().upper())
    severity = {"WARN": "WARNING", "ERR": "ERROR", "FATAL": "CRITICAL", "PANIC": "CRITICAL"}.get(severity, severity)
    try:
        data["severity"] = Severity(severity).value
    except ValueError as exc:
        raise ValueError(f"unsupported severity: {data['severity']}") from exc
    if isinstance(data["event_type"], str):
        data["event_type"] = re.sub(r"[\s-]+", "_", data["event_type"].strip().lower())
    if isinstance(data["service"], str):
        data["service"] = re.sub(r"[\s_]+", "-", data["service"].strip().lower())
    # The current Event schema is strict about top-level keys. Preserve the
    # metadata object as supplied, and reject unknown top-level data explicitly.
    validate_event(data)
    return Event(**{**data, "event_type": EventType(data["event_type"]), "severity": Severity(data["severity"])})
