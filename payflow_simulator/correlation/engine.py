"""Explainable event relationship scoring and deterministic incident components."""

from __future__ import annotations

import hashlib
import json
import logging
import time
import tracemalloc
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from .candidate import CandidateGenerator, event_time, resources, signature, source_event
from .config import CorrelationConfig
from .models import CorrelationEdge, CorrelationEvidence, CorrelationReport
from .storage import CorrelationStore

LOGGER = logging.getLogger(__name__)


class CorrelationEngine:
    """Correlate processed records; relationships are evidence, never causality."""

    def __init__(self, store: CorrelationStore, config: CorrelationConfig | None = None):
        self.store = store
        self.config = config or CorrelationConfig()
        self.candidates = CandidateGenerator(self.config)

    def run(self, *, measure_memory: bool = False) -> CorrelationReport:
        started = time.perf_counter()
        memory_before = tracemalloc.is_tracing()
        if measure_memory and not memory_before:
            tracemalloc.start()
        events = self.store.load_processed_events()
        skipped_ids: set[str] = set()
        valid: list[Mapping[str, Any]] = []
        for item in events:
            try:
                event_time(item)
                if not source_event(item).get("event_id"):
                    raise ValueError("missing event_id")
                valid.append(item)
            except (ValueError, TypeError, AttributeError) as exc:
                skipped_ids.add(str(item.get("event_id", "<unknown>")))
                LOGGER.warning("correlation_input_skipped", extra={"event_id": item.get("event_id"), "reason": str(exc)})
        fingerprint = hashlib.sha256(json.dumps({
            "events": valid,
            "config": self.config.to_dict(),
        }, sort_keys=True, default=str).encode()).hexdigest()
        run_id = str(uuid5(NAMESPACE_URL, f"jarvis-correlation:{fingerprint}"))
        try:
            gen_start = time.perf_counter()
            pairs, candidate_meta = self.candidates.generate(valid)
            generation_seconds = time.perf_counter() - gen_start
            trace_diagnostics = _trace_diagnostics(valid, self.config)
            eval_start = time.perf_counter()
            evaluated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            edges: list[CorrelationEdge] = []
            for left_index, right_index in pairs:
                left, right = valid[left_index], valid[right_index]
                edge = self._evaluate(left, right, candidate_meta["strategies"].get(f"{left_index}:{right_index}", []), evaluated_at)
                if edge is not None:
                    edges.append(edge)
            components = self._incident_components(valid, edges)
            evaluation_seconds = time.perf_counter() - eval_start
            details = {
                "candidate_pairs": len(pairs), "relationships_accepted": len(edges),
                "candidate_generation_seconds": generation_seconds, "evaluation_seconds": evaluation_seconds,
                "skipped_events": len(skipped_ids), "config": self.config.to_dict(),
                "candidate_strategy_counts": _strategy_counts(candidate_meta["strategies"]),
                "trace_diagnostics": trace_diagnostics,
            }
            created = self.store.persist_correlation(run_id, valid, edges, components, details)
        except Exception as exc:
            self.store.record_failed_run(run_id, {"error": str(exc), "events_received": len(events), "config": self.config.to_dict()})
            LOGGER.exception("correlation_run_failed", extra={"run_id": run_id})
            if measure_memory and not memory_before and tracemalloc.is_tracing():
                tracemalloc.stop()
            raise
        duration = time.perf_counter() - started
        peak = tracemalloc.get_traced_memory()[1] if measure_memory else None
        if measure_memory and not memory_before:
            tracemalloc.stop()
        report = CorrelationReport(
            run_id=run_id, events_received=len(events), candidate_pairs=len(pairs), relationships_accepted=len(edges),
            incidents_created=created, duration_seconds=duration, candidate_generation_seconds=generation_seconds,
            evaluation_seconds=evaluation_seconds, events_per_second=len(valid) / duration if duration else 0.0,
            late_events=sum(bool(item.get("temporal", {}).get("late_arrival")) for item in valid),
            skipped_events=len(skipped_ids), trace_diagnostics=len(trace_diagnostics), memory_peak_bytes=peak,
        )
        LOGGER.info("correlation_run_completed", extra=report.to_dict())
        self.store.record_run_metrics(run_id, report.to_dict(), candidate_meta["skipped_missing_trace_ids"])
        return report

    def _evaluate(self, left: Mapping[str, Any], right: Mapping[str, Any], strategies: list[str], evaluated_at: str) -> CorrelationEdge | None:
        a, b = source_event(left), source_event(right)
        aid, bid = sorted((str(a["event_id"]), str(b["event_id"])))
        first, second = (left, right) if str(a["event_id"]) == aid else (right, left)
        sa, sb = source_event(first), source_event(second)
        ta, tb = event_time(first), event_time(second)
        diff = abs((ta - tb).total_seconds())
        trace_same = bool(sa.get("trace_id") and sa.get("trace_id") == sb.get("trace_id"))
        shared = sorted(resources(first, self.config.resource_metadata_keys) & resources(second, self.config.resource_metadata_keys))
        dependent = (sb.get("service") in self.config.service_dependencies.get(str(sa.get("service")), ()) or
                     sa.get("service") in self.config.service_dependencies.get(str(sb.get("service")), ()))
        failure_a = set(first.get("classification", {}).get("categories", [])) & set(self.config.failure_categories)
        failure_b = set(second.get("classification", {}).get("categories", [])) & set(self.config.failure_categories)
        sig_a, sig_b = signature(first), signature(second)
        similarity = SequenceMatcher(None, sig_a, sig_b).ratio()
        values: list[tuple[str, float, str, dict[str, Any]]] = []
        stage3_references = []
        for owner in (first, second):
            peer = str(sb.get("event_id") if owner is first else sa.get("event_id"))
            for pattern in owner.get("patterns", []):
                if peer in pattern.get("evidence_event_ids", []):
                    stage3_references.append({"event_id": owner.get("event_id"), "kind": pattern.get("kind"), "signature": pattern.get("signature")})
        if trace_same:
            values.append(("trace", 1.0, "Both events carry the same non-empty distributed trace ID.", {"trace_id": sa["trace_id"]}))
        if shared:
            values.append(("resource", 0.95, "Both events reference the same extracted resource identifier.", {"shared_resources": shared}))
        if diff <= self.config.temporal_window_seconds and failure_a and failure_b:
            values.append(("temporal", max(0.25, 1.0 - diff / max(1, self.config.temporal_window_seconds)),
                           "Failure-classified events fall within the configured event-time window.",
                           {"window_seconds": self.config.temporal_window_seconds, "categories": sorted(failure_a & failure_b)}))
        if dependent and diff <= self.config.temporal_window_seconds:
            values.append(("dependency", 0.7, "Events are emitted by configured dependent services within the event-time window.",
                           {"services": sorted((str(sa.get("service")), str(sb.get("service")))), "configured_dependency": True}))
        if similarity >= self.config.pattern_similarity_threshold and str(sa.get("service")) != str(sb.get("service")):
            values.append(("pattern", similarity * 0.6, "Normalized signatures are similar across services; similarity alone is insufficient for incident grouping.",
                           {"signature_similarity": round(similarity, 4), "threshold": self.config.pattern_similarity_threshold,
                            "stage3_pattern_signals": [first.get("patterns", []), second.get("patterns", [])]}))
        elif stage3_references:
            values.append(("pattern", 0.7, "Stage 3 pattern evidence explicitly references the other event; this is repetition evidence, not incident proof.",
                           {"stage3_pattern_references": stage3_references}))
        cross = str(sa.get("service")) != str(sb.get("service")) and bool(failure_a or failure_b)
        if cross and (dependent or shared) and diff <= self.config.temporal_window_seconds:
            values.append(("cross_service", 0.65, "Failure signals span services with dependency or shared-resource support.",
                           {"services": sorted((str(sa.get("service")), str(sb.get("service")))),
                            "dependency_supported": dependent, "resource_supported": bool(shared)}))
        if not values:
            return None
        # Combined heuristic is a weighted mean across observed strategies.
        numerator = sum(self.config.strategy_weights.get(name, 0.0) * score for name, score, _, _ in values)
        denominator = sum(self.config.strategy_weights.get(name, 0.0) for name, *_ in values)
        confidence = min(1.0, numerator / denominator) if denominator else 0.0
        evidence = tuple(CorrelationEvidence(aid, bid, name, desc, attrs,
                                             diff if name in {"temporal", "dependency", "cross_service"} else None,
                                             score, round(confidence, 4), evaluated_at)
                         for name, score, desc, attrs in sorted(values))
        return CorrelationEdge(aid, bid, evidence, round(confidence, 4))

    def _incident_components(self, events: list[Mapping[str, Any]], edges: list[CorrelationEdge]) -> list[list[str]]:
        """Only direct strong evidence qualifies; no overlap/time-only chaining."""
        traces = {str(source_event(item).get("event_id", item.get("event_id"))): source_event(item).get("trace_id") for item in events}
        eligible: list[CorrelationEdge] = []
        for edge in edges:
            strategies = {item.strategy for item in edge.evidence}
            trace_a, trace_b = traces.get(edge.source_event_id), traces.get(edge.target_event_id)
            conflicting_trace_boundaries = bool(trace_a and trace_b and trace_a != trace_b)
            strong = "trace" in strategies or "resource" in strategies or len(strategies & {"temporal", "dependency"}) >= 2
            if conflicting_trace_boundaries and "resource" not in strategies:
                strong = False
            if strong and edge.confidence_score >= self.config.incident_min_confidence:
                eligible.append(edge)
        parent: dict[str, str] = {}
        def find(x: str) -> str:
            parent.setdefault(x, x)
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]
        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                lo, hi = sorted((ra, rb)); parent[hi] = lo
        for edge in eligible:
            union(edge.source_event_id, edge.target_event_id)
        groups: dict[str, set[str]] = defaultdict(set)
        for event_id in parent:
            groups[find(event_id)].add(event_id)
        return sorted((sorted(group) for group in groups.values() if len(group) > 1), key=lambda group: group[0])


