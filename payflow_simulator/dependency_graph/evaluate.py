"""Deterministic synthetic blast-radius expectations and evaluation metrics."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter
from typing import Any

from .blast_radius import BlastRadiusAnalyzer
from .graph_builder import DependencyGraphBuilder
from .models import Dependency
from .service_registry import default_config


SCENARIOS = (
    {"scenario":"database_failure", "root":"database-service", "direct":["payment-service"], "indirect":["api-gateway","notification-service"]},
    {"scenario":"payment_failure", "root":"payment-service", "direct":["api-gateway","notification-service"], "indirect":[]},
    {"scenario":"notification_failure", "root":"notification-service", "direct":[], "indirect":[]},
    {"scenario":"authentication_failure", "root":"authentication-service", "direct":["api-gateway"], "indirect":[]},
    {"scenario":"bounded_database_failure", "root":"database-service", "max_depth":1, "direct":["payment-service"], "indirect":[]},
    {"scenario":"uncertain_external_dependency", "root":"mail-provider", "expected_error":"unknown_service"},
    {"scenario":"unknown_dependency_target", "expected_findings":["missing_target_service","unknown_dependency_type"]},
    {"scenario":"duplicate_dependency_edge", "expected_check":"duplicate_edge_collapsed"},
    {"scenario":"cycle_safe_analysis", "expected_check":"finite_unique_traversal_and_cycle_finding"},
)


def run_evaluation() -> dict[str, Any]:
    graph = DependencyGraphBuilder(default_config()).build(); analyzer = BlastRadiusAnalyzer(graph)
    start = perf_counter(); scored = 0; direct_correct = 0; indirect_correct = 0; path_correct = 0
    direct_tp=direct_fp=direct_fn=indirect_tp=indirect_fp=indirect_fn=0
    reports = []
    for scenario in SCENARIOS:
        if scenario.get("expected_findings"):
            config=default_config()
            graph_with_unknown=DependencyGraphBuilder(type(config)(services=config.services, dependencies=(*config.dependencies,
                Dependency("payment-service","unregistered-cache","distributed_cache",.5)))).build()
            codes={finding.code for finding in graph_with_unknown.findings}
            passed=set(scenario["expected_findings"]) <= codes and any(edge.target_service_id=="unregistered-cache" for edge in graph_with_unknown.dependencies)
            reports.append({"scenario":scenario["scenario"],"passed":passed,"expected_findings":scenario["expected_findings"],"actual_findings":sorted(codes)})
            continue
        if scenario.get("expected_check") == "duplicate_edge_collapsed":
            config=default_config(); duplicate_config=type(config)(services=config.services, dependencies=(*config.dependencies, config.dependencies[0]))
            duplicate_graph=DependencyGraphBuilder(duplicate_config).build()
            duplicate_result=BlastRadiusAnalyzer(duplicate_graph).analyze("database-service")
            ids=[x["service_id"] for x in duplicate_result["impacted_services"]]
            passed=(any(f.code=="duplicate_dependency" for f in duplicate_graph.findings)
                    and len(duplicate_graph.dependencies)==len(config.dependencies) and len(ids)==len(set(ids)))
            reports.append({"scenario":scenario["scenario"],"passed":passed,"expected_check":scenario["expected_check"]})
            continue
        if scenario.get("expected_check") == "finite_unique_traversal_and_cycle_finding":
            config=default_config(); cyclic_config=type(config)(services=config.services, dependencies=(*config.dependencies,
                Dependency("database-service","api-gateway","other",.5)))
            cyclic_graph=DependencyGraphBuilder(cyclic_config).build(); result=BlastRadiusAnalyzer(cyclic_graph).analyze("database-service")
            ids=[x["service_id"] for x in result["impacted_services"]]
            passed=bool(result["cycle_findings"]) and len(ids)==len(set(ids)) and len(ids) <= len(config.services)-1
            reports.append({"scenario":scenario["scenario"],"passed":passed,"expected_check":scenario["expected_check"]})
            continue
        if scenario.get("expected_error"):
            try: analyzer.analyze(scenario["root"])
            except KeyError: passed = True
            else: passed = False
            reports.append({"scenario":scenario["scenario"],"passed":passed,"expected_error":scenario["expected_error"]})
            continue
        result = analyzer.analyze(scenario["root"], max_depth=scenario.get("max_depth"))
        direct = sorted(x["service_id"] for x in result["directly_impacted_services"])
        indirect = sorted(x["service_id"] for x in result["indirectly_impacted_services"])
        direct_ok = direct == sorted(scenario["direct"]); indirect_ok = indirect == sorted(scenario["indirect"])
        expected_direct=set(scenario["direct"]); actual_direct=set(direct)
        expected_indirect=set(scenario["indirect"]); actual_indirect=set(indirect)
        direct_tp += len(expected_direct & actual_direct); direct_fp += len(actual_direct - expected_direct); direct_fn += len(expected_direct - actual_direct)
        indirect_tp += len(expected_indirect & actual_indirect); indirect_fp += len(actual_indirect - expected_indirect); indirect_fn += len(expected_indirect - actual_indirect)
        edge_pairs={(edge.source_service_id, edge.target_service_id) for edge in graph.dependencies}
        all_expected_paths = all(any(path[0] == scenario["root"] and path[-1] == item["service_id"] and
            all((path[i+1], path[i]) in edge_pairs for i in range(len(path)-1)) for path in item["dependency_paths"])
            for item in result["impacted_services"])
        direct_correct += int(direct_ok); indirect_correct += int(indirect_ok); path_correct += int(all_expected_paths); scored += 1
        reports.append({"scenario":scenario["scenario"],"direct_expected":sorted(scenario["direct"]),"direct_actual":direct,
            "indirect_expected":sorted(scenario["indirect"]),"indirect_actual":indirect,
            "direct_correct":direct_ok,"indirect_correct":indirect_ok,"paths_valid":all_expected_paths,
            "total_impacted":result["total_impacted_service_count"],"scores_deterministic":all(0 <= x["impact_score"] <= 1 for x in result["impacted_services"])})
    elapsed = perf_counter() - start
    return {"methodology":"Nine deterministic graph validation/impact scenarios over the configured five-service PayFlow topology; expected impacted sets are manually specified. Unknown root/dependency cases are intentional cannot-establish scenarios; duplicate-edge and cyclic-topology cases evaluate structural safeguards. This evaluates contract behavior, not real-world failure prediction.",
        "graph_version":graph.graph_version,"scenario_count":len(SCENARIOS),"known_root_scenarios":scored,
        "direct_impact_scenario_accuracy":direct_correct/scored if scored else None,
        "direct_impact_scenario_denominator":scored,
        "direct_service_precision":direct_tp/(direct_tp+direct_fp) if direct_tp+direct_fp else 1.0,
        "direct_service_recall":direct_tp/(direct_tp+direct_fn) if direct_tp+direct_fn else 1.0,
        "direct_service_expected_denominator":direct_tp+direct_fn,
        "indirect_impact_scenario_accuracy":indirect_correct/scored if scored else None,
        "indirect_impact_scenario_denominator":scored,
        "indirect_service_precision":indirect_tp/(indirect_tp+indirect_fp) if indirect_tp+indirect_fp else 1.0,
        "indirect_service_recall":indirect_tp/(indirect_tp+indirect_fn) if indirect_tp+indirect_fn else 1.0,
        "indirect_service_expected_denominator":indirect_tp+indirect_fn,
        "path_validity_scenario_rate":path_correct/scored if scored else None,
        "path_validity_scenario_denominator":scored,
        "duplicate_service_handling":"impacted services are unique by service_id; tested separately in unit suite",
        "uncertain_scenario_count":sum(bool(s.get("expected_error") or s.get("expected_findings")) for s in SCENARIOS),
        "uncertain_scenario_passed":all(r["passed"] for r in reports if "expected_error" in r or "expected_findings" in r),
        "structural_behavior_scenarios":sum(bool(s.get("expected_check")) for s in SCENARIOS),
        "structural_behavior_scenarios_passed":all(r["passed"] for r in reports if "expected_check" in r),
        "evaluation_duration_seconds":round(elapsed, 6),"scenarios":reports}


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--output", type=Path); parser.add_argument("--dataset-dir", type=Path)
    args=parser.parse_args(); result=run_evaluation(); encoded=json.dumps(result, sort_keys=True, indent=2)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(encoded, encoding="utf-8")
    if args.dataset_dir:
        args.dataset_dir.mkdir(parents=True, exist_ok=True)
        graph=DependencyGraphBuilder(default_config()).build()
        (args.dataset_dir/"stage6_dependency_scenarios.json").write_text(json.dumps({"graph_version":graph.graph_version,"scenarios":list(SCENARIOS)},sort_keys=True,indent=2)+"\n",encoding="utf-8")
        (args.dataset_dir/"stage6_dependency_ground_truth.json").write_text(json.dumps({s["scenario"]:{"root_service_id":s.get("root"),"directly_impacted":s.get("direct",[]),"indirectly_impacted":s.get("indirect",[]),"expected_error":s.get("expected_error"),"expected_findings":s.get("expected_findings",[]),"expected_check":s.get("expected_check")} for s in SCENARIOS},sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__": main()
