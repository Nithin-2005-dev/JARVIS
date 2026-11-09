"""Deterministic synthetic evaluation with time-ordered, per-detector metrics."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from .anomaly_detection import detect_anomalies
from .baseline import build_baselines
from .cross_service_analysis import analyze_cross_service
from .feature_extraction import event_signature, extract_features
from .models import IntelligenceConfig
from .pattern_discovery import discover_patterns
from ..dependency_graph.graph_builder import DependencyGraphBuilder
from ..dependency_graph.service_registry import default_config

BASE = datetime(2025, 1, 1, tzinfo=timezone.utc)
SCENARIOS = (
    "normal_stable_traffic", "sudden_error_rate_increase", "gradual_service_degradation",
    "repeated_error_bursts", "abnormal_event_frequency", "cross_service_anomalies",
    "dependency_degradation_precedes_dependents", "cold_start_insufficient_history",
    "missing_and_invalid_timestamps", "detector_disagreement", "benign_normal_variation",
    "recurring_incident_fingerprints",
)


def build_synthetic_dataset() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Create event records and labeled evaluation windows with no random draws."""
    events: list[dict[str, Any]] = []; labels: dict[tuple[str, int], set[str]] = {}
    services = ["database-service", "payment-service", "api-gateway", "authentication-service", "notification-service", "benign-variation"]
    for index in range(40):
        for service in services:
            count = 10; errors = 0
            if service == "benign-variation": count = (8, 10, 12, 9, 11)[index % 5]
            if service == "authentication-service" and 25 <= index <= 29: errors = 7
            if service == "payment-service" and index >= 25: errors = min(8, max(1, index - 24))
            if service == "database-service" and index in {22, 30, 36}: errors = 5
            if service == "api-gateway" and index == 27: count = 35
            if index == 34 and service == "database-service": errors = 8
            if index == 35 and service == "payment-service": errors = 8
            if index == 36 and service == "api-gateway": errors = 8
            if index == 37 and service == "database-service": errors = 7
            if index == 38 and service == "payment-service": errors = 7
            scenarios = set()
            if service == "authentication-service" and 25 <= index <= 29: scenarios.add("sudden_error_rate_increase")
            if service == "payment-service" and index >= 25: scenarios.add("gradual_service_degradation")
            if service == "database-service" and index in {22,30,36}: scenarios.update({"repeated_error_bursts", "recurring_incident_fingerprints"})
            if service == "api-gateway" and index == 27: scenarios.add("abnormal_event_frequency")
            if (service,index) in {("database-service",34),("payment-service",35),("api-gateway",36)}: scenarios.add("cross_service_anomalies")
            if (service,index) in {("database-service",37),("payment-service",38)}: scenarios.add("dependency_degradation_precedes_dependents")
            if scenarios and index >= 20: labels.setdefault((service,index),set()).update(scenarios)
            for offset in range(count):
                failed = offset < errors
                event_type = "db_pool_exhausted" if failed and service == "database-service" else ("request_failed" if failed else "request_completed")
                message = "connection pool exhausted" if failed and service == "database-service" else ("upstream request failed" if failed else "request completed")
                timestamp = BASE + timedelta(seconds=index*300 + offset*4)
                event_id = f"eval-{service}-{index:02d}-{offset:03d}"
                events.append({"event_id": event_id, "original_event": {"event_id": event_id,
                    "service": service, "event_type": event_type, "severity": "ERROR" if failed else "INFO",
                    "message": message, "timestamp": timestamp.isoformat().replace("+00:00", "Z"), "source": "stage7-synthetic"}})
    # A cold-start service has a single event-time window only at the evaluation tail.
    for offset in range(5):
        timestamp = BASE + timedelta(seconds=39*300 + offset)
        event_id = f"eval-cold-start-39-{offset}"
        events.append({"event_id": event_id, "original_event": {"event_id": event_id, "service": "cold-start-service",
            "event_type": "request_completed", "severity": "INFO", "message": "cold start request",
            "timestamp": timestamp.isoformat().replace("+00:00", "Z"), "source": "stage7-synthetic"}})
    for event_id, timestamp in (("eval-invalid-missing", None), ("eval-invalid-malformed", "not-a-time")):
        payload = {"event_id": event_id, "service": "timestamp-quality-service", "event_type": "request_completed", "severity": "INFO", "message": "timestamp quality case"}
        if timestamp is not None: payload["timestamp"] = timestamp
        events.append({"event_id": event_id, "original_event": payload})
    known_pattern_events = [event for event in events if event["original_event"]["service"] == "database-service"
        and event["original_event"]["message"] == "connection pool exhausted"]
    return events, {"scenario_names": list(SCENARIOS), "training_window_indices": list(range(20)),
        "evaluation_window_indices": list(range(20,40)),
        "anomalous_windows": [{"service_id": service, "window_index": index, "scenarios": sorted(scenarios)}
                              for (service,index),scenarios in sorted(labels.items())],
        "known_recurring_signature": event_signature(known_pattern_events[0]) if known_pattern_events else None,
        "scenario_denominator": len(SCENARIOS), "dataset_event_count": len(events),
        "notes": "Hand-authored ground truth; window index is fixed event-time order. This is a mechanism check, not a representative production distribution."}


