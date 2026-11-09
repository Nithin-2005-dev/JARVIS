"""Deterministic synthetic recommendation checks with explicit denominators."""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from .engine import RecommendationEngine
from .storage import SQLiteRecommendationStore


def scenarios() -> list[dict[str,Any]]:
    """Return fixed fixtures covering all requested evidence/uncertainty families."""
    cases=[]
    def add(name: str, context: dict[str,Any], expected: str, expected_type: str | None=None, expected_absent: str | None=None):
        cases.append({"scenario":name,"context":context,"expected_rule":expected,"expected_type":expected_type,"expected_absent_rule":expected_absent})
    def event(eid: str, service: str, etype: str, message: str, severity: str="ERROR", metadata: dict[str,Any] | None=None):
        return {"event_id":eid,"original_event":{"event_id":eid,"service":service,"event_type":etype,"message":message,"severity":severity,"timestamp":"2025-01-01T00:00:00Z","metadata":metadata or {}},"classification":{"categories":[]},"patterns":[]}
    base={"context_status":"ready","events":[],"intelligence_findings":[],"blast_radius_analyses":[],"incident":{"severity":"ERROR"},"incident_id":"synthetic-incident"}
    add("database_pool_exhaustion",base|{"events":[event("e-db","database-service","db_pool_exhausted","Database connection pool exhausted","CRITICAL")]},"db_pool_diagnostics","investigation")
    add("authentication_degradation",base|{"events":[event("e-auth","authentication-service","auth_failed","Token validation failed")]},"auth_failure_diagnostics","investigation")
    add("notification_queue_failure",base|{"events":[event("e-notify","notification-service","downstream_failure","Notification queue retry timeout")]},"notification_failure_diagnostics","investigation")
    add("payment_degradation",base|{"events":[event("e-pay","payment-service","request_failed","Payment request failed")]},"service_error_diagnostics","investigation")
    competing={"investigation_id":"rca-2","report":{"assessment_status":"competing_hypotheses","hypotheses":[{"candidate_event_id":"e-db","candidate_service":"database-service","heuristic_score":.6,"supporting_evidence":[{"description":"database error observed"}],"contradictory_evidence":[],"missing_evidence":[]},{"candidate_event_id":"e-net","candidate_service":"payment-service","heuristic_score":.59,"supporting_evidence":[{"description":"network error observed"}],"contradictory_evidence":[],"missing_evidence":[]}]}}
    add("competing_rca",base|{"events":[event("e-db","database-service","db_pool_exhausted","pool exhausted"),event("e-net","payment-service","request_failed","upstream request failed")],"rca":competing},"rca_candidate_diagnostics","investigation")
    add("inconclusive_rca",base|{"events":[event("e-unknown","payment-service","request_failed","request failed")],"rca":{"investigation_id":"rca-i","report":{"assessment_status":"inconclusive","hypotheses":[]}}},"rca_candidate_diagnostics","investigation")
    dis={"finding_id":"f-stat","finding_type":"statistical_anomaly","affected_service_ids":["payment-service"],"window_start":"2025-01-01T00:00:00Z","detector":"rolling_mean_standard_deviation","score":4,"score_interpretation":"heuristic deviation","evidence_references":[{"event_id":"e-pay"}]}
    disagree={"finding_id":"f-ml","finding_type":"ml_baseline_observation","affected_service_ids":["payment-service"],"window_start":"2025-01-01T00:00:00Z","detector":"isolation_forest","score":.4,"score_interpretation":"detector raw score","evidence_references":[{"event_id":"e-pay"}]}
    add("detector_disagreement",base|{"events":[event("e-pay","payment-service","request_succeeded","Payment ok","INFO")],"intelligence_findings":[dis,disagree]},"detector_disagreement_diagnostics","diagnostic")
    add("potential_blast_radius",base|{"events":[event("e-db","database-service","db_pool_exhausted","pool exhausted")],"blast_radius_analyses":[{"analysis_id":"br-1","root_service_id":"database-service","graph_version":"g1","impacted_services":[{"service_id":"payment-service"},{"service_id":"api-gateway"}]}]},"potential_blast_radius_check","investigation")
    add("missing_evidence",{"context_status":"insufficient_context","reason":"no processed events or findings"},"",None)
    recurring={"finding_id":"f-rec","finding_type":"recurring_pattern","affected_service_ids":["database-service"],"evidence_references":[{"event_id":"e-db"}],"observed_facts":{"support":3}}
    add("service_without_incident_recurring_anomaly",base|{"incident_id":None,"events":[],"intelligence_findings":[recurring]},"recurrence_monitoring","monitoring")
    add("duplicate_generation",base|{"events":[event("e-db","database-service","db_pool_exhausted","pool exhausted")]},"db_pool_diagnostics","investigation")
    saturation={"pool_size":10,"active_connections":10,"wait_ms":850}
    pool_events=[event("e-pool-1","database-service","db_pool_exhausted","pool exhausted","CRITICAL",saturation),event("e-pool-2","database-service","db_pool_exhausted","pool exhausted","CRITICAL",saturation)]
    add("high_risk_prerequisite_gate",base|{"events":pool_events,"verified_prerequisites":["current_saturation_confirmed","approved_runbook","payment_owner_approval"]},"pool_admission_control","mitigation")
    add("high_risk_missing_prerequisites",base|{"events":pool_events},"db_pool_diagnostics","investigation","pool_admission_control")
    contrad=competing|{"report":{"assessment_status":"inconclusive","hypotheses":[{"candidate_event_id":"e-db","candidate_service":"database-service","heuristic_score":.5,"supporting_evidence":[{"description":"pool errors"}],"contradictory_evidence":[{"description":"metric was normal"}],"missing_evidence":[]}]}}
    add("contradictory_evidence",base|{"events":[event("e-db","database-service","db_pool_exhausted","pool exhausted")],"rca":contrad},"db_pool_diagnostics","investigation")
    add("no_applicable_rule",base|{"events":[event("e-ok","payment-service","request_succeeded","ok","INFO")]},"",None)
    return cases


