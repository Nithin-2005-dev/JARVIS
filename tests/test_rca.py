"""RCA unit and persistence tests covering strengths and limits of the evidence."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from payflow_simulator.rca import RCAConfig, RCAEngine, SQLiteRCAStore
from payflow_simulator.rca.evaluate import _MemoryStore, run_evaluation, scenarios


def processed(eid: str, service: str, event_type: str, severity: str, minute: int, message: str,
              *, category: str = "infrastructure_failures", metadata: dict | None = None, trace: str | None = "trace-a") -> dict:
    return {"event_id": eid, "original_event": {"event_id": eid, "service": service, "event_type": event_type,
            "severity": severity, "timestamp": f"2025-01-01T00:{minute:02d}:00Z", "message": message,
            "trace_id": trace, "metadata": metadata or {}},
            "temporal": {"event_timestamp": f"2025-01-01T00:{minute:02d}:00Z"},
            "classification": {"categories": [category]}}


class RCAEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "events.sqlite"
        with SQLiteRCAStore(self.path) as store:
            db = store.connection
            db.executescript("CREATE TABLE incidents(incident_id TEXT PRIMARY KEY,status TEXT,created_at TEXT,updated_at TEXT,severity TEXT,anchor_event_id TEXT,merged_into TEXT,summary TEXT); CREATE TABLE incident_members(event_id TEXT PRIMARY KEY,incident_id TEXT); CREATE TABLE processed_events(event_id TEXT PRIMARY KEY,payload TEXT); CREATE TABLE correlation_edges(source_event_id TEXT,target_event_id TEXT,run_id TEXT,strategy TEXT,evidence TEXT,confidence_score REAL,PRIMARY KEY(source_event_id,target_event_id,strategy));")
            db.execute("INSERT INTO incidents VALUES('inc-1','active','2025-01-01','2025-01-01','CRITICAL','db-1',NULL,'simulated incident')")
            self.events = [
                processed("db-1", "database-service", "db_pool_exhausted", "CRITICAL", 3, "database connection pool exhausted", category="database_failures", metadata={"database_id": "db-primary"}),
                processed("pay-1", "payment-service", "downstream_failure", "ERROR", 4, "database request failed", category="application_errors", metadata={"database_id": "db-primary"}),
                processed("api-1", "api-gateway", "request_failed", "ERROR", 5, "payment request failed", category="application_errors", metadata={"database_id": "db-primary"}),
            ]
            for item in self.events:
                db.execute("INSERT INTO processed_events VALUES(?,?)", (item["event_id"], json.dumps(item)))
                db.execute("INSERT INTO incident_members VALUES(?, 'inc-1')", (item["event_id"],))
            db.execute("INSERT INTO correlation_edges VALUES(?,?,?,?,?,?)", ("db-1", "pay-1", "corr-1", "resource", json.dumps({"strategy":"resource", "description":"shared database"}), .91))
            db.commit()

    def tearDown(self) -> None: self.temp.cleanup()

    def test_pool_exhaustion_candidate_and_downstream_competitor_are_explained(self) -> None:
        with SQLiteRCAStore(self.path) as store:
            report = RCAEngine(store).investigate("inc-1")
            self.assertIn(report["assessment_status"], {"leading_hypothesis", "competing_hypotheses", "inconclusive"})
            ids = {h["candidate_event_id"] for h in report["hypotheses"]}
            self.assertEqual(ids, {"db-1", "pay-1", "api-1"})
            self.assertTrue(all(not h["confirmed"] for h in report["hypotheses"]))
            self.assertEqual(report["confirmed_causes"], [])
            db_hyp = next(h for h in report["hypotheses"] if h["candidate_event_id"] == "db-1")
            self.assertTrue(any(e["family"] == "resource_exhaustion" for e in db_hyp["supporting_evidence"]))
            self.assertTrue(any(e["family"] == "correlation" for e in db_hyp["supporting_evidence"]))
            self.assertTrue(db_hyp["missing_evidence"])

    def test_missing_trace_and_metrics_are_explicit_and_unknown(self) -> None:
        with SQLiteRCAStore(self.path) as store:
            # Replace records with an event that lacks a trace ID and metric source.
            item = processed("no-trace", "database-service", "network_failure", "ERROR", 1, "network timeout", trace=None)
            store.connection.execute("DELETE FROM incident_members")
            store.connection.execute("DELETE FROM processed_events")
            store.connection.execute("INSERT INTO processed_events VALUES(?,?)", (item["event_id"], json.dumps(item)))
            store.connection.execute("INSERT INTO incident_members VALUES('no-trace','inc-1')")
            store.connection.commit()
            report = RCAEngine(store).investigate("inc-1")
            missing = report["hypotheses"][0]["missing_evidence"]
            self.assertTrue(any(e["family"] == "trace_evidence" for e in missing))
            self.assertTrue(any(e["family"] == "metrics" for e in missing))
            self.assertEqual(report["confirmed_causes"], [])

    def test_repeat_requests_are_idempotent_and_snapshot_retrievable(self) -> None:
        with SQLiteRCAStore(self.path) as store:
            engine = RCAEngine(store)
            first = engine.investigate("inc-1")
            second = engine.investigate("inc-1")
            self.assertEqual(first["investigation_id"], second["investigation_id"])
            self.assertEqual(store.get_investigation(first["investigation_id"])["fingerprint"], first["fingerprint"])
            self.assertEqual(len(store.history("inc-1")), 1)
            self.assertEqual(len(store.compare(first["investigation_id"])), len(first["hypotheses"]))

    def test_unknown_incident_raises_clear_key_error(self) -> None:
        with SQLiteRCAStore(self.path) as store:
            with self.assertRaises(KeyError): RCAEngine(store).investigate("missing")

    def test_malformed_timestamp_is_preserved_with_temporal_evidence_gap(self) -> None:
        with SQLiteRCAStore(self.path) as store:
            event = processed("bad-time", "database-service", "db_pool_exhausted", "CRITICAL", 1, "pool exhausted")
            event["temporal"]["event_timestamp"] = "not-a-timestamp"
            store.connection.execute("DELETE FROM incident_members")
            store.connection.execute("DELETE FROM processed_events")
            store.connection.execute("INSERT INTO processed_events VALUES(?,?)", ("bad-time", json.dumps(event)))
            store.connection.execute("INSERT INTO incident_members VALUES('bad-time','inc-1')")
            store.connection.commit()
            report = RCAEngine(store).investigate("inc-1")
            self.assertEqual(report["event_timeline"][0]["event_id"], "bad-time")
            self.assertIsNone(report["event_timeline"][0]["event_time"])
            self.assertTrue(any(e["family"] == "event_time" for e in report["hypotheses"][0]["missing_evidence"]))

    def test_synthetic_evaluation_is_repeatable_and_documents_ambiguity(self) -> None:
        first = run_evaluation()
        second = run_evaluation()
        self.assertEqual(first["top1_accuracy"], second["top1_accuracy"])
        self.assertEqual(first["top_k_candidate_recall"], 1.0)
        self.assertEqual(first["false_root_cause_assertion_rate"], 0.0)
        self.assertGreater(first["inconclusive_assessment_rate"], 0.0)
        self.assertTrue(first["performance"]["events_per_second"] > 0)
        ambiguous = next(s for s in scenarios() if s["name"] == "ambiguous_multiple_failures")
        context = {"incident":{"incident_id":"ambiguous","summary":"ambiguous"}, "events":ambiguous["events"], "correlations":[]}
        report = RCAEngine(_MemoryStore(context)).investigate("ambiguous")
        self.assertEqual(report["assessment_status"], "competing_hypotheses")
        self.assertIsNone(report["leading_hypothesis"])
        self.assertEqual(len(report["alternative_hypotheses"]), 2)

    def test_failed_snapshot_transaction_leaves_no_partial_investigation(self) -> None:
        with SQLiteRCAStore(self.path) as store:
            store.connection.execute("CREATE TRIGGER reject_hypothesis BEFORE INSERT ON rca_hypotheses BEGIN SELECT RAISE(ABORT, 'forced'); END")
            store.connection.commit()
            with self.assertRaises(Exception): RCAEngine(store).investigate("inc-1")
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM rca_investigations").fetchone()[0], 0)
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM rca_history").fetchone()[0], 0)
            store.connection.execute("DROP TRIGGER reject_hypothesis")
            store.connection.commit()
            self.assertTrue(RCAEngine(store).investigate("inc-1")["hypotheses"])

    def test_late_arrival_is_not_ordered_by_processing_time(self) -> None:
        with SQLiteRCAStore(self.path) as store:
            event = self.events[0]
            event["temporal"].update({"event_timestamp": "2025-01-01T00:03:00Z", "processing_timestamp": "2025-01-01T00:10:00Z", "late_arrival": True, "out_of_order": True})
            event["processing_timestamp"] = "2025-01-01T00:10:00Z"
            store.connection.execute("UPDATE processed_events SET payload=? WHERE event_id='db-1'", (json.dumps(event),))
            store.connection.commit()
            report = RCAEngine(store).investigate("inc-1")
            late = next(x for x in report["event_timeline"] if x["event_id"] == "db-1")
            self.assertEqual(late["event_time"], "2025-01-01T00:03:00Z")
            self.assertEqual(late["processing_time"], "2025-01-01T00:10:00Z")
            self.assertTrue(late["late_arrival"])

    def test_dependency_configuration_is_labeled_inference_and_can_contradict(self) -> None:
        with SQLiteRCAStore(self.path) as store:
            config = RCAConfig(service_dependencies={"payment-service": ("notification-service",)})
            report = RCAEngine(store, config).investigate("inc-1")
            payment = next(h for h in report["hypotheses"] if h["candidate_event_id"] == "pay-1")
            evidence = [*payment["supporting_evidence"], *payment["contradictory_evidence"]]
            path = next(e for e in evidence if e["family"] == "dependency_path")
            self.assertEqual(path["evidence_type"], "inferred_dependency")
            self.assertEqual(path["polarity"], "contradictory")
            self.assertIn("may be incomplete or incorrect", path["description"])


if __name__ == "__main__": unittest.main()
