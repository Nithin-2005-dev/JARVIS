"""Evidence-gated, deterministic Stage 8 recommendation generation."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .models import Recommendation, RecommendationConfig
from .ranking import order_recommendations, rank_breakdown
from .rules import DEFAULT_RULES, RecommendationRule, rules_as_dict
from .storage import SQLiteRecommendationStore


class RecommendationEngine:
    """Generate advisory records only; this engine never executes actions."""
    def __init__(self, store: SQLiteRecommendationStore, config: RecommendationConfig | None = None,
                 rules: Sequence[RecommendationRule] = DEFAULT_RULES):
        self.store=store; self.config=config or RecommendationConfig(); self.rules=tuple(rules)
        if len({r.rule_id for r in self.rules}) != len(self.rules): raise ValueError("rule IDs must be unique")

    def generate(self, *, incident_id: str | None = None, service_id: str | None = None,
                 context: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Generate for a stored incident/service or caller-provided immutable context."""
        ctx=dict(context) if context is not None else self.store.load_context(incident_id=incident_id,service_id=service_id)
        if not incident_id: incident_id=ctx.get("incident_id")
        fingerprint_data={"incident_id":incident_id,"service_id":service_id,"context":ctx,"configuration":self.config.to_dict(),"rules":rules_as_dict(self.rules)}
        fingerprint=hashlib.sha256(_json(fingerprint_data).encode()).hexdigest()
        old=self.store.get_run_by_fingerprint(fingerprint)
        if old: return old
        run_id=hashlib.sha256(("jarvis-recommendation-run:"+fingerprint).encode()).hexdigest()
        if ctx.get("context_status") != "ready":
            payload={"context_status":"insufficient_context","reason":ctx.get("reason","No usable source evidence was found."),
                     "run_id":run_id,"incident_id":incident_id,"service_id":service_id,"recommendations":[],
                     "source_context":_source_context(ctx,incident_id),
                     "summary":{"recommendation_count":0,"outcome":"insufficient_context"}}
            return self.store.save_run(run_id,fingerprint,self.config.to_dict(),rules_as_dict(self.rules),payload)
        findings=[dict(x) for x in ctx.get("intelligence_findings",[]) if isinstance(x,Mapping)]
        events=[dict(x) for x in ctx.get("events",[]) if isinstance(x,Mapping)]
        services=sorted({_service(e) for e in events if _service(e)!="unknown"})
        target_service=service_id or ctx.get("selected_service_id") or (services[0] if len(services)==1 else None)
        result: list[dict[str,Any]]=[]
        by_rule={r.rule_id:r for r in self.rules}

        # Specific symptom rules use direct Stage 3 observations.
        buckets={"db_pool_diagnostics":[],"auth_failure_diagnostics":[],"notification_failure_diagnostics":[],"service_error_diagnostics":[]}
        for event in events:
            original=_original(event); service=str(original.get("service",event.get("service_id","unknown")))
            event_type=str(original.get("event_type", "")).lower(); message=str(original.get("message", "")).lower()
            severity=str(original.get("severity","INFO")).upper(); categories=set(event.get("classification",{}).get("categories",[]))
            ev=_event_evidence(event)
            if "pool" in message and any(x in message for x in ("exhaust", "connection", "saturat")) or "pool" in event_type and any(x in event_type for x in ("exhaust", "saturat")) or event_type=="db_pool_exhausted":
                buckets["db_pool_diagnostics"].append(ev)
            elif service in {"authentication-service","auth-service"} and (severity in {"ERROR","CRITICAL","FATAL"} or "auth" in event_type and any(x in event_type for x in ("fail","error","denied"))):
                buckets["auth_failure_diagnostics"].append(ev)
            elif service in {"notification-service","notification"} and (severity in {"ERROR","CRITICAL","FATAL"} or any(x in event_type+" "+message for x in ("timeout","queue","retry","delivery fail","downstream_failure"))):
                buckets["notification_failure_diagnostics"].append(ev)
            elif severity in {"ERROR","CRITICAL","FATAL"} or any(c in categories for c in {"application_errors","database_failures","network_failures","authentication_failures","infrastructure_failures"}):
                buckets["service_error_diagnostics"].append(ev)
        for rule_id, evidence in buckets.items():
            if not evidence: continue
            services_for=sorted({str(e.get("service_id",target_service or "unknown")) for e in evidence})
            result.append(self._make(by_rule[rule_id],run_id,incident_id,services_for,evidence,[],
                confidence="moderate_evidence" if len(evidence)>1 else "weak_evidence",priority="high" if any(e.get("severity")=="CRITICAL" for e in evidence) else "medium",
                source="stage3",scenario="direct-events:"+rule_id,context=ctx))

        # Guarded mitigation: repeated event-time observations must expose pool
        # capacity and positive wait values. The runbook action remains human-run.
        saturated=[]
        for event in buckets["db_pool_diagnostics"]:
            metrics=event.get("metric_context",{})
            try:
                if float(metrics["active_connections"]) >= float(metrics["pool_size"]) > 0 and float(metrics["wait_ms"]) > 0:
                    saturated.append(event)
            except (KeyError,TypeError,ValueError):
                continue
        distinct={str(e.get("event_id")):e for e in saturated if e.get("event_id")}
        verified=set(str(x) for x in ctx.get("verified_prerequisites",[]))
        required={"current_saturation_confirmed","approved_runbook","payment_owner_approval"}
        if len(distinct)>=2 and required.issubset(verified) and "pool_admission_control" in by_rule:
            result.append(self._make(by_rule["pool_admission_control"],run_id,incident_id,["payment-service","database-service"],list(distinct.values()),[],
                confidence="moderate_evidence",priority="medium",source="stage3",scenario="pool-saturation:repeated-explicit-metrics",context=ctx,
                assumptions=["The cited event metadata reflects the incident window; confirm current saturation before action.","Admission control may delay or reject valid payments.","This is a proposal for an approved operator runbook, not an executed change."],
                title="Consider temporary payment admission control after current saturation is confirmed."))

        # Stage 5 candidates remain unconfirmed and are examined independently.
        rca=ctx.get("rca") or {}; report=rca.get("report",{}) if isinstance(rca,Mapping) else {}
        hypotheses=list(report.get("hypotheses",[])) if isinstance(report,Mapping) else []
        rca_status=str(report.get("assessment_status","")) if isinstance(report,Mapping) else ""
        if rca_status in {"competing_hypotheses","inconclusive"} or (report and report.get("leading_hypothesis")):
            if rca_status=="leading_hypothesis" and report.get("leading_hypothesis"):
                candidates=[report["leading_hypothesis"]]
            else:
                candidates=hypotheses
            if not candidates and report.get("leading_hypothesis"): candidates=[report["leading_hypothesis"]]
            # The rule can also produce a service-level missing-evidence path for no candidates.
            if not candidates and rca_status=="inconclusive" and events:
                ev=[_event_evidence(e) for e in events[:self.config.max_event_evidence]]
                ev.append({"stage":"stage5","kind":"inconclusive_assessment","investigation_id":rca.get("investigation_id"),"assessment_status":rca_status})
                result.append(self._make(by_rule["rca_candidate_diagnostics"],run_id,incident_id,services,ev,[],confidence="insufficient_evidence",priority="medium",source="stage5",scenario="inconclusive:no-candidate",context=ctx,
                    assumptions=["RCA reported insufficient evidence; no cause is selected."], title="Collect evidence to resolve inconclusive RCA"))
            for h in candidates:
                service=str(h.get("candidate_service") or "")
                candidate_event=str(h.get("candidate_event_id") or "")
                if not service and not candidate_event: continue
                supporting=list(h.get("supporting_evidence",[])); contradictory=list(h.get("contradictory_evidence",[])); missing=list(h.get("missing_evidence",[]))
                evidence=[{"stage":"stage5","kind":"rca_hypothesis","investigation_id":rca.get("investigation_id"),"candidate_event_id":candidate_event,
                           "candidate_service":service or None,"assessment_status":rca_status,"confirmed":False,
                           "hypothesis_score":h.get("heuristic_score"),"score_kind":h.get("score_kind"),
                           "supporting_evidence":supporting,"missing_evidence":missing}]
                if candidate_event:
                    source=next((e for e in events if str(e.get("event_id") or _original(e).get("event_id"))==candidate_event),None)
                    if source: evidence.insert(0,_event_evidence(source))
                contrad=[{"stage":"stage5","kind":"contradictory_rca_evidence","investigation_id":rca.get("investigation_id"),"candidate_event_id":candidate_event,"evidence":x} for x in contradictory]
                confidence="weak_evidence" if supporting else "insufficient_evidence"
                title="Validate competing incident hypothesis" if rca_status!="leading_hypothesis" else "Validate unconfirmed leading RCA hypothesis"
                result.append(self._make(by_rule["rca_candidate_diagnostics"],run_id,incident_id,[service] if service else services,evidence,contrad,
                    confidence=confidence,priority="medium",source="stage5",scenario="rca-candidate:"+(candidate_event or service),context=ctx,
                    assumptions=["RCA candidates are hypotheses, not confirmed causes.","Temporal order and correlation do not establish causation."],title=title,
                    related_rca_ids=[str(rca.get("investigation_id"))] if rca.get("investigation_id") else []))

        # Preserve Stage 7 detector disagreement as one distinct diagnostic, never pick a winner.
        detector_groups: dict[tuple[str,str],dict[str,list[Mapping[str,Any]]]]={}
        for finding in findings:
            if finding.get("finding_type") in {"statistical_anomaly","ml_anomaly","ml_baseline_observation"}:
                svc=(finding.get("affected_service_ids") or [finding.get("service_id") or "unknown"])[0]
                window=str(finding.get("window_start") or "unknown")
                detector_groups.setdefault((str(svc),window),{}).setdefault(str(finding.get("detector",finding.get("finding_type"))),[]).append(finding)
        for (svc,window),detectors in sorted(detector_groups.items()):
            statistical=any("statistical" in d.lower() or "rolling" in d.lower() for d in detectors)
            ml=any("forest" in d.lower() or d.lower().startswith("ml") for d in detectors)
            positive_stat=any(f.get("finding_type")=="statistical_anomaly" for d,fs in detectors.items() if "statistical" in d.lower() or "rolling" in d.lower() for f in fs)
            positive_ml=any(f.get("finding_type")=="ml_anomaly" for d,fs in detectors.items() if "forest" in d.lower() or d.lower().startswith("ml") for f in fs)
            if statistical and ml and positive_stat != positive_ml:
                all_findings=[f for fs in detectors.values() for f in fs]
                ev=[{"stage":"stage7","kind":"intelligence_finding","finding_id":f.get("finding_id"),"detector":f.get("detector"),"finding_type":f.get("finding_type"),"score":f.get("score"),"score_interpretation":f.get("score_interpretation"),"evidence_references":f.get("evidence_references",[]),"uncertainty_status":f.get("uncertainty_status")} for f in all_findings]
                result.append(self._make(by_rule["detector_disagreement_diagnostics"],run_id,incident_id,[svc],ev,[],confidence="weak_evidence",priority="low",source="stage7",scenario=f"detector-disagreement:{svc}:{window}",context=ctx,
                    assumptions=["Detector outputs are separate heuristic signals, not probabilities.","Disagreement does not establish that either detector is correct."], related_finding_ids=[str(f.get("finding_id")) for f in all_findings if f.get("finding_id")]))

        # A generic service diagnostic is available when direct events or findings exist.
        seen_services={s for item in result for s in item["affected_services"]}
        for finding in findings:
            if finding.get("finding_type") in {"statistical_anomaly","ml_anomaly","recurring_pattern","cross_service_anomaly_relationship","data_quality_limitation"}:
                for svc in finding.get("affected_service_ids",[]):
                    if svc in seen_services: continue
                    ev=[{"stage":"stage7","kind":"intelligence_finding","finding_id":finding.get("finding_id"),"finding_type":finding.get("finding_type"),"detector":finding.get("detector"),"score":finding.get("score"),"score_interpretation":finding.get("score_interpretation"),"evidence_references":finding.get("evidence_references",[]),"uncertainty_status":finding.get("uncertainty_status")}]
                    result.append(self._make(by_rule["service_error_diagnostics"],run_id,incident_id,[str(svc)],ev,[],confidence="weak_evidence",priority="low",source="stage7",scenario=f"stage7:{finding.get('finding_id')}:{svc}",context=ctx,
                        assumptions=["Anomaly or pattern output is a signal for investigation, not proof of an incident."],related_finding_ids=[str(finding.get("finding_id"))] if finding.get("finding_id") else []))
                    seen_services.add(svc)

        # Historical patterns support a targeted monitoring proposal, not a causal claim.
        for event in events:
            for pattern in event.get("patterns",[]) if isinstance(event.get("patterns",[]),list) else []:
                ids=list(pattern.get("evidence_event_ids",[])); ev=[_event_evidence(event)]
                if ids: ev.append({"stage":"stage3","kind":"repeated_pattern","event_ids":ids,"signature":pattern.get("signature"),"count":pattern.get("count"),"pattern_kind":pattern.get("kind")})
                result.append(self._make(by_rule["recurrence_monitoring"],run_id,incident_id,[_service(event)],ev,[],confidence="weak_evidence",priority="low",source="stage3",scenario="pattern:"+str(pattern.get("signature") or pattern.get("kind") or event.get("event_id")),context=ctx,
                    assumptions=["A repeated signature is recurrence evidence only; it does not identify a cause."],related_finding_ids=[]))
        for finding in findings:
            if finding.get("finding_type")=="recurring_pattern":
                ev=[{"stage":"stage7","kind":"intelligence_finding","finding_id":finding.get("finding_id"),"evidence_references":finding.get("evidence_references",[]),"observed_facts":finding.get("observed_facts",{})}]
                result.append(self._make(by_rule["recurrence_monitoring"],run_id,incident_id,list(finding.get("affected_service_ids",[])),ev,[],confidence="weak_evidence",priority="low",source="stage7",scenario="recurring:"+str(finding.get("finding_id")),context=ctx,
                    assumptions=["Pattern recurrence is not causal evidence."],related_finding_ids=[str(finding.get("finding_id"))] if finding.get("finding_id") else []))

        # Blast-radius membership is explicitly structural potential.
        for analysis in ctx.get("blast_radius_analyses",[]):
            impacted=sorted({str(x.get("service_id")) for x in analysis.get("impacted_services",[]) if x.get("service_id")})
            if not impacted: continue
            ev=[{"stage":"stage6","kind":"potential_blast_radius","analysis_id":analysis.get("analysis_id"),"root_service_id":analysis.get("root_service_id"),"graph_version":analysis.get("graph_version"),"potentially_impacted_services":impacted,"interpretation":"potential structural impact, not confirmed service failure"}]
            result.append(self._make(by_rule["potential_blast_radius_check"],run_id,incident_id,impacted,ev,[],confidence="weak_evidence",priority="medium",source="stage6",scenario="blast:"+str(analysis.get("analysis_id")),context=ctx,
                assumptions=["Dependency reachability describes potential structural impact only.","No affected-service failure is implied."],related_blast_radius_ids=[str(analysis.get("analysis_id"))] if analysis.get("analysis_id") else []))

        # The input can have context but no applicable rule: report that explicitly.
        unique: dict[tuple[str,str,tuple[str,...]],dict[str,Any]]={}
        for item in result:
            # Same rule, subject, and scenario is one recommendation even if
            # multiple source events independently triggered the same pattern.
            key=(item["rule_id"],item["scenario_key"],tuple(item["affected_services"]))
            previous=unique.get(key)
            if previous is None or len(item["supporting_evidence"])>len(previous["supporting_evidence"]): unique[key]=item
        ordered=order_recommendations(list(unique.values()))[:self.config.max_items]
        outcome="generated" if ordered else "no_applicable_rule"
        payload={"context_status":"ready","run_id":run_id,"incident_id":incident_id,"service_id":service_id,
                 "source_context":_source_context(ctx,incident_id),"recommendations":ordered,"summary":{"recommendation_count":len(ordered),"outcome":outcome,
                 "investigation_count":sum(x["recommendation_type"] in {"investigation","diagnostic"} for x in ordered),
                 "mitigation_or_recovery_count":sum(x["recommendation_type"] in {"mitigation","recovery"} for x in ordered),
                 "rule_ids":sorted({x["rule_id"] for x in ordered}),"causal_claims":0}}
        return self.store.save_run(run_id,fingerprint,self.config.to_dict(),rules_as_dict(self.rules),payload)

    def _make(self, rule: RecommendationRule, run_id: str, incident_id: str | None, services: Sequence[str],
              evidence: Sequence[Mapping[str,Any]], contradictory: Sequence[Mapping[str,Any]], *, confidence: str,
              priority: str, source: str, scenario: str, context: Mapping[str,Any], assumptions: Sequence[str]=(),
              title: str | None=None, related_finding_ids: Sequence[str]=(), related_rca_ids: Sequence[str]=(),
              related_blast_radius_ids: Sequence[str]=()) -> dict[str,Any]:
        evidence_rows=list(evidence)[:self.config.max_event_evidence]
        if len(evidence_rows)<self.config.min_evidence: raise ValueError(f"rule {rule.rule_id} missing required evidence")
        ids=sorted(set(str(x) for x in services if x and x!="unknown")); severity=_severity_score(context)
        evidence_score={"strong_evidence":1.0,"moderate_evidence":.68,"weak_evidence":.38,"insufficient_evidence":.1}[confidence]
        urgency=1.0 if priority=="critical" else .75 if priority=="high" else .5 if priority=="medium" else .25
        criticality=.8 if any(x in {"database-service","payment-service","api-gateway","authentication-service"} for x in ids) else .45
        potential=0.0
        if source=="stage6": potential=min(1.0,len(ids)/5)
        precondition=.35 if confidence=="insufficient_evidence" else .7 if confidence=="weak_evidence" else 1.0
        risk=str(rule.template.get("risk","low")); benefit=.65 if rule.template.get("type") in {"investigation","diagnostic"} else .45
        breakdown=rank_breakdown(severity=severity,evidence=evidence_score,urgency=urgency,criticality=criticality,potential_impact=potential,benefit=benefit,prerequisites=precondition,risk=risk,config=self.config)
        rec_key={"run_id":run_id,"rule_id":rule.rule_id,"scenario":scenario,"services":ids,"evidence":evidence_rows}
        recommendation_id=hashlib.sha256(("jarvis-recommendation:"+_json(rec_key)).encode()).hexdigest()
        created=datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
        contradiction_rows=list(contradictory)
        risk_effects={"low":["Investigation time; no direct service state change is proposed."],"medium":["Monitoring changes may add alert noise or operational overhead."],"high":["A high-risk action can cause service impact and must be reviewed with explicit safeguards."]}[risk]
        steps=tuple(str(x) for x in rule.verification_procedure)
        if rule.rule_id=="pool_admission_control":
            implementation=("Confirm the incident is active and current connection metrics still show active_connections >= pool_size with positive wait time.",
                "Obtain database and payment-service owner approval and use the documented admission-control runbook.",
                "Apply a temporary concurrency/admission cap only to the approved payment request path.")
            prerequisites=("Current metrics independently confirm continued pool saturation.","Approved runbook and change authorization are available.","Payment owner confirms acceptable rejection and delay behavior.")
            rollback=("Remove the temporary admission cap through the approved runbook once database waits and transaction latency remain within target.",
                "Restore the prior request admission behavior and verify payment success rate.")
        else:
            implementation=steps[:2] or ("Inspect the referenced evidence and relevant service telemetry.",)
            prerequisites=("Confirm service ownership and access to the referenced telemetry.","For any proposed operational change, obtain required approval and validate safety constraints.")
            rollback=("No rollback is required for read-only investigation.",) if risk=="low" else ("Revert the monitoring/configuration change using its approved prior version if it causes adverse effects.",)
        item=Recommendation(recommendation_id,incident_id,run_id,title or str(rule.template.get("title",rule.description)),
            rule.description+" This is advisory and does not establish root cause or execute a change.",str(rule.template["type"]),tuple(ids),priority,
            "immediate" if priority in {"critical","high"} else "soon" if priority=="medium" else "when_practical",confidence,
            tuple(evidence_rows),tuple(contradiction_rows),tuple(assumptions),_expected_benefit(str(rule.template["type"])),risk,
            tuple(risk_effects),tuple(prerequisites),tuple(implementation),steps,tuple(rollback),
            source,tuple(related_finding_ids),tuple(related_rca_ids),tuple(related_blast_radius_ids),"proposed",created,self.config.version,rule.rule_id,breakdown["score"],breakdown,scenario)
        return item.to_dict()


