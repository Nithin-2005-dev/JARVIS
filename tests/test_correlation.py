"""Stage 4 unit and SQLite integration tests, including false-positive guards."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from payflow_simulator.correlation import CorrelationConfig, CorrelationEngine, SQLiteCorrelationStore
from payflow_simulator.processing.storage import SQLiteProcessingStore


class CorrelationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "events.sqlite"
        with SQLiteProcessingStore(self.db):
            pass
        self.store = SQLiteCorrelationStore(self.db)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    @staticmethod
    def processed(*, service="payment-service", timestamp="2025-01-01T00:00:00Z", severity="ERROR",
                  event_type="request_failed", message="payment backend unavailable", trace=None, metadata=None,
                  categories=None, event_id=None, late=False, patterns=None):
        event_id = event_id or str(uuid4())
        original = {"event_id": event_id, "timestamp": timestamp, "service": service, "event_type": event_type,
                    "severity": severity, "message": message, "source": "test", "trace_id": trace or "",
                    "metadata": metadata or {}}
        return {"schema_version": "1.0", "event_id": event_id, "original_event": original,
                "processing_timestamp": "2025-01-02T00:00:00Z", "classification": {"categories": categories or ["application_errors"]},
                "temporal": {"event_timestamp": timestamp, "processing_timestamp": "2025-01-02T00:00:00Z", "late_arrival": late},
                "patterns": patterns or []}

    def insert(self, *events):
        self.store.connection.executemany("INSERT INTO processed_events(event_id,payload,processed_at) VALUES(?,?,?)",
            [(item["event_id"], json.dumps(item), item["processing_timestamp"]) for item in events])
        self.store.connection.commit()

    def run_engine(self, config=None):
        return CorrelationEngine(self.store, config).run()

    def test_shared_trace_creates_explainable_incident(self):
        a = self.processed(service="api-gateway", trace="trace-1")
        b = self.processed(service="payment-service", trace="trace-1", timestamp="2025-01-01T00:00:04Z")
        self.insert(a, b)
        report = self.run_engine()
        self.assertEqual((report.relationships_accepted, report.incidents_created), (1, 1))
        incident = self.store.list_incidents()[0]
        evidence = self.store.incident_evidence(incident["incident_id"])
        trace_evidence = next(item for item in evidence if item["strategy"] == "trace")
        self.assertEqual(trace_evidence["evidence"]["supporting_attributes"]["trace_id"], "trace-1")
        self.assertEqual(trace_evidence["evidence"]["source_event_id"], min(a["event_id"], b["event_id"]))

    def test_shared_database_resource_links_across_services(self):
        a = self.processed(service="database-service", metadata={"database_id": "db-primary"})
        b = self.processed(service="payment-service", metadata={"database_id": "DB-PRIMARY"})
        self.insert(a, b)
        self.run_engine()
        incident = self.store.list_incidents()[0]
        edge = self.store.incident_evidence(incident["incident_id"])[0]
        resource_evidence = next(item for item in self.store.incident_evidence(incident["incident_id"]) if item["strategy"] == "resource")
        self.assertEqual(resource_evidence["evidence"]["supporting_attributes"]["shared_resources"], ["database_id:db-primary"])

    def test_temporal_dependency_failures_correlate_but_time_alone_does_not(self):
        a = self.processed(service="payment-service", timestamp="2025-01-01T00:00:00Z")
        b = self.processed(service="database-service", timestamp="2025-01-01T00:00:10Z")
        self.insert(a, b)
        self.run_engine()
        self.assertEqual(len(self.store.list_incidents()), 1)
        self.store.connection.execute("DELETE FROM processed_events")
        x = self.processed(service="mystery-a", timestamp="2025-01-01T00:00:00Z", trace=None)
        y = self.processed(service="mystery-b", timestamp="2025-01-01T00:00:00Z", trace=None)
        self.insert(x, y)
        # Generic errors at the same time are not candidates without a registered dependency.
        self.run_engine()
        self.assertEqual(self.store.list_incidents(), [])

    def test_distinct_trace_boundaries_block_time_dependency_bridge_without_resource(self):
        a = self.processed(service="payment-service", trace="request-a", timestamp="2025-01-01T00:00:00Z")
        b = self.processed(service="database-service", trace="request-b", timestamp="2025-01-01T00:00:01Z")
        self.insert(a, b)
        self.run_engine()
        self.assertEqual(self.store.list_incidents(), [])

    def test_unrelated_simultaneous_events_and_similar_messages_do_not_merge(self):
        a = self.processed(service="unrelated-a", message="connection refused at node 42", metadata={"resource_id": "one"})
        b = self.processed(service="unrelated-b", message="connection refused at node 99", metadata={"resource_id": "two"})
        self.insert(a, b)
        self.run_engine()
        self.assertEqual(self.store.list_incidents(), [])

    def test_missing_trace_is_safe_and_late_event_uses_event_time(self):
        a = self.processed(service="api-gateway", trace=None, timestamp="2025-01-01T00:00:00Z", metadata={"server_id": "edge-1"})
        b = self.processed(service="payment-service", trace=None, timestamp="2025-01-01T00:00:01Z", metadata={"server_id": "edge-1"}, late=True)
        self.insert(a, b)
        report = self.run_engine()
        self.assertEqual(report.late_events, 1)
        self.assertEqual(report.skipped_events, 0)
        self.assertEqual(len(self.store.list_incidents()), 1)

    def test_new_late_event_is_added_to_prior_trace_incident(self):
        first = self.processed(trace="arriving-late", timestamp="2025-01-01T00:00:10Z")
        self.insert(first)
        self.run_engine()
        self.assertEqual(self.store.list_incidents(), [])
        late = self.processed(trace="arriving-late", timestamp="2025-01-01T00:00:00Z", late=True)
        self.insert(late)
        report = self.run_engine()
        self.assertEqual(report.late_events, 1)
        self.assertEqual(len(self.store.list_incidents()), 1)
        self.assertEqual(len(self.store.list_incidents()[0]["event_ids"]), 2)

    def test_incident_severity_is_recomputed_from_current_members(self):
        a = self.processed(trace="severity", severity="INFO")
        b = self.processed(trace="severity", severity="CRITICAL")
        self.insert(a, b)
        self.run_engine()
        incident_id = self.store.list_incidents()[0]["incident_id"]
        self.assertEqual(self.store.get_incident(incident_id)["severity"], "CRITICAL")
        b["original_event"]["severity"] = "INFO"
        self.store.connection.execute("UPDATE processed_events SET payload=? WHERE event_id=?", (json.dumps(b), b["event_id"]))
        self.store.connection.commit()
        self.run_engine()
        self.assertEqual(self.store.get_incident(incident_id)["severity"], "INFO")

    def test_trace_diagnostics_flag_missing_single_service_and_excessive_span(self):
        a = self.processed(service="payment-service", trace="trace-one")
        b = self.processed(service="payment-service", trace="trace-one", timestamp="2025-01-01T00:10:00Z")
        missing = self.processed(service="isolated", trace=None)
        self.insert(a, b, missing)
        self.run_engine()
        diagnostics = self.store.get_trace_diagnostics()
        by_trace = {item["trace_id"]: item for item in diagnostics}
        self.assertIn("single_service_observed", by_trace["trace-one"]["status"])
        self.assertIn("span_exceeds_configured_lateness", by_trace["trace-one"]["status"])
        self.assertIn("missing_trace_ids", by_trace[None]["status"])

    def test_malformed_processed_timestamp_is_reported_without_aborting_run(self):
        valid = self.processed(trace="safe")
        invalid = self.processed()
        invalid["temporal"]["event_timestamp"] = "not-a-time"
        invalid["original_event"]["timestamp"] = "not-a-time"
        self.insert(valid, invalid)
        report = self.run_engine()
        self.assertEqual(report.events_received, 2)
        self.assertEqual(report.skipped_events, 1)

    def test_duplicate_event_ingestion_is_prevented_by_primary_key(self):
        event = self.processed(trace="same")
        self.insert(event)
        with self.assertRaises(Exception):
            self.insert(event)
        self.store.connection.rollback()
        self.assertEqual(self.run_engine().events_received, 1)

    def test_repeated_run_is_idempotent_and_ids_are_stable(self):
        a = self.processed(trace="stable")
        b = self.processed(trace="stable")
        self.insert(a, b)
        first = self.run_engine()
        iid = self.store.list_incidents()[0]["incident_id"]
        second = self.run_engine()
        self.assertEqual(first.run_id, second.run_id)
        self.assertEqual(second.incidents_created, 0)
        self.assertEqual(iid, self.store.list_incidents()[0]["incident_id"])
        self.assertEqual(len(self.store.incident_history(iid)), 3)  # created + two members

    def test_new_strong_bridge_merges_incidents_and_records_history(self):
        a, b = self.processed(trace="A"), self.processed(trace="A")
        c, d = self.processed(trace="B"), self.processed(trace="B")
        self.insert(a, b, c, d)
        self.run_engine()
        before = self.store.list_incidents()
        self.assertEqual(len(before), 2)
        # Shared resource edge joins the former components directly.
        bridge = self.processed(trace="A", metadata={"resource_id": "join"})
        c2 = self.processed(trace="B", metadata={"resource_id": "join"})
        self.insert(bridge, c2)
        self.run_engine()
        active = self.store.list_incidents()
        self.assertEqual(len(active), 1)
        merged = self.store.get_incident(active[0]["incident_id"])
        self.assertEqual(merged["status"], "active")
        self.assertTrue(any(item["action"] == "merged" for iid in [x["incident_id"] for x in before]
                            for item in self.store.incident_history(iid)))

    def test_removing_relationship_splits_and_resolves_prior_incident(self):
        a = self.processed(trace="split")
        b = self.processed(trace="split")
        self.insert(a, b)
        self.run_engine()
        iid = self.store.list_incidents()[0]["incident_id"]
        b["original_event"]["trace_id"] = "different"
        self.store.connection.execute("UPDATE processed_events SET payload=? WHERE event_id=?", (json.dumps(b), b["event_id"]))
        self.store.connection.commit()
        self.run_engine()
        self.assertEqual(self.store.list_incidents(), [])
        self.assertEqual(self.store.get_incident(iid)["status"], "resolved")
        self.assertTrue(any(item["action"] in {"split", "resolved"} for item in self.store.incident_history(iid)))

    def test_split_into_two_incidents_preserves_anchor_identity(self):
        events = [self.processed(trace="original") for _ in range(4)]
        self.insert(*events)
        self.run_engine()
        prior = self.store.list_incidents()[0]["incident_id"]
        ordered = sorted(events, key=lambda event: event["event_id"])
        for index, item in enumerate(ordered):
            item["original_event"]["trace_id"] = "left" if index < 2 else "right"
            self.store.connection.execute("UPDATE processed_events SET payload=? WHERE event_id=?", (json.dumps(item), item["event_id"]))
        self.store.connection.commit()
        self.run_engine()
        active = self.store.list_incidents()
        self.assertEqual(len(active), 2)
        self.assertIn(prior, {item["incident_id"] for item in active})
        self.assertTrue(any(item["action"] == "split" for item in self.store.incident_history(prior)))

    def test_pattern_similarity_is_weak_and_not_sufficient(self):
        a = self.processed(service="service-a", message="database unavailable request failed")
        b = self.processed(service="service-b", message="database unavailable request failed")
        self.insert(a, b)
        self.run_engine()
        self.assertEqual(self.store.list_incidents(), [])

    def test_failed_transaction_rolls_back_every_correlation_write(self):
        a, b = self.processed(trace="tx"), self.processed(trace="tx")
        self.insert(a, b)
        self.store.connection.execute("CREATE TRIGGER fail_edges BEFORE INSERT ON correlation_edges BEGIN SELECT RAISE(ABORT,'forced'); END")
        with self.assertRaises(Exception):
            self.run_engine()
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM incidents").fetchone()[0], 0)
        failed = self.store.connection.execute("SELECT status FROM correlation_runs").fetchone()
        self.assertEqual(failed[0], "failed")
        self.store.connection.execute("DROP TRIGGER fail_edges")
        self.store.connection.commit()
        self.run_engine()
        completed = self.store.connection.execute("SELECT status FROM correlation_runs").fetchone()
        self.assertEqual(completed[0], "completed")

    def test_large_sparse_dataset_uses_bounded_candidate_pairs_and_reports_metrics(self):
        events = [self.processed(service=f"service-{i % 20}", severity="INFO", event_type="request_received",
                                 categories=["uncategorized"], timestamp=f"2025-01-01T00:{i // 60:02d}:{i % 60:02d}Z",
                                 trace=f"trace-{i}") for i in range(1200)]
        self.insert(*events)
        report = CorrelationEngine(self.store).run(measure_memory=True)
        self.assertLess(report.candidate_pairs, len(events) * 3)
        self.assertGreater(report.events_per_second, 0)
        self.assertGreater(report.memory_peak_bytes or 0, 0)


if __name__ == "__main__":
    unittest.main()
