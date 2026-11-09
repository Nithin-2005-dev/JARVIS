"""Reproducible synthetic RCA evaluation; labels are never passed to the engine."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from typing import Any

from .engine import RCAEngine


class _MemoryStore:
    def __init__(self, context: dict[str, Any]): self.context = context; self.saved = {}
    def incident_context(self, incident_id: str) -> dict[str, Any] | None: return self.context if incident_id == self.context["incident"]["incident_id"] else None
    def save_investigation(self, investigation_id: str, incident_id: str, fingerprint: str, report: dict[str, Any]) -> None: self.saved[investigation_id] = report
    def get_investigation(self, investigation_id: str) -> dict[str, Any] | None: return self.saved.get(investigation_id)


def _event(eid: str, service: str, kind: str, severity: str, minute: int, message: str, category: str) -> dict[str, Any]:
    timestamp = f"2025-02-01T00:{minute:02d}:00Z"
    return {"event_id": eid, "original_event": {"event_id": eid, "service": service, "event_type": kind,
        "severity": severity, "timestamp": timestamp, "message": message, "trace_id": f"trace-{service}", "metadata": {}},
        "temporal": {"event_timestamp": timestamp}, "classification": {"categories": [category]}}


def scenarios() -> list[dict[str, Any]]:
    """Build known cause examples with distractors and independent no-answer cases."""
    return [
        {"name":"database_pool_cascade", "truth":"db-root", "events":[
            _event("db-root","database-service","db_pool_exhausted","CRITICAL",2,"database connection pool exhausted","database_failures"),
            _event("pay-symptom","payment-service","downstream_failure","ERROR",3,"database request failed","network_failures"),
            _event("api-symptom","api-gateway","request_failed","ERROR",4,"payment request failed","application_errors")]},
        {"name":"network_initiator", "truth":"network-root", "events":[
            _event("network-root","payment-service","network_failure","CRITICAL",1,"upstream network unavailable","network_failures"),
            _event("notify-symptom","notification-service","downstream_failure","ERROR",2,"notification send failed","network_failures"),
            _event("pay-later","payment-service","payment_retry","ERROR",3,"retry failed","application_errors")]},
        {"name":"resource_exhaustion", "truth":"resource-root", "events":[
            _event("resource-root","database-service","db_pool_exhausted","CRITICAL",5,"connection pool exhausted","database_failures"),
            _event("pool-symptom","payment-service","downstream_failure","ERROR",6,"database timeout","application_errors")]},
        {"name":"ambiguous_multiple_failures", "truth":["db-alt","network-alt"], "events":[
            _event("db-alt","database-service","database_unavailable","CRITICAL",2,"database unavailable","database_failures"),
            _event("network-alt","payment-service","network_failure","CRITICAL",2,"network unavailable","network_failures")]},
        {"name":"inconclusive_missing_signals", "truth":None, "events":[
            _event("generic-1","payment-service","request_failed","ERROR",5,"request failed","application_errors"),
            _event("generic-2","api-gateway","request_failed","ERROR",6,"request failed","application_errors")]},
        {"name":"misleading_earliest_event", "truth":"pool-root", "events":[
            _event("early-symptom","payment-service","request_failed","ERROR",1,"payment operation failed","application_errors"),
            _event("pool-root","database-service","db_pool_exhausted","CRITICAL",2,"pool exhausted","database_failures"),
            _event("later-symptom","api-gateway","request_failed","ERROR",3,"checkout failed","application_errors")]},
    ]


def run_evaluation(top_k: int = 3) -> dict[str, Any]:
    started = time.perf_counter()
    outputs = []
    top1_ok = eligible = hit_k = inconclusive = false_assertions = 0
    for scenario in scenarios():
        events = scenario["events"]
        context = {"incident":{"incident_id":scenario["name"],"summary":scenario["name"]}, "events":events, "correlations":[]}
        report = RCAEngine(_MemoryStore(context)).investigate(scenario["name"])
        truth = scenario["truth"]
        ranked = [h["candidate_event_id"] for h in report["hypotheses"]]
        is_inconclusive = report["assessment_status"] == "inconclusive"
        inconclusive += int(is_inconclusive)
        if truth is None:
            false_assertions += int(not is_inconclusive and report["leading_hypothesis"] is not None)
            outputs.append({"scenario":scenario["name"],"truth":None,"assessment_status":report["assessment_status"],"ranked_candidates":ranked})
            continue
        expected = {truth} if isinstance(truth, str) else set(truth)
        eligible += 1
        top1_ok += int(bool(ranked) and ranked[0] in expected)
        hit_k += int(bool(set(ranked[:top_k]) & expected))
        false_assertions += int(is_inconclusive or (report["leading_hypothesis"] is not None and report["leading_hypothesis"]["candidate_event_id"] not in expected))
        outputs.append({"scenario":scenario["name"],"truth":sorted(expected),"assessment_status":report["assessment_status"],"ranked_candidates":ranked,"top1_correct":bool(ranked and ranked[0] in expected),"truth_in_top_k":bool(set(ranked[:top_k]) & expected)})
    elapsed = time.perf_counter() - started
    event_count = sum(len(scenario["events"]) for scenario in scenarios())
    return {"methodology":"Six fixed synthetic incident groups, manually labeled initiating event(s); truth labels are excluded from engine input. Metrics are scenario-level and do not establish real-world accuracy.",
            "scenario_count":len(outputs),"labeled_root_cause_scenarios":eligible,"top_k":top_k,
            "top1_accuracy":top1_ok/eligible if eligible else None,"top_k_candidate_recall":hit_k/eligible if eligible else None,
            "inconclusive_assessment_rate":inconclusive/len(outputs) if outputs else None,
            "false_root_cause_assertion_rate":false_assertions/len(outputs) if outputs else None,
            "performance":{"events_evaluated":event_count,"elapsed_seconds":round(elapsed,6),"events_per_second":round(event_count/elapsed,2) if elapsed else None,"memory_measurement":"not collected"},
            "scenarios":outputs}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="optional path for JSON evaluation report")
    parser.add_argument("--dataset-dir", type=Path, help="write deterministic JSONL observations and separate ground-truth labels")
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()
    result = run_evaluation(args.top_k)
    encoded = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(encoded, encoding="utf-8")
    if args.dataset_dir:
        args.dataset_dir.mkdir(parents=True, exist_ok=True)
        with (args.dataset_dir / "stage5_synthetic_events.jsonl").open("w", encoding="utf-8") as stream:
            for scenario in scenarios():
                for event in scenario["events"]:
                    stream.write(json.dumps({"scenario": scenario["name"], "processed_event": event}, sort_keys=True) + "\n")
        labels = {scenario["name"]: {"initiating_event_ids": scenario["truth"], "interpretation": "synthetic scenario label; not provided to RCA engine"} for scenario in scenarios()}
        (args.dataset_dir / "stage5_ground_truth.json").write_text(json.dumps(labels, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__": main()