def _original(event: Mapping[str,Any]) -> Mapping[str,Any]: return event.get("original_event",event)
def _service(event: Mapping[str,Any]) -> str: return str(_original(event).get("service",event.get("service_id","unknown")))
def _event_evidence(event: Mapping[str,Any]) -> dict[str,Any]:
    original=_original(event)
    metadata=original.get("metadata",{}) if isinstance(original.get("metadata",{}),Mapping) else {}
    metric_context={key:metadata[key] for key in ("pool_size","active_connections","wait_ms","connection_wait_ms") if key in metadata}
    if "wait_ms" not in metric_context and "connection_wait_ms" in metric_context: metric_context["wait_ms"]=metric_context["connection_wait_ms"]
    return {"stage":"stage3","kind":"processed_event","event_id":str(event.get("event_id") or original.get("event_id","")),"service_id":_service(event),
            "event_type":original.get("event_type"),"severity":str(original.get("severity","INFO")).upper(),"message":original.get("message"),
            "event_timestamp":original.get("timestamp"),"classification":event.get("classification",{}).get("categories",[]),"pattern_refs":event.get("patterns",[]),"metric_context":metric_context}
def _severity_score(context: Mapping[str,Any]) -> float:
    severity=str((context.get("incident") or {}).get("severity","INFO")).upper()
    return {"CRITICAL":1.0,"FATAL":1.0,"ERROR":.8,"WARNING":.5,"WARN":.5,"INFO":.2}.get(severity,.2)
