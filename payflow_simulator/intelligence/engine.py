"""Orchestration API for reproducible intelligence analysis over processed events."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .anomaly_detection import detect_anomalies
from .baseline import build_baselines
from .cross_service_analysis import analyze_cross_service
from .feature_extraction import extract_features
from .models import IntelligenceConfig
from .pattern_discovery import discover_patterns
from .scoring import score_description
from .storage import SQLiteIntelligenceStore
from .temporal_analysis import analyze_temporal


class IntelligenceEngine:
    """Build causal-time-safe baselines, anomaly signals, patterns and context."""
    def __init__(self, store: SQLiteIntelligenceStore, config: IntelligenceConfig | None = None):
        self.store = store
        self.config = config or IntelligenceConfig()

    def run(self, events: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
        """Run the deterministic pipeline and persist an immutable result snapshot."""
        source_events = list(events if events is not None else self.store.load_processed_events())
        source_events.sort(key=lambda event: str(event.get("event_id", "")))
        graph = self.store.load_dependency_graph()
        graph_version = graph.graph_version if graph else None
        fingerprint_data = {"events": source_events, "configuration": self.config.to_dict(), "graph_version": graph_version}
        fingerprint = hashlib.sha256(_json(fingerprint_data).encode()).hexdigest()
        existing = self.store.get_run_by_fingerprint(fingerprint)
        if existing: return existing

        extracted = extract_features(source_events, self.config)
        feature_rows = extracted["features"]
        baseline_result = build_baselines(feature_rows, self.config)
        detected = detect_anomalies(feature_rows, baseline_result["baselines"], self.config)
        detector_findings = [*detected["statistical_findings"], *detected["machine_learning_findings"]]
        incidents = self.store.load_incidents()
        temporal = analyze_temporal(feature_rows, detector_findings, extracted["invalid_timestamp_events"], self.config, source_events, incidents)
        patterns = discover_patterns(source_events, incidents, self.config)
        cross_service = analyze_cross_service(detector_findings, graph, self.config)
        findings = self._common_findings(detector_findings, patterns, cross_service, fingerprint)
        for invalid in extracted["invalid_timestamp_events"]:
            created = _now()
            source = {"finding_type": "data_quality_limitation", "service_id": invalid["service_id"],
                "event_id": invalid["event_id"], "reason": invalid["reason"], "raw_timestamp": invalid.get("raw_timestamp")}
            finding_id = hashlib.sha256(_json({"run_fingerprint":fingerprint,"finding":source}).encode()).hexdigest()
            findings.append({"finding_id": finding_id, "finding_type": "data_quality_limitation",
                "affected_service_ids": [invalid["service_id"]], "window_start": None, "window_end": None,
                "observed_facts": {"reason": invalid["reason"], "raw_timestamp": invalid.get("raw_timestamp")},
                "expected_baseline": None, "detector": "event_time_validation", "score": None,
                "score_interpretation": "not applicable", "score_breakdown": score_description("event_time_validation", None),
                "evidence_references": [{"event_id": invalid["event_id"], "raw_timestamp": invalid.get("raw_timestamp"), "evidence_kind": "invalid_event_time"}],
                "related_incidents": [], "related_rca_reports": [], "related_blast_radius_analyses": [],
                "limitations": ["The event was excluded from event-time feature aggregation; processing time was not substituted."],
                "uncertainty_status": "data_quality_limitation", "model_version": self.config.version,
                "detector_version": "event-time-v1", "created_at": created})
        payload = {"features": feature_rows, "feature_summary": {k:v for k,v in extracted.items() if k != "features"},
            "baselines": baseline_result["baselines"], "baseline_method": baseline_result["method"],
            "detectors": {"statistical_findings": detected["statistical_findings"],
                "machine_learning_findings": detected["machine_learning_findings"], "comparison": detected["detector_comparison"]},
            "temporal_analysis": temporal, "patterns": patterns, "cross_service_analysis": cross_service,
            "findings": findings, "model_artifacts": detected["model_artifacts"],
            "summary": {"source_events": len(source_events), "feature_windows": len(feature_rows),
                "finding_count": len(findings), "insufficient_data_count": sum(x["uncertainty_status"] == "insufficient_data" for x in findings),
                "statistical_anomaly_count": sum(x["detector"] == "rolling_mean_standard_deviation" and x["finding_type"] == "statistical_anomaly" for x in findings),
                "ml_anomaly_count": sum(x["detector"] == "isolation_forest" and x["finding_type"] == "ml_anomaly" for x in findings),
                "pattern_count": len(patterns["exact_signature_patterns"])+len(patterns["approximate_signature_patterns"])+len(patterns["incident_structure_patterns"]),
                "cross_service_relationship_count": cross_service.get("relationship_count", 0)},
            "source_provenance": {"source_table": "processed_events" if events is None else "caller_supplied_processed_events",
                "event_ids": sorted(str(event.get("event_id", "")) for event in source_events),
                "dependency_graph_version": graph_version,
                "historical_context": "Stage 4 incident membership and Stage 5/6 references are linked where evidence event IDs overlap; source records are not modified."}}
        run_id = hashlib.sha256(("jarvis-intelligence:" + fingerprint).encode()).hexdigest()
        return self.store.save_run(run_id, fingerprint, self.config.to_dict(), graph_version, payload)

    def extract_features(self, events: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
        return extract_features(events if events is not None else self.store.load_processed_events(), self.config)

    def build_baselines(self, features: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
        rows = list(features if features is not None else self.extract_features()["features"])
        return build_baselines(rows, self.config)

    def detect(self, features: Sequence[Mapping[str, Any]] | None = None,
               baselines: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
        rows = list(features if features is not None else self.extract_features()["features"])
        prior = list(baselines if baselines is not None else self.build_baselines(rows)["baselines"])
        return detect_anomalies(rows, prior, self.config)

    def _common_findings(self, detector_findings: Sequence[Mapping[str, Any]], patterns: Mapping[str, Any],
                         cross_service: Mapping[str, Any], run_fingerprint: str) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = [dict(item) for item in detector_findings]
        for category in ("exact_signature_patterns", "approximate_signature_patterns", "incident_structure_patterns"):
            for pattern in patterns.get(category, []):
                candidates.append({"finding_type": "recurring_pattern", "service_id": None,
                    "service_ids": pattern.get("service_ids", []), "window_start": None, "window_end": None,
                    "observed_facts": {key:value for key,value in pattern.items() if key not in {"evidence_references", "limitations"}},
                    "expected_baseline": None, "detector": pattern["match_kind"],
                    "deviation_score": pattern.get("similarity_score"),
                    "score_interpretation": pattern.get("score_interpretation", pattern.get("interpretation", "recurrence support count; not a probability")),
                    "evidence_references": pattern.get("evidence_references", []),
                    "limitations": pattern.get("limitations", ["Recurrence does not establish causation."]),
                    "uncertainty_status": "pattern_candidate", "model_version": self.config.version})
        for relationship in cross_service.get("relationships", []):
            candidates.append({"finding_type": "cross_service_anomaly_relationship", "service_id": None,
                "service_ids": relationship["service_ids"], "window_start": min(x["window_start"] for x in relationship["anomaly_windows"]),
                "window_end": max(x["window_start"] for x in relationship["anomaly_windows"]),
                "observed_facts": {key:value for key,value in relationship.items() if key not in {"evidence_references", "confidence_limitations"}},
                "expected_baseline": None, "detector": "dependency_contextual_cross_service_analysis",
                "deviation_score": None, "score_interpretation": "no aggregate score; individual detector outputs are preserved",
                "evidence_references": relationship.get("evidence_references", []),
                "limitations": relationship.get("confidence_limitations", []),
                "uncertainty_status": "contextual_relationship_not_causation", "model_version": self.config.version})

        output = []; created = _now()
        for item in candidates:
            evidence = item.get("evidence_references", [])
            event_ids = sorted(_event_ids(evidence))
            links = self.store.related_context(event_ids)
            service_ids = item.get("service_ids") or ([item["service_id"]] if item.get("service_id") else [])
            canonical = {key:value for key,value in item.items() if key not in {"finding_id", "created_at"}}
            finding_id = hashlib.sha256(_json({"run_fingerprint":run_fingerprint,"finding":canonical}).encode()).hexdigest()
            output.append({"finding_id": finding_id, "finding_type": item["finding_type"],
                "affected_service_ids": sorted(set(str(s) for s in service_ids)),
                "window_start": item.get("window_start"), "window_end": item.get("window_end"),
                "observed_facts": item.get("observed_facts", {k:item.get(k) for k in ("feature", "observed_value", "deviation_score", "zero_variance_comparison") if k in item}),
                "expected_baseline": item.get("expected_baseline"), "detector": item.get("detector"),
                "score": item.get("deviation_score"), "score_interpretation": item.get("score_interpretation", "raw detector output; not a probability"),
                "score_breakdown": score_description(str(item.get("detector")), item.get("deviation_score"),
                    item.get("expected_baseline", {}).get("threshold") if isinstance(item.get("expected_baseline"), Mapping) else None),
                "evidence_references": evidence, "related_incidents": links["incidents"],
                "related_rca_reports": links["rca_reports"], "related_blast_radius_analyses": links["blast_radius_analyses"],
                "historical_context": {"rca": [{**context,"candidate_service_overlap":bool(set(context["candidate_service_ids"]) & set(str(s) for s in service_ids)),
                    "interpretation":"hypothesis overlap is comparison context, not confirmation"} for context in links.get("rca_context",[])],
                    "blast_radius": [{**context,"potential_impact_overlap":bool(set(context["potentially_impacted_service_ids"]) & set(str(s) for s in service_ids)),
                    "interpretation":"structural potential impact is not observed failure"} for context in links.get("blast_radius_context",[])]},
                "limitations": item.get("limitations", []), "uncertainty_status": item.get("uncertainty_status", "unknown"),
                "model_version": item.get("model_version", self.config.version),
                "detector_version": item.get("detector_version"), "created_at": created})
        # Distinct detector outputs remain distinct even if they point at identical evidence.
        return sorted(output, key=lambda item: (item["finding_type"], item["affected_service_ids"], str(item["window_start"]), item["detector"], item["finding_id"]))


def _event_ids(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        result = {str(value["event_id"])} if value.get("event_id") else set()
        for child in value.values(): result.update(_event_ids(child))
        return result
    if isinstance(value, (list, tuple)):
        result: set[str] = set()
        for child in value: result.update(_event_ids(child))
        return result
    return set()


def _json(value: Any) -> str: return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
def _now() -> str: return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