def run_evaluation(config: IntelligenceConfig | None = None) -> dict[str, Any]:
    config = config or IntelligenceConfig(minimum_baseline_windows=4, isolation_minimum_samples=12)
    events, truth = build_synthetic_dataset(); started = perf_counter()
    extracted = extract_features(events, config); features = extracted["features"]
    baselines = build_baselines(features, config)["baselines"]
    detected = detect_anomalies(features, baselines, config)
    combined_detectors = [*detected["statistical_findings"], *detected["machine_learning_findings"]]
    graph = DependencyGraphBuilder(default_config()).build()
    cross_service = analyze_cross_service(combined_detectors, graph, config)
    split = BASE + timedelta(seconds=20*300)
    eval_features = [row for row in features if row["window_start"] >= split.isoformat().replace("+00:00", "Z")]
    expected = {(item["service_id"], (BASE+timedelta(seconds=item["window_index"]*300)).isoformat().replace("+00:00", "Z")) for item in truth["anomalous_windows"]}
    stat_pred = _predictions(detected["statistical_findings"], eval_features)
    ml_pred = _predictions(detected["machine_learning_findings"], eval_features)
    stat_metrics = _metrics(expected, stat_pred, eval_features)
    ml_metrics = _metrics(expected, ml_pred, eval_features)
    pattern_report = discover_patterns(events, [], config)
    exact_found = {p["event_signature"] for p in pattern_report["exact_signature_patterns"]}
    pattern_expected = {truth["known_recurring_signature"]} if truth["known_recurring_signature"] else set()
    tp = len(exact_found & pattern_expected); fp = len(exact_found - pattern_expected); fn = len(pattern_expected - exact_found)
    baseline_ready = sum(row["status"] == "ready" for row in baselines if row["target_window_start"] >= split.isoformat().replace("+00:00", "Z"))
    evaluation_windows = [row for row in features if row["window_start"] >= split.isoformat().replace("+00:00", "Z")]
    baseline_leakage = all(all(start < row["window_start"] for start in baseline["training_window_starts"])
                  for row in evaluation_windows for baseline in baselines if baseline["service_id"] == row["service_id"] and baseline["target_window_start"] == row["window_start"])
    model_leakage = all(all(start < model["target_window_start"] for start in model["training_window_starts"])
                  for model in detected["model_artifacts"])
    detector_disagreement = len({(x["service_id"], x["window_start"]) for x in detected["statistical_findings"] if x["finding_type"] == "statistical_anomaly"} ^
                                {(x["service_id"], x["window_start"]) for x in detected["machine_learning_findings"] if x["finding_type"] == "ml_anomaly"})
    scenario_results = _scenario_results(truth, expected, stat_pred, ml_pred, features, extracted, pattern_report, cross_service)
    return {"methodology": "Time-ordered per-service window evaluation. Windows 0–19 precede the evaluation period; each scored window baseline/forest is trained only from strictly earlier windows. Classification is at service-window level; multiple features in one window count as one predicted anomaly.",
        "scenario_names": list(SCENARIOS), "scenario_denominator": len(SCENARIOS), "scenario_results": scenario_results,
        "dataset_event_count": len(events), "feature_window_count": len(features),
        "training_window_index_range": [0,19], "evaluation_window_index_range": [20,39],
        "anomaly_ground_truth_window_count": len(expected), "statistical": stat_metrics, "machine_learning": ml_metrics,
        "baseline_coverage": {"ready": baseline_ready, "evaluation_service_windows": len(evaluation_windows), "rate": baseline_ready/len(evaluation_windows) if evaluation_windows else 0},
        "insufficient_data_rate": {"windows": sum(row["status"] != "ready" for row in baselines), "all_service_windows": len(baselines), "rate": sum(row["status"] != "ready" for row in baselines)/len(baselines) if baselines else 0},
        "pattern": {"expected_recurring_signatures": len(pattern_expected), "discovered_exact_signatures": len(exact_found),
            "precision": tp/(tp+fp) if tp+fp else 0, "recall": tp/(tp+fn) if tp+fn else 0,
            "true_positive": tp, "false_positive": fp, "false_negative": fn},
        "detector_disagreement_window_count": detector_disagreement,
        "cross_service_relationship_count": cross_service["relationship_count"],
        "cross_service_candidate_pair_count": cross_service["candidate_pair_count"],
        "cross_service_truncated_relationship_count": cross_service["truncated_relationship_count"],
        "timestamp_quality": {"invalid_timestamp_events": extracted["events_with_invalid_timestamps"], "valid_timestamp_events": extracted["events_with_valid_timestamps"]},
        "baseline_no_future_data_leakage": baseline_leakage, "model_no_future_data_leakage": model_leakage,
        "no_future_data_leakage": baseline_leakage and model_leakage,
        "evaluation_duration_seconds": round(perf_counter()-started,6),
        "detector_settings": detected["detector_comparison"],
        "limitations": ["Synthetic incidents and baselines are manually authored and simplified.", "Thresholds are configuration choices, not calibrated probabilities.", "No claim of production precision, recall, or delay is made."]}