def _expected_benefit(kind: str) -> str:
    return {"investigation":"Reduce uncertainty by collecting evidence that distinguishes relevant failure hypotheses.",
            "diagnostic":"Compare conflicting signals and establish which observations are independently supported.",
            "mitigation":"If prerequisites are independently confirmed, may reduce database contention while limiting the action to an approved payment admission path; service impact remains possible.",
            "recovery":"Support verification of service recovery using the listed signals.",
            "monitoring":"Improve detection of the historically observed failure signature; alert quality must be reviewed.",
            "prevention":"Reduce recurrence risk for the observed pattern, subject to design review.",
            "capacity":"Make capacity decisions from observed utilization and service objectives.",
            "configuration":"Change configuration only after prerequisites and approvals are met.",
            "security":"Investigate the referenced security signals while preserving existing controls."}.get(kind,"Help responders investigate the specific evidence referenced by this recommendation.")
def _source_context(context: Mapping[str,Any],incident_id: str | None) -> dict[str,Any]:
    return {"stage4_incident_id":incident_id,
            "stage3_event_ids":sorted({str(e.get("event_id") or _original(e).get("event_id")) for e in context.get("events",[]) if e.get("event_id") or _original(e).get("event_id")}),
            "stage5_rca_investigation_id":(context.get("rca") or {}).get("investigation_id"),
            "stage6_blast_radius_analysis_ids":sorted(str(x.get("analysis_id")) for x in context.get("blast_radius_analyses",[]) if x.get("analysis_id")),
            "stage6_graph_versions":sorted({str(x.get("graph_version")) for x in context.get("blast_radius_analyses",[]) if x.get("graph_version")}),
            "stage7_intelligence_run_id":context.get("intelligence_run_id"),
            "stage7_finding_ids":sorted(str(x.get("finding_id")) for x in context.get("intelligence_findings",[]) if x.get("finding_id")),
            "externally_verified_prerequisites":sorted(set(str(x) for x in context.get("verified_prerequisites",[])))}
def _json(value:Any) -> str: return json.dumps(value,sort_keys=True,separators=(",",":"),default=str)
