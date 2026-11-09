"""Dependency-contextual anomaly relationships without causal claims."""
from __future__ import annotations

from datetime import datetime
from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections import deque
from typing import Any, Mapping, Sequence

from ..dependency_graph.models import DependencyGraph
from .models import IntelligenceConfig


def analyze_cross_service(findings: Sequence[Mapping[str, Any]], graph: DependencyGraph | None,
                          config: IntelligenceConfig) -> dict[str, Any]:
    grouped: dict[tuple[str,str], list[Mapping[str,Any]]] = defaultdict(list)
    for item in findings:
        if item.get("finding_type") in {"statistical_anomaly", "ml_anomaly"} and item.get("uncertainty_status") == "heuristic_anomaly_signal":
            grouped[(str(item["service_id"]),str(item["window_start"]))].append(item)
    anomalies: dict[str,list[dict[str,Any]]] = defaultdict(list)
    for (service,window), items in sorted(grouped.items()):
        references = {}
        for item in items:
            for ref in item.get("evidence_references",[]):
                if ref.get("event_id"): references[str(ref["event_id"])] = ref
        anomalies[service].append({"service_id":service,"window_start":window,
            "detectors":sorted({str(item.get("detector")) for item in items}),
            "evidence_references":list(references.values())[:5],"evidence_reference_count":len(references)})
    if graph is None:
        return {"status": "dependency_graph_unavailable", "relationships": [],
                "limitations": ["Stage 6 graph snapshot was not available; cross-service topology could not be assessed."]}
    edges = {(d.source_service_id, d.target_service_id): d for d in graph.dependencies}
    relationships = []; considered=0; truncated=0; candidate_cap_hit=False
    service_names=sorted(anomalies)
    paths_by_service={service:_paths_from(graph,service) for service in service_names}
    for left_index, a in enumerate(service_names):
        if candidate_cap_hit:
            break
        for b in service_names[left_index+1:]:
            path_ab = paths_by_service[a].get(b)
            path_ba = paths_by_service[b].get(a)
            if not path_ab and not path_ba:
                continue
            left = anomalies[a]; right = anomalies[b]
            left_times = [_dt(row["window_start"]).timestamp() for row in left]
            right_times = [_dt(row["window_start"]).timestamp() for row in right]
            for i, first in enumerate(left):
                stamp = left_times[i]
                lo = bisect_left(right_times, stamp-config.cross_service_max_lag_seconds)
                hi = bisect_right(right_times, stamp+config.cross_service_max_lag_seconds)
                for j in range(lo, hi):
                    if considered >= config.cross_service_max_candidate_pairs:
                        candidate_cap_hit = True
                        break
                    second = right[j]; delta = stamp-right_times[j]; considered += 1
                    if len(relationships) >= config.cross_service_max_relationships:
                        truncated += 1
                        continue
                    if first["window_start"] == second["window_start"]:
                        relation = "simultaneous_dependency_neighbor_anomalies"
                    elif (path_ab and delta > 0) or (path_ba and delta < 0):
                        relation = "dependency_service_anomaly_preceded_dependent_service_anomaly"
                    else:
                        relation = "dependency_related_anomalies_within_time_range"
                    chosen_path = path_ab or path_ba
                    dep_evidence = [edges[(chosen_path[k], chosen_path[k+1])].to_dict()
                        for k in range(len(chosen_path)-1) if (chosen_path[k], chosen_path[k+1]) in edges]
                    relationships.append({"finding_type": relation, "service_ids": [a,b],
                        "anomaly_windows": [{"service_id":a,"window_start":first["window_start"],"detectors":first["detectors"]},
                            {"service_id":b,"window_start":second["window_start"],"detectors":second["detectors"]}],
                        "time_difference_seconds_a_minus_b":delta,"dependency_path":chosen_path,"dependency_evidence":dep_evidence,
                        "evidence_references":[{"service_id":item["service_id"],"window_start":item["window_start"],
                            "event_references":item["evidence_references"],"event_reference_count":item["evidence_reference_count"]} for item in (first,second)],
                        "competing_explanations":["shared upstream condition","independent services responding to common traffic variation","timestamp/window alignment artifact"],
                        "confidence_limitations":["Configured dependency topology may be incomplete or stale.","Anomaly timing and dependency structure do not establish propagation or causation."],
                        "interpretation":"contextual dependency relationship only"})
                if candidate_cap_hit:
                    break
            if candidate_cap_hit:
                break
    return {"status": "analyzed", "graph_version": graph.graph_version,
        "relationships": relationships, "anomalous_service_count": len(anomalies),
        "dependency_direction": "A -> B means A depends on B; candidate paths are reported in configured edge direction.",
        "relationship_count": len(relationships), "candidate_pair_count": considered,
        "truncated_relationship_count": truncated,"max_relationships":config.cross_service_max_relationships,
        "candidate_pairs_truncated":candidate_cap_hit,"max_candidate_pairs":config.cross_service_max_candidate_pairs}


def _dt(value: Any):
    if not isinstance(value, str): return None
    try: return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError: return None


def _paths_from(graph: DependencyGraph, start: str) -> dict[str,list[str]]:
    """All shortest configured directed paths from one source in O(V+E)."""
    adjacency: dict[str,list[str]]=defaultdict(list)
    for edge in graph.dependencies: adjacency[edge.source_service_id].append(edge.target_service_id)
    for values in adjacency.values(): values.sort()
    paths={start:[start]}; queue=deque([start])
    while queue:
        current=queue.popleft()
        for target in adjacency.get(current,[]):
            if target not in paths:
                paths[target]=[*paths[current],target]; queue.append(target)
    return paths
