"""Cycle-safe impact traversal, transparent scores, and Stage 4/5 incident integration."""
from __future__ import annotations

import hashlib
import json
from collections import deque
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from .graph_builder import DependencyGraphBuilder
from .graph_store import SQLiteDependencyGraphStore
from .models import Dependency, DependencyGraph, ImpactedService
from .service_registry import DependencyGraphConfig, config_from_dict, default_config


class BlastRadiusAnalyzer:
    """Analyze structural potential; downstream membership is not proof of failure."""
    def __init__(self, graph: DependencyGraph): self.graph = graph

    def analyze(self, service_id: str, *, max_depth: int | None = None, environment: str | None = None,
                incident_context: Mapping[str, Any] | None = None,
                scenario_label: str = "hypothetical_service_failure",
                rca_investigation_id: str | None = None,
                candidate_event_id: str | None = None) -> dict[str, Any]:
        if service_id not in self.graph.services:
            raise KeyError(f"unknown service ID: {service_id}")
        if max_depth is not None and max_depth < 1: raise ValueError("max_depth must be positive")
        root = self.graph.services[service_id]
        if environment and root.environment != environment:
            raise ValueError(f"root service {service_id} is outside environment {environment}")
        allowed = {sid for sid, service in self.graph.services.items() if not environment or service.environment == environment}
        environment_excluded = [edge.to_dict() for edge in self.graph.dependencies
            if edge.source_service_id in self.graph.services and edge.target_service_id in self.graph.services
            and (edge.source_service_id in allowed) != (edge.target_service_id in allowed)] if environment else []
        parents: dict[str, list[Dependency]] = {}
        for edge in self.graph.dependencies:
            if edge.source_service_id in allowed and edge.target_service_id in allowed:
                parents.setdefault(edge.target_service_id, []).append(edge)
        for values in parents.values(): values.sort(key=lambda d: (d.source_service_id, d.target_service_id, d.dependency_type))
        shortest: dict[str, int] = {service_id: 0}; queue = deque([service_id])
        while queue:
            current = queue.popleft()
            depth = shortest[current]
            if max_depth is not None and depth >= max_depth: continue
            for edge in parents.get(current, []):
                impacted = edge.source_service_id
                if impacted == service_id: continue
                if impacted not in shortest:
                    shortest[impacted] = depth + 1; queue.append(impacted)

        incident_events = (incident_context or {}).get("events", [])
        evidence_by_service: dict[str, list[dict[str, Any]]] = {}
        for processed in incident_events:
            original = processed.get("original_event", processed)
            event_service = original.get("service")
            if event_service:
                evidence_by_service.setdefault(str(event_service), []).append({
                    "event_id": str(original.get("event_id", processed.get("event_id", ""))),
                    "severity": original.get("severity"), "event_type": original.get("event_type"),
                    "message": original.get("message"), "event_time": original.get("timestamp"),
                    "classification_categories": processed.get("classification", {}).get("categories", []),
                    "evidence_kind": "observed_incident_event"})
        impacted_results: list[ImpactedService] = []
        truncated_paths: list[str] = []
        for impacted_id, depth in sorted(shortest.items(), key=lambda x: (x[1], x[0])):
            if impacted_id == service_id: continue
            paths, truncated = self._paths(service_id, impacted_id, max_depth, allowed)
            if truncated: truncated_paths.append(impacted_id)
            paths = tuple(paths)
            primary = paths[0] if paths else (service_id, impacted_id)
            path_edges = [self._edge_for(primary[i + 1], primary[i]) for i in range(len(primary) - 1)]
            importance_factor = _product([_factor(edge.importance) for edge in path_edges])
            confidence_factors = [_dependency_confidence(edge, self.graph.config) for edge in path_edges]
            confidence_factor = _product([_factor(value) for value in confidence_factors])
            service = self.graph.services[impacted_id]
            criticality_factor = float(self.graph.config.get("criticality_factors", {}).get(service.criticality, self.graph.config.get("criticality_factors", {}).get("unknown", .25)))
            depth_decay = float(self.graph.config.get("depth_decay", .85)) ** max(0, depth - 1)
            direct_dependents = len(parents.get(impacted_id, []))
            fanout_factor = min(1.0, float(self.graph.config.get("fanout_base", .7)) + float(self.graph.config.get("fanout_increment", .1)) * direct_dependents)
            score = round(max(0.0, min(1.0, criticality_factor * importance_factor * confidence_factor * depth_decay * fanout_factor)), 4)
            event_facts = sorted(evidence_by_service.get(impacted_id, []), key=lambda e: (e["event_time"] or "", e["event_id"]))
            failure_signals = [e for e in event_facts if str(e.get("severity", "")).upper() in {"ERROR", "CRITICAL", "FATAL"}
                               or any(category != "service_lifecycle_events" for category in e.get("classification_categories", []))]
            breakdown = {"service_criticality_factor": criticality_factor, "dependency_importance_product": round(importance_factor, 4),
                         "dependency_confidence_product": round(confidence_factor, 4), "depth_decay_factor": round(depth_decay, 4),
                         "direct_dependent_fanout_factor": round(fanout_factor, 4),
                         "formula": "criticality_factor × product(path dependency importance) × product(path dependency confidence) × depth_decay^(depth-1) × fanout_factor",
                         "score_kind": "heuristic_structural_impact_score_not_failure_probability",
                         "scoring_path": list(primary), "path_dependencies": [edge.to_dict() for edge in path_edges]}
            impacted_results.append(ImpactedService(impacted_id, service.service_name, depth, paths, score, breakdown,
                service.criticality, service.business_capability,
                {"impact_kind": "potential_structural_impact", "observed_incident_evidence": event_facts if incident_context is not None else None,
                 "observed_failure_signal_event_ids": [e["event_id"] for e in failure_signals], "confirmed_failure": False,
                 "confirmation_note": "Dependency structure and event observations do not independently confirm service failure."}))

        direct = [x.to_dict() for x in impacted_results if x.depth == 1]
        indirect = [x.to_dict() for x in impacted_results if x.depth > 1]
        impacted_services = [*direct, *indirect]
        crit = {key: sum(1 for item in impacted_results if item.criticality == key) for key in ("critical", "high", "medium", "low", "unknown")}
        capabilities = sorted(({root.business_capability} | {item.business_capability for item in impacted_results}) - {"", "unknown"})
        reachable = set(shortest)
        relevant_findings = [f.to_dict() for f in self.graph.findings if _finding_relevant(f.context, reachable)]
        cycles = [f for f in relevant_findings if f["code"] == "dependency_cycle"]
        unresolved = [edge.to_dict() for edge in self.graph.dependencies
                      if (edge.source_service_id not in self.graph.services or edge.target_service_id not in self.graph.services)
                      and bool({edge.source_service_id, edge.target_service_id} & reachable)]
        for edge in self.graph.dependencies:
            if edge.source_service_id in reachable and edge.target_service_id in reachable and (edge.confidence is None or edge.verification_status not in {"verified", "observed"}):
                unresolved.append(edge.to_dict())
        warnings = ["Blast radius describes potential structural impact, not actual failure or causality."]
        if cycles: warnings.append("Relevant dependency cycles were detected; visited-node protection prevented repeated traversal.")
        if any(f["code"] == "disconnected_service" for f in relevant_findings): warnings.append("The root or an impacted service belongs to a disconnected dependency component.")
        if unresolved: warnings.append("Some graph dependencies are unresolved or insufficiently verified.")
        unknown_types = [f.to_dict() for f in self.graph.findings if f.code == "unknown_dependency_type" and (f.context.get("source_service_id") in reachable or f.context.get("target_service_id") in reachable)]
        if unknown_types: warnings.append("A relevant dependency uses an unrecognized type; it was retained and traversed as a structural edge.")
        if any(f["severity"] == "error" for f in relevant_findings): warnings.append("Relevant graph validation errors may limit impact-score reliability; inspect graph_validation_findings.")
        if truncated_paths: warnings.append("Alternative path enumeration reached its configured per-service limit.")
        if environment_excluded: warnings.append("Dependencies crossing the selected environment boundary were excluded from traversal.")
        incident = (incident_context or {}).get("incident") or {}
        rca = (incident_context or {}).get("rca") or {}
        rca_report = rca.get("report", {})
        report = {"root_service": root.to_dict(), "root_service_id": service_id,
            "scenario_label": scenario_label, "candidate_event_id": candidate_event_id,
            "graph_version": self.graph.graph_version, "maximum_depth": max_depth,
            "environment_filter": environment, "directly_impacted_services": direct,
            "indirectly_impacted_services": indirect, "impacted_services": impacted_services,
            "total_impacted_service_count": len(impacted_results), "impact_depth": max((x.depth for x in impacted_results), default=0),
            "criticality_distribution": crit, "potential_business_capabilities": capabilities,
            "environment_excluded_dependencies": environment_excluded,
            "unresolved_dependencies": _unique_dicts(unresolved), "unknown_dependency_type_findings": unknown_types,
            "graph_validation_findings": relevant_findings, "cycle_findings": cycles, "warnings": warnings,
            "incident_id": incident.get("incident_id"), "rca_investigation_id": rca.get("investigation_id"),
            "root_service_observed_incident_evidence": evidence_by_service.get(service_id, []) if incident_context is not None else None,
            "rca_assessment_status": rca_report.get("assessment_status") if incident_context is not None else None,
            "confirmed_root_cause": False, "analysis_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
        return report

    def _edge_for(self, source: str, target: str) -> Dependency:
        return next(edge for edge in self.graph.dependencies if edge.source_service_id == source and edge.target_service_id == target)

    def _paths(self, root: str, target: str, max_depth: int | None, allowed: set[str]) -> tuple[list[tuple[str, ...]], bool]:
        parents: dict[str, list[str]] = {}
        for edge in self.graph.dependencies:
            if edge.source_service_id in allowed and edge.target_service_id in allowed:
                parents.setdefault(edge.target_service_id, []).append(edge.source_service_id)
        for values in parents.values(): values.sort()
        limit_depth = max_depth if max_depth is not None else max(1, len(self.graph.services) - 1)
        cap = int(self.graph.config.get("max_paths_per_service", 100))
        result: list[tuple[str, ...]] = []; truncated = False
        def visit(node: str, path: tuple[str, ...]) -> None:
            nonlocal truncated
            if truncated: return
            if len(path) - 1 >= limit_depth: return
            for parent in parents.get(node, []):
                if parent in path: continue
                next_path = (*path, parent)
                if parent == target:
                    if len(result) >= cap: truncated = True; return
                    result.append(next_path)
                else: visit(parent, next_path)
        visit(root, (root,))
        result.sort(key=lambda x: (len(x), x))
        return result, truncated


class DependencyGraphEngine:
    """Build/store a graph and persist idempotent blast-radius snapshots."""
    def __init__(self, store: SQLiteDependencyGraphStore, config: DependencyGraphConfig | None = None,
                 graph_version: str | None = None):
        self.store = store
        if graph_version is not None:
            graph = store.load_graph(graph_version)
            if graph is None: raise KeyError(f"unknown graph version: {graph_version}")
            self.graph = graph
            self.config = config_from_dict(graph.config)
        elif config is None and store.graph_snapshot() is not None:
            graph = store.load_graph()
            assert graph is not None
            self.graph = graph
            self.config = config_from_dict(graph.config)
        else:
            self.config = config or default_config()
            self.graph = DependencyGraphBuilder(self.config).build()
            self.store.save_graph(self.graph)
        self.analyzer = BlastRadiusAnalyzer(self.graph)

    def validate(self) -> dict[str, Any]:
        return {"graph_version": self.graph.graph_version, "valid": not any(f.severity == "error" for f in self.graph.findings),
                "findings": [f.to_dict() for f in self.graph.findings]}

    def analyze(self, service_id: str, *, max_depth: int | None = None, environment: str | None = None,
                incident_context: Mapping[str, Any] | None = None, scenario_label: str = "hypothetical_service_failure",
                rca_investigation_id: str | None = None, candidate_event_id: str | None = None) -> dict[str, Any]:
        report = self.analyzer.analyze(service_id, max_depth=max_depth, environment=environment,
            incident_context=incident_context, scenario_label=scenario_label,
            rca_investigation_id=rca_investigation_id, candidate_event_id=candidate_event_id)
        fingerprint_payload = {k: v for k, v in report.items() if k != "analysis_timestamp"}
        fingerprint = hashlib.sha256(_json(fingerprint_payload).encode()).hexdigest()
        analysis_id = str(uuid5(NAMESPACE_URL, "jarvis-blast-radius:" + fingerprint))
        report["analysis_id"] = analysis_id; report["input_fingerprint"] = fingerprint
        existing = self.store.analysis(analysis_id)
        if existing is not None: return existing
        report["analysis_configuration"] = self.config.to_dict()
        self.store.save_analysis(analysis_id, self.graph.graph_version, service_id,
            str((incident_context or {}).get("incident", {}).get("incident_id")) if (incident_context or {}).get("incident") else None,
            rca_investigation_id, fingerprint, report)
        # Return the canonical JSON snapshot so first-run and replay APIs have identical types.
        return self.store.analysis(analysis_id) or report

    def analyze_incident(self, incident_id: str, *, max_depth: int | None = None, environment: str | None = None) -> dict[str, Any]:
        context = self.store.incident_context(incident_id)
        if context is None:
            return {"error": {"code": "incident_not_found", "message": f"Incident {incident_id} was not found."}}
        rca = context.get("rca")
        if not rca:
            return {"error": {"code": "rca_unavailable", "message": "No Stage 5 RCA snapshot exists; provide an explicit --service to run a standalone hypothetical analysis.", "incident_id": incident_id}}
        rca_report = rca.get("report", {}); status = rca_report.get("assessment_status", "unknown")
        candidates: list[Mapping[str, Any]] = []
        if status == "leading_hypothesis" and rca_report.get("leading_hypothesis"):
            candidates = [rca_report["leading_hypothesis"]]
        elif status in {"competing_hypotheses", "inconclusive"}:
            candidates = list(rca_report.get("hypotheses", []))
        if not candidates:
            return {"error": {"code": "service_id_unavailable", "message": "RCA did not provide a usable service candidate; provide an explicit service ID for a hypothetical analysis.", "incident_id": incident_id, "rca_assessment_status": status}}
        results = []; rejected = []
        for candidate in candidates:
            service_id = candidate.get("candidate_service")
            event_id = candidate.get("candidate_event_id")
            if not service_id or service_id not in self.graph.services:
                rejected.append({"candidate_event_id": event_id, "service_id": service_id, "reason": "missing_or_unknown_service_id"}); continue
            results.append(self.analyze(str(service_id), max_depth=max_depth, environment=environment,
                incident_context=context, scenario_label="hypothetical_rca_candidate", rca_investigation_id=rca.get("investigation_id"), candidate_event_id=event_id))
        return {"incident_id": incident_id, "rca_investigation_id": rca.get("investigation_id"),
                "rca_assessment_status": status, "uncertainty_preserved": status in {"competing_hypotheses", "inconclusive"},
                "scenario_analyses": results, "rejected_candidates": rejected,
                "message": "Each result is a hypothetical structural impact scenario; Stage 5 hypotheses are not confirmed causes."}


def _dependency_confidence(edge: Dependency, config: Mapping[str, Any]) -> float:
    if edge.confidence is not None: return edge.confidence
    return float(config.get("verification_factors", {}).get(edge.verification_status, config.get("verification_factors", {}).get("unknown", .3)))

def _product(values: list[float]) -> float:
    result = 1.0
    for value in values: result *= value
    return result

def _factor(value: Any) -> float:
    try: return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError): return 0.0

def _unique_dicts(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found = {_json(value): value for value in values}
    return [found[key] for key in sorted(found)]

def _finding_relevant(context: Mapping[str, Any], reachable: set[str]) -> bool:
    if reachable.intersection(str(x) for x in context.get("service_ids", [])): return True
    if context.get("service_id") in reachable: return True
    if context.get("source_service_id") in reachable or context.get("target_service_id") in reachable: return True
    dependency = context.get("dependency", {})
    return dependency.get("source_service_id") in reachable or dependency.get("target_service_id") in reachable

def _json(value: Any) -> str: return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