def _strategy_counts(index: Mapping[str, list[str]]) -> dict[str, int]:
    result: dict[str, int] = defaultdict(int)
    for strategies in index.values():
        for strategy in strategies:
            result[strategy] += 1
    return dict(result)


def _trace_diagnostics(events: list[Mapping[str, Any]], config: CorrelationConfig) -> list[dict[str, Any]]:
    """Describe observable trace completeness; absence of spans is not proof of loss."""
    traces: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    missing: list[str] = []
    for item in events:
        trace = source_event(item).get("trace_id")
        if isinstance(trace, str) and trace:
            traces[trace].append(item)
        else:
            missing.append(str(item.get("event_id", "<unknown>")))
    result: list[dict[str, Any]] = []
    for trace, members in sorted(traces.items()):
        services = sorted({str(source_event(member).get("service", "unknown")) for member in members})
        instants = [event_time(member) for member in members]
        span = (max(instants) - min(instants)).total_seconds()
        statuses = []
        if len(members) < 2 or len(services) < 2:
            statuses.append("single_service_observed")
        if span > config.max_lateness_seconds:
            statuses.append("span_exceeds_configured_lateness")
        if statuses:
            result.append({"trace_id": trace, "status": statuses, "event_count": len(members), "services": services,
                           "event_time_span_seconds": span,
                           "interpretation": "Observed trace appears incomplete or inconsistent; configured span is a diagnostic, not proof of missing spans."})
    if missing:
        result.append({"trace_id": None, "status": ["missing_trace_ids"], "event_count": len(missing), "event_ids": sorted(missing),
                       "interpretation": "Events have no trace identifier; no trace relationship was inferred."})
    return result
