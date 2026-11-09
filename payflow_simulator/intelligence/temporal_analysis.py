"""Event-time trend, burst, interval, and sequence summaries."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .models import IntelligenceConfig


def analyze_temporal(features: Sequence[Mapping[str, Any]], detector_findings: Sequence[Mapping[str, Any]],
                     invalid_timestamp_events: Sequence[Mapping[str, Any]], config: IntelligenceConfig,
                     events: Sequence[Mapping[str, Any]] = (), incidents: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    by_service: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in features: by_service[str(row["service_id"])].append(row)
    trends = []
    for service, rows in sorted(by_service.items()):
        rows.sort(key=lambda item: str(item["window_start"]))
        counts = [int(item["event_count"]) for item in rows]
        errors = [float(item["error_rate"]) for item in rows if item.get("error_rate") is not None]
        if len(rows) >= 3:
            first = sum(counts[:max(1, len(counts)//3)]) / max(1, len(counts)//3)
            last = sum(counts[-max(1, len(counts)//3):]) / max(1, len(counts)//3)
            degradation = errors[-1] - errors[0] if len(errors) >= 2 else None
            slopes = _slope(errors) if len(errors) >= 3 else None
            trends.append({"service_id": service, "first_third_mean_event_count": first,
                "last_third_mean_event_count": last, "event_volume_change": last-first,
                "error_rate_change": degradation, "error_rate_linear_slope_per_window": slopes,
                "time_range": [rows[0]["window_start"], rows[-1]["window_end"]],
                "status": "observed_trend_summary", "future_information_note": "This summary describes the supplied full range; historical detector findings use strictly prior windows."})
        else:
            trends.append({"service_id": service, "time_range": [rows[0]["window_start"], rows[-1]["window_end"]],
                "status": "insufficient_temporal_depth", "observed_windows": len(rows), "minimum_windows": 3})
    late = []
    for event in events:
        original = event.get("original_event") if isinstance(event.get("original_event"), Mapping) else event
        event_time = original.get("timestamp")
        processed_at = event.get("processing_timestamp")
        try:
            if event_time and processed_at and datetime.fromisoformat(str(processed_at).replace("Z", "+00:00")) > datetime.fromisoformat(str(event_time).replace("Z", "+00:00")):
                late.append({"event_id": original.get("event_id", event.get("event_id")), "event_time": event_time, "processing_time": processed_at,
                    "lag_seconds": (datetime.fromisoformat(str(processed_at).replace("Z", "+00:00")) - datetime.fromisoformat(str(event_time).replace("Z", "+00:00"))).total_seconds()})
        except (TypeError, ValueError):
            continue
    bursts = [dict(item) for item in detector_findings if item.get("finding_type") == "statistical_anomaly" and item.get("feature") in {"event_count", "critical_count"}]
    return {"service_trends": trends, "volume_or_severity_bursts": bursts,
        "invalid_timestamp_events": list(invalid_timestamp_events), "late_arrival_observations": late,
        "simultaneous_anomaly_windows": _simultaneous(detector_findings),
        "known_incident_preceding_sequences": _preceding_incidents(detector_findings, events, incidents),
        "ordering_policy": "UTC event-time epoch windows; invalid timestamps excluded from aggregates and listed. Late events are included in the supplied dataset window and runs are recomputed from current inputs; this is not a streaming watermark.",
        "config_version": config.version}


def _slope(values: Sequence[float]) -> float:
    n = len(values); x_mean = (n - 1) / 2; y_mean = sum(values) / n
    denominator = sum((x - x_mean) ** 2 for x in range(n))
    return sum((x - x_mean) * (y - y_mean) for x, y in enumerate(values)) / denominator if denominator else 0.0


def _simultaneous(findings: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    windows: dict[str, set[str]] = defaultdict(set)
    evidence: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in findings:
        if item.get("finding_type") not in {"statistical_anomaly", "ml_anomaly"}: continue
        window = item.get("window_start")
        if window:
            service = str(item["service_id"]); windows[str(window)].add(service)
            evidence[(str(window), service)].extend(item.get("evidence_references", []))
    return [{"window_start": window, "service_ids": sorted(services), "evidence_references": [e for service in sorted(services) for e in evidence[(window, service)]],
             "interpretation": "simultaneous detector outputs; shared timing does not establish shared cause"}
            for window, services in sorted(windows.items()) if len(services) > 1]


def _preceding_incidents(findings: Sequence[Mapping[str, Any]], events: Sequence[Mapping[str, Any]],
                         incidents: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_id={}
    for event in events:
        original=event.get("original_event") if isinstance(event.get("original_event"),Mapping) else event
        try:
            stamp=datetime.fromisoformat(str(original["timestamp"]).replace("Z","+00:00"))
            if stamp.tzinfo is None: continue
            by_id[str(original.get("event_id",event.get("event_id")))]=(stamp.astimezone(timezone.utc),str(original.get("service","unknown")))
        except (KeyError,TypeError,ValueError): continue
    result=[]
    for incident in incidents:
        members=[by_id[event_id] for event_id in incident.get("event_ids",[]) if event_id in by_id]
        if not members:
            result.append({"incident_id":incident["incident_id"],"status":"insufficient_event_time_evidence","interpretation":"No valid member event time; no earlier-anomaly claim is made."})
            continue
        start=min(item[0] for item in members)
        preceding=[]
        for finding in findings:
            if finding.get("finding_type") not in {"statistical_anomaly","ml_anomaly"}: continue
            window_end=finding.get("window_end")
            try: end=datetime.fromisoformat(str(window_end).replace("Z","+00:00"))
            except (TypeError,ValueError): continue
            if end<=start:
                preceding.append({"service_id":finding.get("service_id"),"window_start":finding.get("window_start"),
                    "detector":finding.get("detector"),"evidence_references":finding.get("evidence_references",[])[:5]})
        result.append({"incident_id":incident["incident_id"],"first_member_event_time":start.isoformat().replace("+00:00","Z"),
            "member_services":sorted({service for _,service in members}),"preceding_anomaly_count":len(preceding),
            "preceding_anomalies":preceding[:100],"interpretation":"Retrospective event-time ordering context only; not a claimed prediction or causal explanation.",
            "limitations":["Only persisted Stage 4 incident members are considered.","A preceding anomaly can be unrelated to the incident."]})
    return result
