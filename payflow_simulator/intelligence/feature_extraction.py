"""Event-time feature aggregation with explicit source provenance."""
from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any, Iterable, Mapping

from .models import FeatureWindow, IntelligenceConfig


def _original(event: Mapping[str, Any]) -> Mapping[str, Any]:
    value = event.get("original_event")
    return value if isinstance(value, Mapping) else event


def _event_time(event: Mapping[str, Any], original: Mapping[str, Any]) -> datetime:
    temporal = event.get("temporal", {})
    raw = temporal.get("event_timestamp") if isinstance(temporal, Mapping) else None
    raw = raw or original.get("timestamp")
    if not isinstance(raw, str):
        raise ValueError("missing event timestamp")
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("event timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def event_signature(event: Mapping[str, Any]) -> str:
    """Stable exact-ish signature: service/type/severity and normalized message."""
    original = _original(event)
    message = re.sub(r"\b[0-9a-fA-F-]{8,}\b", "<id>", str(original.get("message", "")).lower())
    message = re.sub(r"\b\d+(?:\.\d+)?\b", "<n>", message)
    message = " ".join(message.split())[:240]
    body = "|".join((str(original.get("service", "unknown")).strip(), str(original.get("event_type", "unknown")).strip().lower(),
                     str(original.get("severity", "unknown")).upper(), message))
    return hashlib.sha256(body.encode()).hexdigest()


def extract_features(events: Iterable[Mapping[str, Any]], config: IntelligenceConfig) -> dict[str, Any]:
    """Aggregate event records by service and UTC epoch-aligned window."""
    buckets: dict[tuple[str, int], list[tuple[datetime, Mapping[str, Any], Mapping[str, Any]]]] = defaultdict(list)
    invalid: list[dict[str, Any]] = []
    for event in events:
        original = _original(event)
        event_id = str(original.get("event_id", event.get("event_id", "")))
        service = str(original.get("service") or "unknown").strip()
        try:
            timestamp = _event_time(event, original)
        except (TypeError, ValueError, OverflowError) as exc:
            invalid.append({"event_id": event_id, "service_id": service, "reason": str(exc), "raw_timestamp": original.get("timestamp")})
            continue
        epoch = int(timestamp.timestamp())
        start_epoch = epoch - epoch % config.window_seconds
        buckets[(service, start_epoch)].append((timestamp, event, original))

    features: list[FeatureWindow] = []
    for (service, start_epoch), rows in sorted(buckets.items()):
        rows.sort(key=lambda row: (row[0], str(_original(row[1]).get("event_id", ""))))
        start = datetime.fromtimestamp(start_epoch, timezone.utc)
        end = start + timedelta(seconds=config.window_seconds)
        originals = [row[2] for row in rows]
        severities = [str(item.get("severity", "")).upper() for item in originals]
        errors = sum(level in {"ERROR", "CRITICAL", "FATAL"} for level in severities)
        error_rate = errors / len(rows) if all(item.get("severity") for item in originals) else None
        event_types = Counter(str(item.get("event_type") or "unknown").strip().lower() for item in originals)
        severity_counts = Counter(level or "UNKNOWN" for level in severities)
        signatures = Counter(event_signature(row[1]) for row in rows)
        resources: Counter[str] = Counter()
        for item in originals:
            metadata = item.get("metadata", {})
            if not isinstance(metadata, Mapping): continue
            for key in ("resource_id", "resource", "database", "server", "host", "api", "network_component"):
                value = metadata.get(key)
                if isinstance(value, str) and value: resources[f"{key}:{value}"] += 1
            values = metadata.get("resource_ids", metadata.get("resources", []))
            if isinstance(values, str): values = [values]
            if isinstance(values, list):
                for value in values:
                    if isinstance(value, str) and value: resources[f"resource:{value}"] += 1
        times = [row[0].timestamp() for row in rows]
        intervals = [times[index] - times[index - 1] for index in range(1, len(times))]
        latencies: list[float] = []
        for item in originals:
            metadata = item.get("metadata", {})
            raw = item.get("latency_ms", item.get("duration_ms"))
            if raw is None and isinstance(metadata, Mapping): raw = metadata.get("latency_ms", metadata.get("duration_ms"))
            if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw >= 0:
                latencies.append(float(raw))
        missing = []
        if any(not item.get("service") for item in originals): missing.append("service")
        if any(not item.get("event_type") for item in originals): missing.append("event_type")
        if any(not item.get("severity") for item in originals): missing.append("severity")
        if not latencies: missing.append("latency")
        ids = tuple(str(_original(row[1]).get("event_id", row[1].get("event_id", ""))) for row in rows)
        features.append(FeatureWindow(service, start.isoformat().replace("+00:00", "Z"),
            end.isoformat().replace("+00:00", "Z"), len(rows), error_rate,
            sum(level in {"CRITICAL", "FATAL"} for level in severities),
            sum(level in {"WARN", "WARNING"} for level in severities), dict(sorted(event_types.items())),
            dict(sorted(severity_counts.items())), dict(sorted(signatures.items())), dict(sorted(resources.items())), mean(intervals) if intervals else None,
            mean(latencies) if latencies else None, tuple(sorted(set(missing))), ids,
            tuple(row[0].isoformat().replace("+00:00", "Z") for row in rows),
            {"event_count": "count of valid event-time records", "error_rate": "ERROR/CRITICAL/FATAL event count divided by total window events; absent if any severity is missing",
             "critical_count": "CRITICAL/FATAL severity count", "warning_count": "WARN/WARNING severity count",
             "severity_counts": "count by original severity value", "event_type_counts": "count by original event_type",
             "signature_counts": "count by deterministic normalized event signature",
             "resource_counts": "counts for identifiers explicitly present in source metadata; no resource is inferred",
             "mean_interarrival_seconds": "mean adjacent UTC event-time difference; absent for fewer than two events",
             "latency_mean_ms": "mean explicit latency_ms or duration_ms source fields only; absent when not provided"}))
    return {"features": [item.to_dict() for item in features], "invalid_timestamp_events": invalid,
            "events_with_valid_timestamps": sum(item.event_count for item in features),
            "events_with_invalid_timestamps": len(invalid), "window_seconds": config.window_seconds}
