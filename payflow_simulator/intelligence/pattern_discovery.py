"""Bounded, deterministic recurring signature and incident-structure mining."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
from typing import Any, Mapping, Sequence

from .feature_extraction import event_signature
from .models import IntelligenceConfig


def discover_patterns(events: Sequence[Mapping[str, Any]], incidents: Sequence[Mapping[str, Any]],
                      config: IntelligenceConfig) -> dict[str, Any]:
    signatures: dict[str, dict[str, Any]] = {}
    by_signature: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        original = event.get("original_event") if isinstance(event.get("original_event"), Mapping) else event
        signature = event_signature(event)
        row = {"event_id": str(original.get("event_id", event.get("event_id", ""))),
               "service_id": str(original.get("service", "unknown")), "timestamp": original.get("timestamp"),
               "event_type": original.get("event_type"), "severity": original.get("severity"),
               "message": original.get("message", ""), "signature": signature}
        by_signature[signature].append(row)
    exact = []
    for signature, rows in sorted(by_signature.items()):
        windows = sorted({_window_bucket(row.get("timestamp"), config.window_seconds) for row in rows} - {None})
        if len(rows) >= config.pattern_minimum_support and len(windows) > 1:
            exact.append({"pattern_id": signature, "match_kind": "exact_normalized_signature",
                "support_events": len(rows), "support_time_buckets": len(windows), "service_ids": sorted({r["service_id"] for r in rows}),
                "event_signature": signature, "evidence_references": [{"event_id": r["event_id"], "timestamp": r["timestamp"], "service_id": r["service_id"]} for r in rows[:100]],
                "total_evidence_event_count": len(rows), "omitted_evidence_event_count": max(0,len(rows)-100),
                "interpretation": "repeated signature; recurrence is not causal evidence"})
    # Similarity uses event-type/severity/message tokens reconstructed from the normalized signature groups.
    representatives = []
    for signature, rows in sorted(by_signature.items()):
        sample = rows[0]
        representative = (signature, set((str(sample.get("event_type", "")).lower(), str(sample.get("severity", "")).lower(),
            *str(sample.get("message", "")).lower().split())))
        representatives.append(representative)
    approximate = []; comparisons = 0
    for (left_id, left), (right_id, right) in combinations(representatives, 2):
        if comparisons >= config.pattern_pair_limit: break
        comparisons += 1
        union = left | right; similarity = len(left & right) / len(union) if union else 1.0
        if config.pattern_similarity_threshold <= similarity < 1.0:
            approximate.append({"pattern_id": f"{left_id}:{right_id}", "match_kind": "approximate_token_similarity",
                "similarity_score": round(similarity, 6), "score_interpretation": "Jaccard token similarity, not probability or causal strength",
                "supporting_signatures": [left_id, right_id], "evidence_references": [
                    {"event_id": r["event_id"], "timestamp": r["timestamp"], "service_id": r["service_id"]}
                    for signature in (left_id, right_id) for r in by_signature[signature][:50]],
                "total_evidence_event_count": len(by_signature[left_id])+len(by_signature[right_id]),
                "limitations": ["Token overlap can group semantically unrelated messages.", "Approximate matches are investigative hints only."]})
    structures: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for incident in incidents:
        services = tuple(sorted(set(str(x) for x in incident.get("service_ids", []))))
        if services: structures[services].append(incident)
    incident_patterns = [{"pattern_id": "incident:" + ",".join(services), "match_kind": "exact_incident_service_structure",
        "service_ids": list(services), "support_incidents": len(rows),
        "evidence_references": [{"incident_id": str(row["incident_id"]), "created_at": row.get("created_at"), "event_ids": row.get("event_ids", [])} for row in rows],
        "interpretation": "recurring incident membership structure; does not imply a common root cause"}
        for services, rows in sorted(structures.items()) if len(rows) >= config.pattern_minimum_support]
    return {"exact_signature_patterns": exact, "approximate_signature_patterns": approximate,
        "incident_structure_patterns": incident_patterns, "similarity_comparisons": comparisons,
        "comparison_limit": config.pattern_pair_limit, "minimum_support": config.pattern_minimum_support}


def _window_bucket(raw: Any, window_seconds: int) -> str | None:
    if not isinstance(raw, str): return None
    try: parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError: return None
    if parsed.tzinfo is None: return None
    epoch = int(parsed.astimezone(timezone.utc).timestamp())
    bucket = epoch - epoch % window_seconds
    return datetime.fromtimestamp(bucket, timezone.utc).isoformat().replace("+00:00", "Z")