def write_evaluation(output_dir: str | Path) -> dict[str, Any]:
    directory = Path(output_dir); directory.mkdir(parents=True, exist_ok=True)
    config = IntelligenceConfig(minimum_baseline_windows=4, isolation_minimum_samples=12)
    events, ground_truth = build_synthetic_dataset()
    result = run_evaluation(config)
    (directory/"stage7_synthetic_events.jsonl").write_text("".join(json.dumps(event, sort_keys=True)+"\n" for event in events), encoding="utf-8")
    (directory/"stage7_ground_truth.json").write_text(json.dumps(ground_truth,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    (directory/"stage7_intelligence_metrics.json").write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    return result


def _predictions(rows: list[dict[str, Any]], eval_features: list[dict[str, Any]]) -> set[tuple[str,str]]:
    valid = {(row["service_id"], row["window_start"]) for row in eval_features}
    return {(row["service_id"], row["window_start"]) for row in rows if row.get("finding_type") in {"statistical_anomaly", "ml_anomaly"} and (row["service_id"],row["window_start"]) in valid}


def _metrics(expected: set[tuple[str,str]], predicted: set[tuple[str,str]], eval_features: list[dict[str,Any]]) -> dict[str,Any]:
    universe={(row["service_id"],row["window_start"]) for row in eval_features}; tp=len(expected&predicted); fp=len(predicted-expected); fn=len(expected-predicted); tn=len(universe-expected-predicted)
    precision=tp/(tp+fp) if tp+fp else 0.0; recall=tp/(tp+fn) if tp+fn else 0.0
    expected_service_times: dict[str,list[str]]={}
    for service,window in expected: expected_service_times.setdefault(service,[]).append(window)
    delays=[]
    for service, windows in expected_service_times.items():
        first_expected=min(windows); detected=sorted(w for sid,w in predicted if sid==service and w>=first_expected)
        if detected: delays.append((datetime.fromisoformat(detected[0].replace("Z","+00:00"))-datetime.fromisoformat(first_expected.replace("Z","+00:00"))).total_seconds())
    return {"true_positive":tp,"false_positive":fp,"false_negative":fn,"true_negative":tn,
        "precision":precision,"recall":recall,"f1":2*precision*recall/(precision+recall) if precision+recall else 0.0,
        "false_positive_rate":fp/(fp+tn) if fp+tn else 0.0,"ground_truth_positive_denominator":tp+fn,
        "prediction_denominator":tp+fp,"negative_window_denominator":fp+tn,"evaluation_service_window_count":len(universe),
        "mean_detection_delay_seconds":sum(delays)/len(delays) if delays else None,"detection_delay_sequence_count":len(delays)}


def _scenario_results(truth: dict[str,Any], expected: set[tuple[str,str]], stat_pred: set[tuple[str,str]],
                      ml_pred: set[tuple[str,str]], features: list[dict[str,Any]], extracted: dict[str,Any],
                      pattern_report: dict[str,Any], cross_service: dict[str,Any]) -> list[dict[str,Any]]:
    records=[]
    for scenario in SCENARIOS:
        keys={(item["service_id"],(BASE+timedelta(seconds=item["window_index"]*300)).isoformat().replace("+00:00","Z"))
              for item in truth["anomalous_windows"] if scenario in item["scenarios"]}
        if keys:
            record={"scenario":scenario,"ground_truth_windows":len(keys),
                "statistical_detected":len(keys&stat_pred),"statistical_recall":len(keys&stat_pred)/len(keys),
                "ml_detected":len(keys&ml_pred),"ml_recall":len(keys&ml_pred)/len(keys),"status":"measured"}
            if scenario in {"cross_service_anomalies","dependency_degradation_precedes_dependents"}:
                expected_pairs = ([(("database-service",34),("payment-service",35)), (("payment-service",35),("api-gateway",36)), (("database-service",34),("api-gateway",36))] if scenario=="cross_service_anomalies" else [(("database-service",37),("payment-service",38))])
                actual_pairs=set()
                for relationship in cross_service["relationships"]:
                    observed={(entry["service_id"],entry["window_start"]) for entry in relationship["anomaly_windows"]}
                    actual_pairs.add(frozenset(observed))
                expected_keys=[frozenset({(a,_window(t1)),(b,_window(t2))}) for (a,t1),(b,t2) in expected_pairs]
                record["dependency_context_relationships_found"] = sum(pair in actual_pairs for pair in expected_keys)
                record["dependency_context_relationship_denominator"] = len(expected_keys)
            records.append(record)
        elif scenario == "normal_stable_traffic":
            # The generated fixture contains 20 historical stable windows for every established service.
            normal_windows=[row for row in features if row["service_id"] in {"database-service","payment-service","api-gateway","authentication-service","notification-service"} and row["window_start"] < (BASE+timedelta(seconds=20*300)).isoformat().replace("+00:00","Z")]
            records.append({"scenario":scenario,"stable_training_windows":len(normal_windows),"status":"included_in_time_ordered_training"})
        elif scenario == "benign_normal_variation":
            benign=[row for row in features if row["service_id"]=="benign-variation" and row["window_start"] >= (BASE+timedelta(seconds=20*300)).isoformat().replace("+00:00","Z")]
            keys_b={(row["service_id"],row["window_start"]) for row in benign}
            records.append({"scenario":scenario,"normal_variation_windows":len(keys_b),
                "statistical_false_alarms":len(keys_b&stat_pred),"ml_false_alarms":len(keys_b&ml_pred),"status":"normal_false_positive_probe"})
        elif scenario == "cold_start_insufficient_history":
            cold=[row for row in features if row["service_id"]=="cold-start-service"]
            records.append({"scenario":scenario,"observed_windows":len(cold),"insufficient_baseline":bool(cold and len(cold)<4),"status":"passed" if cold and len(cold)<4 else "failed"})
        elif scenario == "missing_and_invalid_timestamps":
            invalid=extracted["events_with_invalid_timestamps"]
            records.append({"scenario":scenario,"invalid_timestamp_events":invalid,"status":"passed" if invalid==2 else "failed"})
        elif scenario == "detector_disagreement":
            records.append({"scenario":scenario,"disagreeing_evaluation_windows":len(stat_pred^ml_pred),"status":"observed" if stat_pred^ml_pred else "no_disagreement"})
        elif scenario == "recurring_incident_fingerprints":
            expected_sig=truth.get("known_recurring_signature")
            found={p["event_signature"] for p in pattern_report["exact_signature_patterns"]}
            records.append({"scenario":scenario,"expected_signature_found":expected_sig in found,"status":"passed" if expected_sig in found else "failed"})
        else:
            records.append({"scenario":scenario,"status":"represented_by_labeled_window_evaluation"})
    return records


def _window(index:int)->str:
    return (BASE+timedelta(seconds=index*300)).isoformat().replace("+00:00","Z")


if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--output-dir",default="data/evaluation")
    args=parser.parse_args(); print(json.dumps(write_evaluation(args.output_dir),sort_keys=True,indent=2))
