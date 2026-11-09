"""Indexed candidate generation; only plausible event pairs reach scoring."""

from __future__ import annotations

from collections import defaultdict
from collections import deque
from datetime import datetime
from difflib import SequenceMatcher
from itertools import combinations
import re
from typing import Any, Iterable, Mapping

from .config import CorrelationConfig


def event_time(event: Mapping[str, Any]) -> datetime:
    value = event.get("temporal", {}).get("event_timestamp") or event.get("original_event", {}).get("timestamp")
    if not isinstance(value, str):
        raise ValueError("processed event is missing event-time timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("event timestamp must include timezone")
    return parsed


def source_event(event: Mapping[str, Any]) -> Mapping[str, Any]:
    return event.get("original_event", event)


def resources(event: Mapping[str, Any], keys: tuple[str, ...]) -> set[str]:
    """Extract identifier-like values from configured normalized metadata keys."""
    metadata = source_event(event).get("metadata", {})
    result: set[str] = set()
    def walk(value: Any, parent: str = "") -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                key_s = str(key).lower()
                if key_s in keys and isinstance(child, (str, int, float)) and str(child).strip():
                    result.add(f"{key_s}:{str(child).strip().lower()}")
                walk(child, key_s)
        elif isinstance(value, list):
            for child in value:
                walk(child, parent)
    walk(metadata)
    return result


def signature(event: Mapping[str, Any]) -> str:
    original = source_event(event)
    explicit = original.get("metadata", {}).get("signature")
    if isinstance(explicit, str) and explicit:
        return explicit.lower()
    # Keep text similarity weak and avoid IDs/numbers driving exact signatures.
    message = " ".join(str(original.get("message", "")).lower().split())
    return f"{original.get('event_type', '')}:{original.get('severity', '')}:{message}"


class CandidateGenerator:
    """Union candidates from trace/resource/time/dependency/signature indexes.

    Sorting is O(n log n); sparse bucket joins are O(n + k), where k is the
    emitted candidates. Dense buckets are bounded by max_candidates.
    """

    def __init__(self, config: CorrelationConfig):
        self.config = config

    def generate(self, events: Iterable[Mapping[str, Any]]) -> tuple[list[tuple[int, int]], dict[str, Any]]:
        rows = list(events)
        pair_strategies: dict[tuple[int, int], set[str]] = defaultdict(set)
        by_trace: dict[str, list[int]] = defaultdict(list)
        by_resource: dict[str, list[int]] = defaultdict(list)
        by_event_id: dict[str, int] = {}
        by_service: dict[str, list[int]] = defaultdict(list)
        times: list[tuple[datetime, int]] = []
        skipped = 0
        for i, item in enumerate(rows):
            source = source_event(item)
            trace = source.get("trace_id")
            if isinstance(trace, str) and trace:
                by_trace[trace].append(i)
            else:
                skipped += 1
            for resource in resources(item, self.config.resource_metadata_keys):
                by_resource[resource].append(i)
            by_event_id[str(source.get("event_id", item.get("event_id", "")))] = i
            by_service[str(source.get("service", ""))].append(i)
            times.append((event_time(item), i))

        def add_bucket(index: Mapping[str, list[int]], strategy: str) -> None:
            for ids in index.values():
                if len(ids) > 1:
                    if strategy == "pattern":
                        pairs = ((a, b) for pos, a in enumerate(ids) for b in ids[pos + 1:]
                                 if source_event(rows[a]).get("service") != source_event(rows[b]).get("service"))
                    else:
                        pairs = combinations(ids, 2)
                    for a, b in pairs:
                        pair_strategies[(min(a, b), max(a, b))].add(strategy)
                        if len(pair_strategies) > self.config.max_candidates:
                            raise ValueError(f"candidate limit exceeded ({self.config.max_candidates})")

        add_bucket(by_trace, "trace")
        add_bucket(by_resource, "resource")
        # Reuse Stage 3's explicit bounded pattern evidence where it names peers.
        for i, item in enumerate(rows):
            for pattern in item.get("patterns", []):
                for event_id in pattern.get("evidence_event_ids", []):
                    other = by_event_id.get(str(event_id))
                    if other is not None and other != i:
                        pair_strategies[(min(i, other), max(i, other))].add("pattern")

        # Time sweep: only plausible failure events are emitted, preventing
        # coincident informational events from becoming candidate relationships.
        times.sort()
        active_by_category: dict[str, deque[tuple[datetime, int]]] = defaultdict(deque)
        active_by_service: dict[str, deque[tuple[datetime, int]]] = defaultdict(deque)
        reverse_dependencies: dict[str, set[str]] = defaultdict(set)
        for upstream, downstreams in self.config.service_dependencies.items():
            for downstream in downstreams:
                reverse_dependencies[downstream].add(upstream)
        for current_time, current_idx in times:
            current_source = source_event(rows[current_idx])
            for queue in (*active_by_category.values(), *active_by_service.values()):
                while queue and (current_time - queue[0][0]).total_seconds() > self.config.temporal_window_seconds:
                    queue.popleft()
            current_cats = set(rows[current_idx].get("classification", {}).get("categories", [])) & set(self.config.failure_categories)
            current_service = str(current_source.get("service", ""))
            dependent_services = set(self.config.service_dependencies.get(current_service, ())) | reverse_dependencies.get(current_service, set())
            candidate_ids: set[int] = set()
            for category in current_cats:
                candidate_ids.update(index for _, index in active_by_category.get(category, ()))
            for service in dependent_services:
                candidate_ids.update(index for _, index in active_by_service.get(service, ()))
            for prior_idx in candidate_ids:
                prior_source = source_event(rows[prior_idx])
                prior_cats = set(rows[prior_idx].get("classification", {}).get("categories", [])) & set(self.config.failure_categories)
                shared_failure = bool(current_cats & prior_cats)
                cross_service = current_service != prior_source.get("service")
                key = (min(current_idx, prior_idx), max(current_idx, prior_idx))
                if shared_failure:
                    pair_strategies[key].add("temporal")
                if cross_service and shared_failure:
                    similarity = SequenceMatcher(None, signature(rows[current_idx]), signature(rows[prior_idx])).ratio()
                    if similarity >= self.config.pattern_similarity_threshold:
                        pair_strategies[key].add("pattern")
                if cross_service and str(prior_source.get("service")) in dependent_services:
                    pair_strategies[key].add("dependency")
                if cross_service and shared_failure and str(prior_source.get("service")) in dependent_services:
                    pair_strategies[key].add("cross_service")
                if len(pair_strategies) > self.config.max_candidates:
                    raise ValueError(f"candidate limit exceeded ({self.config.max_candidates})")
            if current_cats:
                for category in current_cats:
                    active_by_category[category].append((current_time, current_idx))
                active_by_service[current_service].append((current_time, current_idx))
            if len(pair_strategies) > self.config.max_candidates:
                raise ValueError(f"candidate limit exceeded ({self.config.max_candidates})")
        pairs = sorted(pair_strategies)
        return pairs, {"strategies": {f"{a}:{b}": sorted(v) for (a, b), v in pair_strategies.items()},
                       "skipped_missing_trace_ids": skipped}
