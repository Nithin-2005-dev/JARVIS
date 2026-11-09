"""Deterministic candidate generation and explainable hypothesis assessment.

This engine ranks possible initiators. It does not infer causality from correlation,
and never marks a cause confirmed without an independent verification input.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol
from uuid import NAMESPACE_URL, uuid5

from ..correlation.candidate import event_time, resources, source_event
from .config import RCAConfig

LOG = logging.getLogger(__name__)


class RCAStore(Protocol):
    def incident_context(self, incident_id: str) -> dict[str, Any] | None: ...
    def save_investigation(self, investigation_id: str, incident_id: str, fingerprint: str, report: Mapping[str, Any]) -> None: ...
    def get_investigation(self, investigation_id: str) -> dict[str, Any] | None: ...


class RCAEngine:
    """Investigate one persisted incident and store a reproducible report."""
    def __init__(self, store: RCAStore, config: RCAConfig | None = None):
        self.store = store
        self.config = config or RCAConfig()

    def investigate(self, incident_id: str) -> dict[str, Any]:
        started = time.perf_counter()
        context = self.store.incident_context(incident_id)
        if context is None:
            raise KeyError(f"unknown incident: {incident_id}")
        events = context["events"]
        fingerprint = hashlib.sha256(_json({"incident_id": incident_id, "events": events,
            "correlations": context["correlations"], "patterns": [e.get("patterns", []) for e in events],
            "config": self.config.to_dict()}).encode()).hexdigest()
        investigation_id = str(uuid5(NAMESPACE_URL, "jarvis-rca:" + fingerprint))
        existing = self.store.get_investigation(investigation_id)
        if existing is not None:
            return existing
        report = self._analyze(incident_id, context, investigation_id, fingerprint)
        report["processing_duration_seconds"] = round(time.perf_counter() - started, 6)
        self.store.save_investigation(investigation_id, incident_id, fingerprint, report)
        LOG.info("rca_investigation_completed", extra={"investigation_id": investigation_id,
                 "incident_id": incident_id, "status": report["assessment_status"], "candidate_count": len(report["hypotheses"])})
        return report

    def _analyze(self, incident_id: str, context: Mapping[str, Any], investigation_id: str, fingerprint: str) -> dict[str, Any]:
        events = list(context["events"])
        rows: list[tuple[datetime, Mapping[str, Any], Mapping[str, Any]]] = []
        untimed: list[tuple[None, Mapping[str, Any], Mapping[str, Any]]] = []
        for processed in events:
            original = source_event(processed)
            try:
                rows.append((event_time(processed), processed, original))
            except (ValueError, TypeError):
                # Keep malformed-time records visible; never invent their ordering.
                untimed.append((None, processed, original))
        rows.sort(key=lambda x: (x[0], str(x[2].get("event_id", ""))))
        all_rows = rows + untimed
        abnormal = [row for row in all_rows if str(row[2].get("severity", "INFO")).upper() in self.config.abnormal_severities
                    or any(category != "service_lifecycle_events" for category in row[1].get("classification", {}).get("categories", []))]
        candidates: dict[str, tuple[Mapping[str, Any], Mapping[str, Any], datetime | None]] = {}
        for when, processed, original in abnormal:
            eid = str(original.get("event_id", processed.get("event_id", "")))
            if eid:
                candidates[eid] = (processed, original, when)

        if not candidates:
            return self._report(incident_id, investigation_id, fingerprint, all_rows, [], context,
                                "inconclusive", ["No abnormal event was observed in the incident payload."], [])

        incident_event_ids = {str(source_event(p).get("event_id", p.get("event_id", ""))) for p in events}
        correlation_records = [r for r in context.get("correlations", [])
                               if r.get("source_event_id") in incident_event_ids and r.get("target_event_id") in incident_event_ids]
        first_time = min((r[0] for r in abnormal if r[0] is not None), default=None)
        hypotheses = []
        for event_id, (processed, original, when) in candidates.items():
            support: list[dict[str, Any]] = []
            contradictions: list[dict[str, Any]] = []
            missing: list[dict[str, Any]] = []
            categories = set(processed.get("classification", {}).get("categories", []))
            etype = str(original.get("event_type", "")).lower()
            message = str(original.get("message", "")).lower()
            meta = original.get("metadata", {}) if isinstance(original.get("metadata", {}), dict) else {}
            resource_keys = ("resource_id", "database", "database_id", "db_instance", "server_id", "host", "hostname", "api", "endpoint", "network_component", "resource")
            resource_set = resources(processed, resource_keys)
            shared_resources = sorted(resource_set & set().union(*(resources(other, resource_keys) for other in events if str(source_event(other).get("event_id", "")) != event_id))) if resource_set else []
            service = str(original.get("service", "unknown"))
            is_resource_failure = any(k in etype or k in message for k in ("pool", "exhaust", "connection", "resource", "saturat", "capacity"))
            is_db = "database" in categories or "database" in etype or "database" in message or service == "database-service"
            is_network = "network" in categories or "network" in etype or "network" in message or "downstream" in etype
            is_infra = "infrastructure_failures" in categories or "infrastructure" in etype
            if is_resource_failure:
                support.append(self._evidence("resource_exhaustion", "supporting", "Observed event explicitly indicates resource/pool exhaustion or saturation.", [event_id], 1.0, {"event_type": etype, "message": original.get("message")}))
            if is_db:
                support.append(self._evidence("initiating_failure", "supporting", "Observed database-related failure signal.", [event_id], .85, {"categories": sorted(categories), "service": service}))
            if is_network:
                support.append(self._evidence("infrastructure_failure", "supporting", "Observed network or downstream failure signal.", [event_id], .75, {"categories": sorted(categories), "event_type": etype}))
            if is_infra:
                support.append(self._evidence("infrastructure_failure", "supporting", "Event is classified as an infrastructure failure.", [event_id], .75, {"categories": sorted(categories)}))
            if shared_resources:
                support.append(self._evidence("resource_context", "supporting", "Candidate shares explicit resource identifiers with other incident events; sharing does not show the resource failed or caused symptoms.", [event_id], .65, {"shared_resources": shared_resources}, evidence_type="correlated_relationship"))
            if not (is_resource_failure or is_db or is_network or is_infra):
                support.append(self._evidence("initiating_failure", "supporting", "Abnormal application event is a candidate, but its message does not identify a specific failure domain.", [event_id], .3, {"categories": sorted(categories), "severity": original.get("severity")}))

            if first_time and when == first_time:
                later = [{"event_id": str(r[2].get("event_id")), "event_time": _iso(r[0]), "difference_seconds": round((r[0] - when).total_seconds(), 3)} for r in abnormal if r[0] is not None and r[0] > when]
                support.append(self._evidence("temporal_precedence", "supporting", "This is the earliest observed abnormal event; subsequent observed failures are temporally consistent with sequence only, not causality.", [event_id, *[x["event_id"] for x in later]], .35, {"event_time": _iso(when), "subsequent_abnormal_observations": later}))
            elif first_time and when is not None:
                earlier = next((r for r in abnormal if r[0] == first_time), None)
                if earlier:
                    contradictions.append(self._evidence("temporal_precedence", "contradictory", "Another abnormal event was observed earlier; this may be a downstream symptom, though incomplete telemetry can hide earlier causes.", [str(earlier[2].get("event_id")), event_id], .4, {"earlier_event_time": _iso(first_time)}))

            # Configured topology is an inferred plausibility cue, never observed causation.
            descendants = set()
            for upstream, downstreams in self.config.service_dependencies.items():
                if service == upstream:
                    descendants.update(downstreams)
            affected_services = {str(r[2].get("service", "unknown")) for r in abnormal if r[2].get("event_id") != event_id}
            dependent_affected = sorted(descendants & affected_services)
            if dependent_affected:
                support.append(self._evidence("dependency_path", "supporting", "Configured service dependency suggests this service could affect observed downstream services; topology is inferred/configured and may be stale.", [event_id], .55, {"configured_downstream_services": dependent_affected, "candidate_service": service}, evidence_type="inferred_dependency"))
            elif affected_services and service in self.config.service_dependencies and not (descendants & affected_services):
                contradictions.append(self._evidence("dependency_path", "contradictory", "Configured dependency map contains no path from this candidate to the other failing services; the map may be incomplete or incorrect.", [event_id], .25, {"affected_services": sorted(affected_services)}, evidence_type="inferred_dependency"))

            for corr in correlation_records:
                if event_id not in {corr.get("source_event_id"), corr.get("target_event_id")}: continue
                ev = corr.get("evidence", {})
                strategy = ev.get("strategy", corr.get("strategy", "unknown"))
                support.append(self._evidence("correlation", "supporting", "Stage 4 recorded an association; this supports relatedness only and does not establish causal direction.", [corr.get("source_event_id"), corr.get("target_event_id")], min(1.0, float(corr.get("confidence_score", 0))), {"strategy": strategy, "description": ev.get("description"), "attributes": ev.get("supporting_attributes", {})}, evidence_type="correlated_relationship"))
            for pattern in processed.get("patterns", []):
                support.append(self._evidence("pattern", "supporting", "Stage 3 detected a repeated/frequency pattern; recurrence does not establish an initiating cause.", [event_id, *pattern.get("evidence_event_ids", [])], .5, {"kind": pattern.get("kind"), "signature": pattern.get("signature"), "count": pattern.get("count")}, evidence_type="correlated_relationship"))
            if not resource_set:
                missing.append(self._evidence("resource_evidence", "missing", "No normalized shared-resource identifier was available for this candidate.", [event_id], 0.0, {}))
            if not original.get("trace_id"):
                missing.append(self._evidence("trace_evidence", "missing", "No trace ID was available; trace ordering and span relationships cannot be assessed.", [event_id], 0.0, {}))
            if when is None:
                missing.append(self._evidence("event_time", "missing", "This event has no valid event timestamp; its temporal order cannot be assessed.", [event_id], 0.0, {}))
            temporal = processed.get("temporal", {})
            if temporal.get("late_arrival") or temporal.get("out_of_order"):
                missing.append(self._evidence("temporal_observation", "missing", "Stage 3 marked this record late or out of order; observed arrival ordering may omit earlier events.", [event_id], 0.0, {"late_arrival": bool(temporal.get("late_arrival")), "out_of_order": bool(temporal.get("out_of_order")), "event_timestamp": temporal.get("event_timestamp"), "processing_timestamp": temporal.get("processing_timestamp")}, evidence_type="correlated_relationship"))
            missing.append(self._evidence("metrics", "missing", "No metrics source is attached to this incident; saturation and health trends cannot be independently verified.", [event_id], 0.0, {}))
            missing.append(self._evidence("independent_verification", "missing", "No independent verification signal is available; this candidate cannot be marked confirmed.", [event_id], 0.0, {}))

            score, breakdown = self._score(support, contradictions)
            families = {e["family"] for e in support}
            hypotheses.append({"assessment_type": "root_cause_hypothesis", "candidate_event_id": event_id, "candidate_service": service,
                "candidate_event_type": original.get("event_type"), "candidate_message": original.get("message"),
                "event_time": _iso(when) if when else None, "heuristic_score": score, "score_kind": "heuristic_evidence_score_not_probability",
                "score_breakdown": breakdown, "supporting_evidence": support, "contradictory_evidence": contradictions,
                "missing_evidence": missing, "supporting_evidence_families": sorted(families),
                "confirmed": False, "confidence_limitations": ["Heuristic weights are not statistically calibrated.", "Temporal precedence and Stage 4 correlation do not prove causation.", "Missing telemetry is unknown, not negative evidence."]})
        hypotheses.sort(key=lambda h: (-h["heuristic_score"], h["event_time"] or "", h["candidate_event_id"]))
        for i, hypothesis in enumerate(hypotheses, 1): hypothesis["rank"] = i
        top = hypotheses[0]
        plausible = [h for h in hypotheses if h["heuristic_score"] >= self.config.minimum_heuristic_score and len(h["supporting_evidence_families"]) >= self.config.minimum_supporting_families]
        close = len(plausible) > 1 and plausible[0]["heuristic_score"] - plausible[1]["heuristic_score"] <= self.config.competing_margin
        status = "inconclusive" if not plausible else ("competing_hypotheses" if close else "leading_hypothesis")
        gaps = sorted({e["description"] for h in hypotheses for e in h["missing_evidence"]})
        return self._report(incident_id, investigation_id, fingerprint, all_rows, hypotheses, context, status, gaps,
                            ["Inspect database pool and connection metrics around the event time.", "Verify the service dependency map against deployment configuration.", "Collect trace spans and resource health signals for the incident window."])

    def _score(self, supporting: list[dict[str, Any]], contradictory: list[dict[str, Any]]) -> tuple[float, dict[str, Any]]:
        positives = [float(e["weight"]) * float(e["reliability"]) * float(e["strength"]) for e in supporting]
        negatives = [float(e["weight"]) * float(e["reliability"]) * float(e["strength"]) * self.config.contradictory_weight for e in contradictory]
        denom = sum(float(e["weight"]) * float(e["reliability"]) for e in supporting + contradictory)
        score = max(0.0, min(1.0, (sum(positives) - sum(negatives)) / denom if denom else 0.0))
        return round(score, 4), {"support_contributions": [round(x, 4) for x in positives], "contradiction_penalties": [round(x, 4) for x in negatives], "normalization_denominator": round(denom, 4), "formula": "clamp((sum(weight*reliability*strength support) - contradictory_weight*sum(weight*reliability*strength contradiction)) / sum(weight*reliability for observed support and contradiction), 0, 1)"}

    def _evidence(self, family: str, polarity: str, description: str, event_ids: list[Any], strength: float, details: Mapping[str, Any], evidence_type: str = "observed_fact") -> dict[str, Any]:
        reliability_key = "event_fact" if evidence_type == "observed_fact" else ("configured_dependency" if evidence_type == "inferred_dependency" else "stage4_correlation" if evidence_type == "correlated_relationship" else "event_fact")
        return {"family": family, "polarity": polarity, "evidence_type": evidence_type, "description": description,
                "event_ids": sorted({str(x) for x in event_ids if x}), "strength": strength,
                "weight": float(self.config.evidence_weights.get(family, .2)),
                "reliability": float(self.config.evidence_reliability.get(reliability_key, .5)), "details": dict(details)}

    def _report(self, incident_id: str, investigation_id: str, fingerprint: str, rows: list[Any], hypotheses: list[dict[str, Any]], context: Mapping[str, Any], status: str, gaps: list[str], recommendations: list[str]) -> dict[str, Any]:
        incident = context.get("incident") or {}
        rows = sorted(rows, key=lambda x: (x[0] is None, _iso(x[0]) if x[0] else "", str(x[2].get("event_id", ""))))
        timeline = [{"event_id": str(original.get("event_id", processed.get("event_id", ""))), "event_time": _iso(when) if when else None, "processing_time": processed.get("processing_timestamp") or processed.get("temporal", {}).get("processing_timestamp"), "late_arrival": bool(processed.get("temporal", {}).get("late_arrival")), "out_of_order": bool(processed.get("temporal", {}).get("out_of_order")), "service": original.get("service", "unknown"), "event_type": original.get("event_type"), "severity": original.get("severity"), "message": original.get("message"), "observation_type": "observed_fact"} for when, processed, original in rows]
        times = [r[0] for r in rows if r[0] is not None]
        services = sorted({str(r[2].get("service", "unknown")) for r in rows})
        # A close race remains a ranked set, not a declared leader.
        leader = hypotheses[0] if hypotheses and status == "leading_hypothesis" else None
        alternatives = hypotheses[1:] if leader else hypotheses
        summary = str(incident.get("summary") or f"Incident {incident_id} with {len(rows)} timestamped observations across {len(services)} services.")
        return {"investigation_id": investigation_id, "incident_id": incident_id, "fingerprint": fingerprint,
            "assessment_status": status, "incident_summary": summary,
            "investigation_time_range": {"start": _iso(min(times)) if times else None, "end": _iso(max(times)) if times else None},
            "investigated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "leading_hypothesis": leader, "alternative_hypotheses": alternatives, "hypotheses": hypotheses,
            "confirmed_causes": [], "affected_services": services, "event_timeline": timeline,
            "observed_facts": [{"event_id": x["event_id"], "event_time": x["event_time"], "processing_time": x["processing_time"], "service": x["service"], "event_type": x["event_type"], "severity": x["severity"], "message": x["message"]} for x in timeline],
            "correlated_relationships": context.get("correlations", []), "evidence_gaps": gaps,
            "recommended_further_investigations": recommendations,
            "confidence_assessment": {"kind": "heuristic_not_probability", "status": status,
                "explanation": "Assessment ranks evidence consistency; it does not establish causation. No independent verifier is configured."},
            "config": self.config.to_dict()}


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