def evaluate() -> dict[str,Any]:
    """Run fixtures in a temporary SQLite store; metrics are synthetic conformance only."""
    rows=[]; applicable=traceable=uncertainty=duplicate=verification=priority_ok=unsupported=mitigations=bad_mitigations=0; lifecycle_ok=feedback_ok=priority_order_ok=risk_classification_ok=0; correct=0
    with tempfile.TemporaryDirectory(prefix="jarvis-stage8-") as tmp:
        with SQLiteRecommendationStore(Path(tmp)/"recommendations.sqlite") as store:
            engine=RecommendationEngine(store)
            for case in scenarios():
                ctx=case["context"]
                result=engine.generate(incident_id=ctx.get("incident_id"),service_id=ctx.get("service_id"),context=ctx)
                if case["scenario"]=="duplicate_generation":
                    repeated=engine.generate(incident_id=ctx.get("incident_id"),service_id=ctx.get("service_id"),context=ctx)
                    duplicate+=int(repeated["run_id"]==result["run_id"] and repeated["recommendations"]==result["recommendations"])
                if case["scenario"]=="high_risk_prerequisite_gate":
                    types=[r["recommendation_type"] for r in result.get("recommendations",[])]
                    priority_order_ok=int("investigation" in types and "mitigation" in types and types.index("investigation")<types.index("mitigation"))
                    mitigation=next((r for r in result.get("recommendations",[]) if r["rule_id"]=="pool_admission_control"),None)
                    risk_classification_ok=int(mitigation is not None and mitigation["risk_level"]=="high" and len(mitigation["prerequisites"])>=3)
                matching=[r for r in result.get("recommendations",[]) if r["rule_id"]==case["expected_rule"]] if case["expected_rule"] else []
                ok=bool(matching) if case["expected_rule"] else result.get("summary",{}).get("outcome") in {"insufficient_context","no_applicable_rule"}
                if case.get("expected_absent_rule"):
                    ok=ok and not any(r["rule_id"]==case["expected_absent_rule"] for r in result.get("recommendations",[]))
                correct+=int(ok)
                if matching:
                    applicable+=1
                    traceable+=int(all(bool(r["supporting_evidence"]) for r in matching))
                    verification+=int(all(bool(r["verification_steps"]) for r in matching))
                    unsupported+=int(any(not r["supporting_evidence"] or not r["rule_id"] for r in matching))
                    high_risk=[r for r in matching if r["risk_level"]=="high"]
                    priority_ok+=int(all(bool(r["prerequisites"]) and r["recommendation_type"] in {"mitigation","recovery","configuration"} for r in high_risk))
                for rec in result.get("recommendations",[]):
                    if rec["recommendation_type"] in {"mitigation","recovery"}:
                        mitigations+=1
                        refs=rec["supporting_evidence"]
                        supported=rec["risk_level"]=="high" and bool(rec["prerequisites"]) and len([x for x in refs if x.get("kind")=="processed_event" and x.get("metric_context",{}).get("pool_size") and x.get("metric_context",{}).get("active_connections") and x.get("metric_context",{}).get("wait_ms")])>=2
                        bad_mitigations+=int(not supported)
                if case["scenario"] in {"competing_rca","inconclusive_rca","detector_disagreement","potential_blast_radius"}:
                    if case["scenario"]=="competing_rca": uncertainty+=int(len([x for x in matching])>=2 and all(not any(e.get("confirmed") for e in x["supporting_evidence"]) for x in matching))
                    else: uncertainty+=int(bool(matching) and all(x["confidence_label"] in {"weak_evidence","insufficient_evidence"} for x in matching))
                rows.append({"scenario":case["scenario"],"expected_rule":case["expected_rule"],"matched":ok,"recommendation_ids":[r["recommendation_id"] for r in result.get("recommendations",[])],"outcome":result.get("summary",{}).get("outcome")})
            # Lifecycle and feedback are exercised against an actual persisted record.
            first=store.list_recommendations(limit=1)
            if first:
                rid=first[0]["recommendation_id"]
                store.update_status(rid,"acknowledged")
                store.update_status(rid,"in_progress")
                store.update_status(rid,"completed",notes="synthetic evaluation completion")
                lifecycle_ok=int(store.get_recommendation(rid)["status"]=="completed" and len(store.history(rid))==4)
                feedback=store.record_feedback({"recommendation_id":rid,"outcome_status":"inconclusive","observed_evidence":[]})
                feedback_ok=int(len(store.feedback_history(rid))==1 and feedback["recommendation_id"]==rid)
    total=len(rows)
    return {"evaluation_type":"synthetic_rule_conformance_not_production_quality","scenario_count":total,"scenario_match_rate":{"numerator":correct,"denominator":total,"value":round(correct/total,4)},
            "evidence_traceability":{"numerator":traceable,"denominator":applicable,"value":round(traceable/applicable,4) if applicable else None},
            "verification_completeness":{"numerator":verification,"denominator":applicable,"value":round(verification/applicable,4) if applicable else None},
            "priority_and_risk_gate_correctness":{"numerator":priority_ok,"denominator":applicable,"value":round(priority_ok/applicable,4) if applicable else None},
            "investigation_before_mitigation_order":{"numerator":priority_order_ok,"denominator":1,"value":float(priority_order_ok)},
            "high_risk_classification_and_prerequisites":{"numerator":risk_classification_ok,"denominator":1,"value":float(risk_classification_ok)},
            "lifecycle_transition_correctness":{"numerator":lifecycle_ok,"denominator":1,"value":float(lifecycle_ok)},
            "feedback_persistence":{"numerator":feedback_ok,"denominator":1,"value":float(feedback_ok)},
            "uncertainty_preservation":{"numerator":uncertainty,"denominator":4,"value":round(uncertainty/4,4)},
            "duplicate_idempotency":{"numerator":duplicate,"denominator":1,"value":float(duplicate)},
            "duplicate_rate_on_repeated_generation":{"numerator":1-duplicate,"denominator":1,"value":float(1-duplicate)},
            "unsupported_recommendations":{"numerator":unsupported,"denominator":applicable,"value":round(unsupported/applicable,4) if applicable else None},
            "inappropriate_mitigation_suggestions":{"numerator":bad_mitigations,"denominator":mitigations,"value":round(bad_mitigations/mitigations,4) if mitigations else None},"scenarios":rows,
            "limitations":["Fixtures exercise deterministic rule conformance, not responder utility or production incident quality.","Synthetic denominator is small and authored alongside the rules.","No calibrated confidence or success probability is measured."]}


def write_evaluation(path: str | Path) -> dict[str,Any]:
    output=evaluate(); path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(output,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return output


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--output",default="data/evaluation/stage8_recommendation_metrics.json"); args=parser.parse_args()
    print(json.dumps(write_evaluation(args.output),indent=2,sort_keys=True))
