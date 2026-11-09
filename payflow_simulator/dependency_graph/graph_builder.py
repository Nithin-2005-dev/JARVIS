"""Deterministic graph construction and structured topology validation."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Iterable

from .models import Dependency, DependencyGraph, Service, ValidationFinding
from .service_registry import DependencyGraphConfig


class DependencyGraphBuilder:
    """Build a graph while retaining invalid definitions as findings/data."""
    def __init__(self, config: DependencyGraphConfig): self.config = config

    def build(self, services: Iterable[Service] | None = None,
              dependencies: Iterable[Dependency] | None = None) -> DependencyGraph:
        service_rows = sorted(tuple(services if services is not None else self.config.services),
                              key=lambda x: (x.service_id, json.dumps(x.to_dict(), sort_keys=True, default=str)))
        dependency_rows = sorted(tuple(dependencies if dependencies is not None else self.config.dependencies),
                                 key=lambda x: (x.source_service_id, x.target_service_id, x.dependency_type,
                                                json.dumps(x.to_dict(), sort_keys=True, default=str)))
        findings: list[ValidationFinding] = []
        nodes: dict[str, Service] = {}
        for service in service_rows:
            if not isinstance(service.service_id, str) or not service.service_id.strip():
                findings.append(ValidationFinding("empty_service_id", "error", "Service ID must not be empty.")); continue
            if service.service_id in nodes:
                findings.append(ValidationFinding("duplicate_service", "error", "Service ID is defined more than once.", {"service_id": service.service_id}))
                continue
            if service.criticality not in self.config.criticality_factors:
                findings.append(ValidationFinding("unknown_criticality", "warning", "Service criticality has no configured scoring factor.", {"service_id": service.service_id, "criticality": service.criticality}))
            if not isinstance(service.service_name, str) or not service.service_name.strip():
                findings.append(ValidationFinding("missing_service_name", "error", "Service display name must not be empty.", {"service_id": service.service_id}))
            if not isinstance(service.environment, str) or not service.environment.strip():
                findings.append(ValidationFinding("missing_service_environment", "error", "Service environment must not be empty.", {"service_id": service.service_id}))
            nodes[service.service_id] = service

        unique: dict[tuple[str, str, str], Dependency] = {}
        for edge in dependency_rows:
            key = (edge.source_service_id, edge.target_service_id, edge.dependency_type)
            if key in unique:
                findings.append(ValidationFinding("duplicate_dependency", "warning", "Duplicate dependency edge was collapsed to one deterministic definition.", {"source_service_id": key[0], "target_service_id": key[1], "dependency_type": key[2]}))
                continue
            unique[key] = edge
            if edge.source_service_id not in nodes:
                findings.append(ValidationFinding("missing_source_service", "error", "Dependency source service is not defined.", {"dependency": edge.to_dict()}))
            if edge.target_service_id not in nodes:
                findings.append(ValidationFinding("missing_target_service", "error", "Dependency target service is not defined.", {"dependency": edge.to_dict()}))
            if edge.source_service_id == edge.target_service_id:
                findings.append(ValidationFinding("self_dependency", "error", "A service cannot depend on itself.", {"service_id": edge.source_service_id, "dependency_type": edge.dependency_type}))
            if edge.dependency_type not in self.config.known_dependency_types:
                findings.append(ValidationFinding("unknown_dependency_type", "warning", "Dependency type is retained but is not in the configured known type list.", {"dependency_type": edge.dependency_type, "source_service_id": edge.source_service_id, "target_service_id": edge.target_service_id}))
            try: importance_valid = 0 <= float(edge.importance) <= 1
            except (TypeError, ValueError): importance_valid = False
            if not importance_valid:
                findings.append(ValidationFinding("invalid_importance", "error", "Dependency importance must be within [0, 1].", {"dependency": edge.to_dict()}))
            if edge.confidence is not None:
                try: confidence_valid = 0 <= float(edge.confidence) <= 1
                except (TypeError, ValueError): confidence_valid = False
                if not confidence_valid: findings.append(ValidationFinding("invalid_confidence", "error", "Dependency confidence must be within [0, 1].", {"dependency": edge.to_dict()}))
            if edge.verification_status not in self.config.verification_factors:
                findings.append(ValidationFinding("unknown_verification_status", "warning", "Dependency verification status has no configured factor.", {"verification_status": edge.verification_status, "dependency_id": edge.dependency_id}))

        edges = tuple(unique[key] for key in sorted(unique))
        adjacency: dict[str, list[str]] = defaultdict(list)
        for edge in edges:
            if edge.source_service_id in nodes and edge.target_service_id in nodes:
                adjacency[edge.source_service_id].append(edge.target_service_id)
        weak_components = _weak_components(nodes, adjacency)
        if len(weak_components) > 1:
            primary = min(weak_components, key=lambda members: (-len(members), members[0]))
            for component in weak_components:
                if component == primary: continue
                for node in component:
                    findings.append(ValidationFinding("disconnected_service", "info", "Service belongs to a disconnected weakly connected component.", {"service_id": node, "component_service_ids": component, "component_count": len(weak_components)}))
        for cycle in _cycles(nodes, adjacency):
            findings.append(ValidationFinding("dependency_cycle", "warning", "Directed dependency cycle detected; traversal will use visited-node protection.", {"service_ids": cycle}))

        config_payload = self.config.to_dict()
        config_payload["services"] = [x.to_dict() for x in nodes.values()]
        config_payload["dependencies"] = [x.to_dict() for x in edges]
        serialized = {"config": config_payload, "services": [x.to_dict() for x in nodes.values()],
                      "dependencies": [x.to_dict() for x in edges],
                      "findings": [x.to_dict() for x in sorted(findings, key=lambda f: (f.code, json.dumps(f.context, sort_keys=True, default=str)))]}
        version = hashlib.sha256(json.dumps(serialized, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        return DependencyGraph(version, nodes, edges, tuple(sorted(findings, key=lambda f: (f.code, json.dumps(f.context, sort_keys=True, default=str)))), config_payload)


def _cycles(nodes: dict[str, Service], adjacency: dict[str, list[str]]) -> list[list[str]]:
    """Tarjan SCC; return deterministic SCCs that contain a directed cycle."""
    index = 0; stack: list[str] = []; on_stack: set[str] = set()
    indices: dict[str, int] = {}; low: dict[str, int] = {}; result: list[list[str]] = []
    def visit(node: str) -> None:
        nonlocal index
        indices[node] = low[node] = index; index += 1
        stack.append(node); on_stack.add(node)
        for target in sorted(adjacency.get(node, [])):
            if target not in indices:
                visit(target); low[node] = min(low[node], low[target])
            elif target in on_stack: low[node] = min(low[node], indices[target])
        if low[node] == indices[node]:
            component: list[str] = []
            while True:
                item = stack.pop(); on_stack.remove(item); component.append(item)
                if item == node: break
            component.sort()
            if len(component) > 1 or node in adjacency.get(node, []): result.append(component)
    for node in sorted(nodes):
        if node not in indices: visit(node)
    return sorted(result)


def _weak_components(nodes: dict[str, Service], adjacency: dict[str, list[str]]) -> list[list[str]]:
    neighbors: dict[str, set[str]] = {node: set() for node in nodes}
    for source, targets in adjacency.items():
        for target in targets:
            neighbors[source].add(target); neighbors[target].add(source)
    seen: set[str] = set(); components=[]
    for start in sorted(nodes):
        if start in seen: continue
        stack=[start]; seen.add(start); members=[]
        while stack:
            node=stack.pop(); members.append(node)
            for other in sorted(neighbors[node], reverse=True):
                if other not in seen: seen.add(other); stack.append(other)
        components.append(sorted(members))
    return sorted(components, key=lambda x:x[0])
