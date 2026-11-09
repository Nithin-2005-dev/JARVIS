"""Stage 7 feature, baseline, detector, pattern, dependency, and persistence tests."""
from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from payflow_simulator.dependency_graph.graph_builder import DependencyGraphBuilder
from payflow_simulator.dependency_graph.graph_store import SQLiteDependencyGraphStore
from payflow_simulator.dependency_graph.service_registry import default_config
from payflow_simulator.intelligence.anomaly_detection import detect_anomalies, isolation_forest_score
from payflow_simulator.intelligence.baseline import build_baselines
from payflow_simulator.intelligence.cross_service_analysis import analyze_cross_service
from payflow_simulator.intelligence.engine import IntelligenceEngine
from payflow_simulator.intelligence.evaluation import build_synthetic_dataset, run_evaluation
from payflow_simulator.intelligence.feature_extraction import extract_features
from payflow_simulator.intelligence.models import IntelligenceConfig
from payflow_simulator.intelligence.pattern_discovery import discover_patterns
from payflow_simulator.intelligence.storage import SQLiteIntelligenceStore
from payflow_simulator.intelligence.temporal_analysis import analyze_temporal


class IntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = IntelligenceConfig(minimum_baseline_windows=2, isolation_minimum_samples=3,
            isolation_trees=12, rolling_lookback_windows=4, pattern_minimum_support=2,
            pattern_similarity_threshold=0.45, pattern_pair_limit=4)
        self.base = datetime(2025, 1, 1, tzinfo=timezone.utc)

    def tearDown(self): self.temp.cleanup()

    def event(self, ident, service="payment-service", index=0, severity="INFO", event_type="request_completed", message="request completed", **extra):
        timestamp = self.base + timedelta(seconds=index*300)
        original = {"event_id":ident,"service":service,"event_type":event_type,"severity":severity,
            "message":message,"timestamp":timestamp.isoformat().replace("+00:00","Z"),"source":"test"}
        original.update(extra)
        return {"event_id":ident,"original_event":original,"processing_timestamp":(timestamp+timedelta(seconds=10)).isoformat().replace("+00:00","Z")}

    def feature(self, index, service="payment-service", count=10, error_rate=0.0):
        start=self.base+timedelta(seconds=index*300)
        return {"service_id":service,"window_start":start.isoformat().replace("+00:00","Z"),
            "window_end":(start+timedelta(seconds=300)).isoformat().replace("+00:00","Z"),
            "event_count":count,"error_rate":error_rate,"critical_count":0,"warning_count":0,
            "event_type_counts":{"request_completed":count},"signature_counts":{},
            "mean_interarrival_seconds":20.0,"latency_mean_ms":None,"missing_fields":["latency"],
            "source_event_ids":[f"event-{service}-{index}"],"source_timestamps":[],"feature_provenance":{}}

    def test_feature_extraction_utc_aggregates_provenance_and_missing_latency(self):
        first=self.event("a",index=0,severity="ERROR",latency_ms=13)
        first["original_event"]["timestamp"]="2025-01-01T01:00:00+01:00"
        first["original_event"]["metadata"]={"resource_id":"db-primary"}
        second=self.event("b",index=0,severity="WARN")
        original=copy.deepcopy(first)
        result=extract_features([first,second],self.config)
        self.assertEqual(len(result["features"]),1)
        feature=result["features"][0]
        self.assertEqual(feature["window_start"],"2025-01-01T00:00:00Z")
        self.assertEqual(feature["event_count"],2)
        self.assertEqual(feature["error_rate"],0.5)
        self.assertEqual(feature["latency_mean_ms"],13.0)
        self.assertEqual(feature["severity_counts"],{"ERROR":1,"WARN":1})
        self.assertEqual(feature["resource_counts"],{"resource_id:db-primary":1})
        self.assertIn("latency",extract_features([second],self.config)["features"][0]["missing_fields"])
        self.assertEqual(first,original)
        self.assertEqual(len(feature["source_event_ids"]),2)
        incomplete=self.event("incomplete",index=1)
        del incomplete["original_event"]["severity"]
        incomplete_feature=extract_features([incomplete],self.config)["features"][0]
        self.assertIsNone(incomplete_feature["error_rate"])
        self.assertIn("severity",incomplete_feature["missing_fields"])

    def test_invalid_or_missing_timestamp_is_preserved_as_quality_finding(self):
        invalid=self.event("bad")
        invalid["original_event"]["timestamp"]="not-a-timestamp"
        missing=self.event("missing")
        del missing["original_event"]["timestamp"]
        result=extract_features([invalid,missing],self.config)
        self.assertEqual(result["events_with_invalid_timestamps"],2)
        self.assertEqual({row["event_id"] for row in result["invalid_timestamp_events"]},{"bad","missing"})

    def test_baselines_are_strictly_prior_reproducible_and_rolling_capped(self):
        rows=[self.feature(i) for i in range(7)]
        first=build_baselines(rows,self.config)["baselines"]
        second=build_baselines(list(reversed(rows)),self.config)["baselines"]
        self.assertEqual(first,second)
        sixth=next(b for b in first if b["target_window_start"]==rows[6]["window_start"])
        self.assertEqual(len(sixth["training_window_starts"]),4)
        self.assertEqual(sixth["training_window_starts"],[rows[i]["window_start"] for i in range(2,6)])
        self.assertNotIn(rows[6]["window_start"],sixth["training_window_starts"])
        self.assertEqual(first[0]["status"],"insufficient_data")
        self.assertEqual(first[2]["status"],"ready")

    def test_statistical_detector_handles_zero_variance_and_excludes_target(self):
        rows=[self.feature(i) for i in range(4)]+[self.feature(4,count=30)]
        baselines=build_baselines(rows,self.config)["baselines"]
        detected=detect_anomalies(rows,baselines,self.config)
        target=[x for x in detected["statistical_findings"] if x["window_start"]==rows[4]["window_start"]]
        count_finding=next(x for x in target if x["feature"]=="event_count")
        self.assertTrue(count_finding["zero_variance_comparison"])
        self.assertGreater(count_finding["deviation_score"],self.config.statistical_threshold)
        self.assertNotIn(rows[4]["window_start"],count_finding["expected_baseline"]["training_windows"])

    def test_isolation_forest_is_deterministic_and_distinct_from_statistical_score(self):
        train=[[10.0,0.0],[10.0,0.0],[11.0,0.0],[9.0,0.0],[10.0,0.0],[10.0,0.0]]
        first=isolation_forest_score(train,[80.0,1.0],trees=20,sample_size=6,seed=99)
        second=isolation_forest_score(train,[80.0,1.0],trees=20,sample_size=6,seed=99)
        self.assertEqual(first,second)
        self.assertGreater(first[0],0.5)
        self.assertEqual(len(first[1]),20)

    def test_ml_detector_returns_insufficient_data_before_training_minimum(self):
        rows=[self.feature(i) for i in range(2)]
        baselines=build_baselines(rows,self.config)["baselines"]
        result=detect_anomalies(rows,baselines,self.config)
        self.assertTrue(all(item["uncertainty_status"]=="insufficient_data" for item in result["machine_learning_findings"]))

    def test_temporal_summary_reports_invalid_timestamps_and_late_events(self):
        rows=[self.feature(i) for i in range(3)]
        late=self.event("late",index=0)
        late["processing_timestamp"]=(self.base+timedelta(days=1)).isoformat().replace("+00:00","Z")
        result=analyze_temporal(rows,[],[{"event_id":"bad","reason":"invalid"}],self.config,[late])
        self.assertEqual(len(result["late_arrival_observations"]),1)
        self.assertEqual(result["invalid_timestamp_events"][0]["event_id"],"bad")
        self.assertEqual(result["service_trends"][0]["status"],"observed_trend_summary")

    def test_patterns_exact_approximate_and_computation_cap(self):
        events=[]
        for index in (0,2,4): events.append(self.event(f"exact-{index}",index=index,severity="ERROR",event_type="db_pool_exhausted",message="connection pool exhausted"))
        for index in (1,3): events.append(self.event(f"approx-{index}",service="api-gateway",index=index,severity="ERROR",event_type="request_failed",message="request failed upstream"))
        for index in (1,3): events.append(self.event(f"approx2-{index}",service="payment-service",index=index,severity="ERROR",event_type="request_failed",message="request failed dependency"))
        result=discover_patterns(events,[],self.config)
        self.assertTrue(any(x["match_kind"]=="exact_normalized_signature" for x in result["exact_signature_patterns"]))
        self.assertTrue(result["approximate_signature_patterns"])
        self.assertLessEqual(result["similarity_comparisons"],self.config.pattern_pair_limit)
        self.assertTrue(all("event_id" in ref for x in result["exact_signature_patterns"] for ref in x["evidence_references"]))
        self.assertTrue(all(x["score_interpretation"].startswith("Jaccard") for x in result["approximate_signature_patterns"]))

    def test_cross_service_dependency_context_is_explainable_and_bounded(self):
        graph=DependencyGraphBuilder(default_config()).build()
        findings=[]
        for service,window in (("database-service","2025-01-01T00:00:00Z"),("payment-service","2025-01-01T00:05:00Z")):
            findings.extend([{"finding_type":"statistical_anomaly","service_id":service,"window_start":window,
                "uncertainty_status":"heuristic_anomaly_signal","detector":detector,
                "evidence_references":[{"event_id":f"{service}-{detector}"}]} for detector in ("rolling_mean_standard_deviation","isolation_forest")])
        result=analyze_cross_service(findings,graph,self.config)
        self.assertEqual(result["relationship_count"],1)
        rel=result["relationships"][0]
        self.assertEqual(rel["finding_type"],"dependency_service_anomaly_preceded_dependent_service_anomaly")
        self.assertEqual(rel["dependency_path"],["payment-service","database-service"])
        self.assertIn("do not establish", " ".join(rel["confidence_limitations"]))
        limited=IntelligenceConfig(minimum_baseline_windows=2,rolling_lookback_windows=4,isolation_minimum_samples=3,cross_service_max_relationships=1)
        expanded=analyze_cross_service(findings*10,graph,limited)
        self.assertLessEqual(expanded["relationship_count"],1)
        dense=[]
        for index in range(10):
            window=(self.base+timedelta(seconds=index*300)).isoformat().replace("+00:00","Z")
            dense.extend([{"finding_type":"ml_anomaly","service_id":service,"window_start":window,
                "uncertainty_status":"heuristic_anomaly_signal","evidence_references":[]} for service in ("database-service","payment-service")])
        capped=IntelligenceConfig(minimum_baseline_windows=2,rolling_lookback_windows=4,isolation_minimum_samples=3,
            cross_service_max_candidate_pairs=3)
        bounded=analyze_cross_service(dense,graph,capped)
        self.assertEqual(bounded["candidate_pair_count"],3)
        self.assertTrue(bounded["candidate_pairs_truncated"])

    def test_unrelated_services_are_not_linked_and_missing_graph_is_explicit(self):
        graph=DependencyGraphBuilder(default_config()).build()
        findings=[{"finding_type":"ml_anomaly","service_id":"authentication-service","window_start":"2025-01-01T00:00:00Z","uncertainty_status":"heuristic_anomaly_signal"},
                  {"finding_type":"ml_anomaly","service_id":"notification-service","window_start":"2025-01-01T00:00:00Z","uncertainty_status":"heuristic_anomaly_signal"}]
        self.assertEqual(analyze_cross_service(findings,graph,self.config)["relationship_count"],0)
        self.assertEqual(analyze_cross_service(findings,None,self.config)["status"],"dependency_graph_unavailable")

    def test_run_is_idempotent_persisted_and_preserves_detector_disagreement(self):
        events,_=build_synthetic_dataset()
        # Use a smaller deterministic input while retaining multiple service windows.
        selected=[event for event in events if event["original_event"]["service"]=="payment-service" and
                  int(event["original_event"]["timestamp"][17:19])<60]
        db=self.root/"intel.sqlite"
        with SQLiteIntelligenceStore(db) as store:
            engine=IntelligenceEngine(store,self.config)
            first=engine.run(selected); second=engine.run(selected)
            self.assertEqual(first["run_id"],second["run_id"])
            self.assertEqual(len(store.history()),1)
            self.assertIn("statistical_findings",first["detectors"])
            self.assertIn("machine_learning_findings",first["detectors"])
            self.assertTrue(first["findings"])
            self.assertTrue(all(f["finding_id"] and "score_interpretation" in f and "evidence_references" in f for f in first["findings"]))
            self.assertTrue(all(f["score_breakdown"].get("is_probability") is False for f in first["findings"]))
            self.assertGreater(store.connection.execute("SELECT COUNT(*) FROM intelligence_models").fetchone()[0],0)
            changed=IntelligenceConfig(minimum_baseline_windows=2,isolation_minimum_samples=3,isolation_trees=12,
                rolling_lookback_windows=4,pattern_minimum_support=2,pattern_similarity_threshold=0.45,
                pattern_pair_limit=4,statistical_threshold=2.5)
            third=IntelligenceEngine(store,changed).run(selected)
            self.assertNotEqual(first["run_id"],third["run_id"])
            self.assertEqual(len(store.history()),2)
            self.assertTrue(set(x["finding_id"] for x in first["findings"]).isdisjoint(x["finding_id"] for x in third["findings"]))

    def test_known_incident_sequence_is_retrospective_and_excludes_future_findings(self):
        events=[self.event("before",index=3)]
        findings=[{"finding_type":"statistical_anomaly","service_id":"payment-service","window_start":"2025-01-01T00:05:00Z","window_end":"2025-01-01T00:10:00Z","detector":"rolling"},
            {"finding_type":"ml_anomaly","service_id":"payment-service","window_start":"2025-01-01T00:15:00Z","window_end":"2025-01-01T00:20:00Z","detector":"forest"}]
        incidents=[{"incident_id":"known-incident","event_ids":["before"]}]
        result=analyze_temporal([],findings,[],self.config,events,incidents)
        sequence=result["known_incident_preceding_sequences"][0]
        self.assertEqual(sequence["preceding_anomaly_count"],1)
        self.assertIn("Retrospective",sequence["interpretation"])

    def test_evidence_links_to_existing_incident_rca_and_blast_radius(self):
        db=self.root/"integrated.sqlite"; events=[self.event("proof-event",index=i) for i in range(5)]
        events.append(self.event("proof-event-anomaly",index=5,severity="ERROR",event_type="request_failed",message="processor failed"))
        with SQLiteIntelligenceStore(db) as store:
            store.connection.executescript("""
            CREATE TABLE incidents(incident_id TEXT PRIMARY KEY,created_at TEXT);
            CREATE TABLE incident_members(event_id TEXT PRIMARY KEY,incident_id TEXT);
            CREATE TABLE rca_investigations(investigation_id TEXT,incident_id TEXT,report TEXT,created_at TEXT);
            CREATE TABLE blast_radius_analyses(analysis_id TEXT,incident_id TEXT,created_at TEXT,payload TEXT);
            INSERT INTO incidents VALUES('incident-existing','2025-01-01T00:00:00Z');
            INSERT INTO incident_members VALUES('proof-event-anomaly','incident-existing');
            INSERT INTO rca_investigations VALUES('rca-existing','incident-existing','{"assessment_status":"competing_hypotheses","hypotheses":[{"candidate_service":"payment-service"}]}','2025-01-01T00:01:00Z');
            INSERT INTO blast_radius_analyses VALUES('blast-existing','incident-existing','2025-01-01T00:02:00Z','{"root_service_id":"database-service","graph_version":"g1","impacted_services":[{"service_id":"payment-service"}]}');
            """)
            result=IntelligenceEngine(store,self.config).run(events)
            linked=[f for f in result["findings"] if "proof-event-anomaly" in json.dumps(f["evidence_references"])]
            self.assertTrue(linked)
            self.assertTrue(all("incident-existing" in f["related_incidents"] for f in linked))
            self.assertTrue(all("rca-existing" in f["related_rca_reports"] for f in linked))
            self.assertTrue(all("blast-existing" in f["related_blast_radius_analyses"] for f in linked))
            self.assertTrue(all(f["historical_context"]["rca"][0]["candidate_service_overlap"] for f in linked))
            self.assertTrue(all(f["historical_context"]["blast_radius"][0]["potential_impact_overlap"] for f in linked))

    def test_stage6_graph_snapshot_is_consumed_without_mutation(self):
        db=self.root/"shared.sqlite"
        graph=DependencyGraphBuilder(default_config()).build()
        with SQLiteDependencyGraphStore(db) as graph_store: graph_store.save_graph(graph)
        events=[]
        for i in range(6):
            events.append(self.event(f"db-{i}",service="database-service",index=i,
                severity="ERROR" if i==5 else "INFO",event_type="db_pool_exhausted" if i==5 else "query_succeeded"))
            events.append(self.event(f"pay-{i}",service="payment-service",index=i,
                severity="ERROR" if i==5 else "INFO",event_type="request_failed" if i==5 else "request_completed"))
        original=copy.deepcopy(events)
        with SQLiteIntelligenceStore(db) as store:
            result=IntelligenceEngine(store,self.config).run(events)
            self.assertEqual(result["graph_version"],graph.graph_version)
            self.assertGreater(result["cross_service_analysis"]["relationship_count"],0)
            self.assertEqual(events,original)

    def test_transaction_rolls_back_run_features_and_findings(self):
        db=self.root/"rollback.sqlite"; events=[self.event(f"e-{i}",index=i) for i in range(5)]
        with SQLiteIntelligenceStore(db) as store:
            store.connection.execute("CREATE TRIGGER reject_stage7_finding BEFORE INSERT ON intelligence_findings BEGIN SELECT RAISE(ABORT,'forced'); END")
            with self.assertRaises(sqlite3.IntegrityError): IntelligenceEngine(store,self.config).run(events)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM intelligence_runs").fetchone()[0],0)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM intelligence_features").fetchone()[0],0)

    def test_evaluation_is_time_ordered_reproducible_and_reports_weak_ml_precision(self):
        first=run_evaluation(); second=run_evaluation()
        self.assertEqual(first["statistical"],second["statistical"])
        self.assertEqual(first["machine_learning"],second["machine_learning"])
        self.assertEqual(first["scenario_denominator"],12)
        self.assertTrue(first["no_future_data_leakage"])
        self.assertEqual(first["timestamp_quality"]["invalid_timestamp_events"],2)
        self.assertTrue(next(x for x in first["scenario_results"] if x["scenario"]=="cold_start_insufficient_history")["insufficient_baseline"])
        self.assertLess(first["machine_learning"]["precision"],1.0)
        self.assertIn("ground_truth_positive_denominator",first["machine_learning"])


if __name__ == "__main__": unittest.main()
