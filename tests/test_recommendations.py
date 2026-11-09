"""Stage 8 recommendation engine and persistence tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import json

from payflow_simulator.recommendations import Recommendation, RecommendationConfig, RecommendationEngine, SQLiteRecommendationStore
from payflow_simulator.recommendations.evaluation import evaluate, scenarios


class RecommendationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store=SQLiteRecommendationStore(Path(self.tmp.name)/"events.sqlite"); self.addCleanup(self.store.close)
        self.engine=RecommendationEngine(self.store)

    def context(self, name): return next(x["context"] for x in scenarios() if x["scenario"]==name)

    def test_database_exhaustion_yields_evidence_linked_investigation_not_remediation(self):
        result=self.engine.generate(context=self.context("database_pool_exhaustion"))
        item=next(x for x in result["recommendations"] if x["rule_id"]=="db_pool_diagnostics")
        self.assertEqual(item["recommendation_type"],"investigation")
        self.assertEqual(item["confidence_label"],"weak_evidence")
        self.assertEqual(item["supporting_evidence"][0]["event_id"],"e-db")
        self.assertTrue(item["verification_steps"])
        self.assertFalse(any(x["recommendation_type"] in {"mitigation","recovery"} for x in result["recommendations"]))

    def test_high_risk_mitigation_requires_repeated_explicit_metrics_and_ranks_after_investigation(self):
        result=self.engine.generate(context=self.context("high_risk_prerequisite_gate"))
        investigation=next(i for i,x in enumerate(result["recommendations"]) if x["recommendation_type"]=="investigation")
        mitigation=next(i for i,x in enumerate(result["recommendations"]) if x["rule_id"]=="pool_admission_control")
        item=result["recommendations"][mitigation]
        self.assertLess(investigation,mitigation)
        self.assertEqual(item["risk_level"],"high")
        self.assertGreaterEqual(len(item["prerequisites"]),3)
        self.assertTrue(all(x.get("metric_context",{}).get("active_connections")==x.get("metric_context",{}).get("pool_size") for x in item["supporting_evidence"]))
        no_prereqs=self.context("high_risk_missing_prerequisites")
        blocked=self.engine.generate(context=no_prereqs)
        self.assertFalse(any(x["rule_id"]=="pool_admission_control" for x in blocked["recommendations"]))

    def test_competing_rca_candidates_remain_separate(self):
        result=self.engine.generate(context=self.context("competing_rca"))
        candidates=[x for x in result["recommendations"] if x["rule_id"]=="rca_candidate_diagnostics"]
        self.assertEqual({x["affected_services"][0] for x in candidates},{"database-service","payment-service"})
        self.assertTrue(all("not confirmed" in " ".join(x["assumptions"]) for x in candidates))

    def test_single_leading_rca_hypothesis_is_targeted_but_unconfirmed(self):
        ctx=self.context("competing_rca")
        hypotheses=ctx["rca"]["report"]["hypotheses"]
        ctx["rca"]["report"]={"assessment_status":"leading_hypothesis","hypotheses":hypotheses,
            "leading_hypothesis":hypotheses[0]}
        result=self.engine.generate(context=ctx)
        candidates=[x for x in result["recommendations"] if x["rule_id"]=="rca_candidate_diagnostics"]
        self.assertEqual(len(candidates),1)
        self.assertIn("unconfirmed",candidates[0]["title"].lower())

    def test_inconclusive_and_missing_context_are_explicit(self):
        inconclusive=self.engine.generate(context=self.context("inconclusive_rca"))
        self.assertTrue(inconclusive["recommendations"])
        self.assertEqual(inconclusive["recommendations"][0]["recommendation_type"],"investigation")
        missing=self.engine.generate(context=self.context("missing_evidence"))
        self.assertEqual(missing["context_status"],"insufficient_context")
        self.assertEqual(missing["recommendations"],[])

    def test_detector_disagreement_keeps_both_detector_references(self):
        result=self.engine.generate(context=self.context("detector_disagreement"))
        item=next(x for x in result["recommendations"] if x["rule_id"]=="detector_disagreement_diagnostics")
        detectors={e["detector"] for e in item["supporting_evidence"]}
        self.assertEqual(detectors,{"rolling_mean_standard_deviation","isolation_forest"})
        self.assertEqual(item["confidence_label"],"weak_evidence")

    def test_potential_blast_radius_never_claims_observed_failure(self):
        result=self.engine.generate(context=self.context("potential_blast_radius"))
        item=next(x for x in result["recommendations"] if x["rule_id"]=="potential_blast_radius_check")
        self.assertIn("potential structural impact",item["supporting_evidence"][0]["interpretation"])
        self.assertTrue(any("potential" in x.lower() for x in item["assumptions"]))

    def test_idempotent_generation_and_snapshot(self):
        context=self.context("database_pool_exhaustion")
        first=self.engine.generate(context=context); second=self.engine.generate(context=context)
        self.assertEqual(first["run_id"],second["run_id"])
        self.assertEqual(first["recommendations"],second["recommendations"])
        self.assertEqual(len(self.store.list_recommendations()),1)

    def test_lifecycle_transitions_audit_and_feedback_persist(self):
        result=self.engine.generate(context=self.context("database_pool_exhaustion"))
        rec=result["recommendations"][0]; rid=rec["recommendation_id"]
        self.store.update_status(rid,"acknowledged")
        self.store.update_status(rid,"in_progress")
        self.store.update_status(rid,"completed",notes="verified recovery metrics")
        self.assertEqual(self.store.get_recommendation(rid)["status"],"completed")
        self.assertEqual(len(self.store.history(rid)),4)
        with self.assertRaises(ValueError): self.store.update_status(rid,"dismissed",reason="late")
        feedback=self.store.record_feedback({"recommendation_id":rid,"outcome_status":"successful","observed_evidence":[{"metric":"wait_ms","value":0}]})
        self.assertEqual(feedback["outcome_status"],"successful")
        self.assertEqual(len(self.store.feedback_history(rid)),1)

    def test_status_validation_and_recommendation_model_validation(self):
        with self.assertRaises(ValueError):
            Recommendation("id",None,"run","title","desc","mitigation",(),"urgent","now","strong_evidence",(),(),(),"benefit","low",(),(),(),(),(),"stage3")

    def test_stage3_to_stage7_context_is_read_without_mutating_source_records(self):
        conn=self.store.connection
        conn.executescript("""
        CREATE TABLE processed_events(event_id TEXT PRIMARY KEY,payload TEXT NOT NULL,processed_at TEXT NOT NULL);
        CREATE TABLE incidents(incident_id TEXT PRIMARY KEY,status TEXT,created_at TEXT,updated_at TEXT,severity TEXT,anchor_event_id TEXT,merged_into TEXT,summary TEXT);
        CREATE TABLE incident_members(event_id TEXT PRIMARY KEY,incident_id TEXT);
        CREATE TABLE rca_investigations(investigation_id TEXT PRIMARY KEY,incident_id TEXT,created_at TEXT,report TEXT);
        CREATE TABLE blast_radius_analyses(analysis_id TEXT PRIMARY KEY,incident_id TEXT,root_service_id TEXT,created_at TEXT,payload TEXT);
        CREATE TABLE intelligence_runs(run_id TEXT PRIMARY KEY,created_at TEXT);
        CREATE TABLE intelligence_findings(finding_id TEXT PRIMARY KEY,run_id TEXT,finding_type TEXT,created_at TEXT,payload_json TEXT);
        """)
        event={"event_id":"evt-db","original_event":{"event_id":"evt-db","service":"database-service","event_type":"db_pool_exhausted","message":"pool exhausted","severity":"CRITICAL","timestamp":"2025-01-01T00:00:00Z"},"classification":{"categories":["database_failures"]},"patterns":[]}
        conn.execute("INSERT INTO processed_events VALUES(?,?,?)",("evt-db",json.dumps(event),"2025-01-01"))
        conn.execute("INSERT INTO incidents VALUES(?,?,?,?,?,?,?,?)",("inc-1","active","t","t","CRITICAL","evt-db",None,"db pool issue"))
        conn.execute("INSERT INTO incident_members VALUES(?,?)",("evt-db","inc-1"))
        conn.execute("INSERT INTO rca_investigations VALUES(?,?,?,?)",("rca-1","inc-1","t",json.dumps({"assessment_status":"inconclusive","hypotheses":[]})))
        conn.execute("INSERT INTO blast_radius_analyses VALUES(?,?,?,?,?)",("blast-1","inc-1","database-service","t",json.dumps({"analysis_id":"blast-1","root_service_id":"database-service","graph_version":"g1","impacted_services":[{"service_id":"payment-service"}]})))
        conn.execute("INSERT INTO intelligence_runs VALUES(?,?)",("ir-1","t"))
        finding={"finding_id":"f-1","finding_type":"statistical_anomaly","affected_service_ids":["database-service"],"related_incidents":["inc-1"],"evidence_references":[{"event_id":"evt-db"}],"detector":"rolling_mean_standard_deviation","window_start":"2025-01-01T00:00:00Z"}
        conn.execute("INSERT INTO intelligence_findings VALUES(?,?,?,?,?)",("f-1","ir-1","statistical_anomaly","t",json.dumps(finding)))
        conn.commit()
        before=conn.execute("SELECT payload FROM processed_events WHERE event_id='evt-db'").fetchone()[0]
        result=self.engine.generate(incident_id="inc-1")
        self.assertEqual(result["context_status"],"ready")
        self.assertTrue(any(x["rule_id"]=="db_pool_diagnostics" for x in result["recommendations"]))
        self.assertTrue(any(x["rule_id"]=="potential_blast_radius_check" for x in result["recommendations"]))
        after=conn.execute("SELECT payload FROM processed_events WHERE event_id='evt-db'").fetchone()[0]
        self.assertEqual(before,after)

    def test_evaluation_reports_explicit_synthetic_denominators(self):
        report=evaluate()
        self.assertEqual(report["scenario_count"],15)
        self.assertEqual(report["scenario_match_rate"]["denominator"],15)
        self.assertEqual(report["inappropriate_mitigation_suggestions"]["numerator"],0)
        self.assertIn("not_production_quality",report["evaluation_type"])


if __name__=="__main__": unittest.main()
