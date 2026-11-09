"""Unit/integration coverage for event processing, patterns, and recovery."""

from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from payflow_simulator.ingestion.adapters import LiveEventAdapter
from payflow_simulator.ingestion.adapters import JSONFileAdapter
from payflow_simulator.ingestion.engine import IngestionEngine
from payflow_simulator.ingestion.storage import SQLiteEventStore
from payflow_simulator.models import EventType
from payflow_simulator.processing.classification import EventClassifier
from payflow_simulator.processing.config import PatternThresholds, ProcessingConfig, config_from_dict
from payflow_simulator.processing.engine import ProcessingEngine
from payflow_simulator.processing.pipeline import ProcessingPipeline
from payflow_simulator.processing.storage import SQLiteProcessingStore
from payflow_simulator.processing.temporal import TemporalProcessor
from payflow_simulator.simulator import Scenario, Simulator


class ProcessingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "events.sqlite"
        self.quarantine = self.root / "quarantine.jsonl"
        self.fixed_clock = lambda: datetime(2025, 2, 1, 0, 0, tzinfo=timezone.utc)
        self.config = ProcessingConfig(batch_size=2, allowed_lateness_seconds=10)

    def tearDown(self):
        self.temp.cleanup()

    def make_event(self, *, event_type="request_failed", service="payment-service", severity="ERROR", message="processor failed", timestamp="2025-01-15T12:00:00Z"):
        event = Simulator().generate(Scenario.NORMAL, payments=1)[0].to_dict()
        event.update({
            "event_id": str(uuid4()), "trace_id": str(uuid4()), "timestamp": timestamp,
            "event_type": event_type, "service": service, "severity": severity, "message": message,
        })
        event["metadata"] = {"preserve_me": {"value": [1, 2, 3]}}
        event["source"] = "external-source"
        return event

    def ingest(self, events):
        with SQLiteEventStore(self.database) as store:
            return IngestionEngine(store, self.quarantine).ingest(LiveEventAdapter(events, "processing-test"))

    def open_engine(self, config=None, pipeline=None):
        store = SQLiteProcessingStore(self.database)
        return store, ProcessingEngine(store, config or self.config, pipeline or ProcessingPipeline(config or self.config, clock=self.fixed_clock))

    def test_enrichment_context_provenance_and_original_data_preserved(self):
        source = self.make_event(event_type="db_pool_exhausted", service="database-service", severity="CRITICAL")
        self.ingest([source])
        store, engine = self.open_engine()
        report = engine.run()
        result = store.get_processed(source["event_id"])
        self.assertEqual((report.processed, report.failed), (1, 0))
        self.assertEqual(result["original_event"], source)
        self.assertEqual(result["original_event"]["metadata"], source["metadata"])
        self.assertEqual(result["original_event"]["source"], "external-source")
        self.assertEqual(result["enrichment"]["environment"], "development")
        self.assertEqual(result["enrichment"]["application"], "payflow")
        self.assertEqual(result["enrichment"]["service_metadata"]["kind"], "storage")
        self.assertTrue(result["enrichment"]["enrichment_provenance"]["registry_match"])
        store.close()

    def test_unknown_service_is_enriched_as_unregistered(self):
        source = self.make_event(service="new-service")
        self.ingest([source])
        store, engine = self.open_engine()
        engine.run()
        enrichment = store.get_processed(source["event_id"])["enrichment"]
        self.assertEqual(enrichment["service_metadata"], {})
        self.assertFalse(enrichment["enrichment_provenance"]["registry_match"])
        store.close()

    def test_unknown_event_type_in_legacy_queue_is_preserved_and_classified(self):
        source = self.make_event(event_type="vendor_future_event", severity="ERROR")
        store = SQLiteProcessingStore(self.database)
        store.connection.execute(
            "INSERT INTO events(event_id,payload,adapter,locator) VALUES(?,?,?,?)",
            (source["event_id"], json.dumps(source), "legacy", "fixture"),
        )
        store.connection.commit()
        engine = ProcessingEngine(store, self.config, ProcessingPipeline(self.config, clock=self.fixed_clock))
        report = engine.run()
        result = store.get_processed(source["event_id"])
        self.assertEqual((report.processed, report.failed), (1, 0))
        self.assertEqual(result["original_event"]["event_type"], "vendor_future_event")
        self.assertTrue(result["classification"]["unknown_event_type"])
        self.assertIn("application_errors", result["classification"]["categories"])
        store.close()

    def test_classification_taxonomy_and_unknown_event_type(self):
        db_event = self.make_event(event_type="db_pool_exhausted", service="database-service", severity="CRITICAL", message="pool exhausted")
        self.ingest([db_event])
        store, engine = self.open_engine()
        engine.run()
        categories = store.get_processed(db_event["event_id"])["classification"]["categories"]
        self.assertIn("infrastructure_failures", categories)
        self.assertIn("database_failures", categories)
        self.assertIn("performance_degradation", categories)
        store.close()

        unknown = EventClassifier(self.config).classify({"event_type": "something_new", "severity": "ERROR", "service": "mystery", "message": "boom"})
        self.assertTrue(unknown["unknown_event_type"])
        self.assertIn("application_errors", unknown["categories"])

    def test_network_authentication_and_application_categories(self):
        samples = [
            ("downstream_failure", "notification-service", "ERROR", "provider unavailable", "network_failures"),
            ("request_failed", "authentication-service", "ERROR", "credential rejected", "authentication_failures"),
            ("request_failed", "payment-service", "ERROR", "unexpected exception", "application_errors"),
        ]
        for event_type, service, severity, message, expected in samples:
            result = EventClassifier(self.config).classify({"event_type": event_type, "service": service, "severity": severity, "message": message})
            self.assertIn(expected, result["categories"])

    def test_service_lifecycle_and_security_event_types_ingest_and_classify(self):
        lifecycle = self.make_event(event_type=EventType.SERVICE_STARTED.value, service="payment-service", severity="INFO", message="service started")
        security = self.make_event(event_type=EventType.SECURITY_ALERT.value, severity="ERROR", message="suspicious credential use")
        self.assertEqual(self.ingest([lifecycle, security]).accepted, 2)
        store, engine = self.open_engine()
        engine.run()
        self.assertIn("service_lifecycle_events", store.get_processed(lifecycle["event_id"])["classification"]["categories"])
        self.assertIn("security_related", store.get_processed(security["event_id"])["classification"]["categories"])
        store.close()

    def test_custom_classification_rules_load_from_config(self):
        config = config_from_dict({"classification_rules": [{"rule_id": "custom", "category": "security_related", "event_types": ["request_received"]}]})
        classifier = EventClassifier(config)
        result = classifier.classify({"event_type": "request_received", "severity": "INFO", "service": "api-gateway", "message": "request"})
        self.assertEqual(result["categories"], ["security_related"])
        self.assertEqual(result["rule_ids"], ["custom"])

    def test_out_of_order_and_late_events_preserve_event_time(self):
        later = self.make_event(timestamp="2025-01-15T12:00:30Z")
        earlier = self.make_event(timestamp="2025-01-15T12:00:00Z")
        self.ingest([later, earlier])
        store, engine = self.open_engine()
        report = engine.run()
        self.assertEqual(report.processed, 2)
        temporal = store.get_processed(earlier["event_id"])["temporal"]
        self.assertTrue(temporal["out_of_order"])
        self.assertTrue(temporal["late_arrival"])
        self.assertEqual(temporal["event_timestamp"], earlier["timestamp"])
        self.assertEqual(temporal["processing_timestamp"], "2025-02-01T00:00:00Z")
        self.assertEqual(temporal["previous_max_event_timestamp"], later["timestamp"])
        store.close()

    def test_allowed_lateness_boundary_is_inclusive(self):
        temporal = TemporalProcessor(ProcessingConfig(allowed_lateness_seconds=10))
        result = temporal.process({"timestamp": "2025-01-15T11:59:50Z"}, "2025-02-01T00:00:00Z", "2025-01-15T12:00:00Z")
        self.assertTrue(result["out_of_order"])
        self.assertFalse(result["late_arrival"])

    def test_subsecond_watermark_compares_chronologically(self):
        events = [
            self.make_event(timestamp="2025-01-15T12:00:00.900Z", severity="INFO", event_type="request_received"),
            self.make_event(timestamp="2025-01-15T12:00:00.950Z", severity="INFO", event_type="request_received"),
            self.make_event(timestamp="2025-01-15T12:00:00.910Z", severity="INFO", event_type="request_received"),
        ]
        self.ingest(events)
        store, engine = self.open_engine()
        engine.run()
        self.assertEqual(store.current_watermark(), "2025-01-15T12:00:00.95Z")
        temporal = store.get_processed(events[2]["event_id"])["temporal"]
        self.assertTrue(temporal["out_of_order"])
        store.close()

    def test_patterns_cross_batch_and_include_reproducible_evidence(self):
        config = ProcessingConfig(
            batch_size=2,
            patterns=PatternThresholds(
                repeated_error=2, recurring_failure=3, frequency_spike=3, repeated_across_services=2,
            ),
        )
        events = [
            self.make_event(service="payments-a"),
            self.make_event(service="payments-b"),
            self.make_event(service="payments-a"),
            self.make_event(service="payments-a"),
        ]
        self.ingest(events)
        store, engine = self.open_engine(config)
        report = engine.run()
        self.assertEqual(report.processed, 4)
        second = store.get_processed(events[1]["event_id"])["patterns"]
        self.assertIn("repeated_error", [item["kind"] for item in second])
        self.assertIn("repeated_across_services", [item["kind"] for item in second])
        recurring = store.get_processed(events[2]["event_id"])["patterns"]
        self.assertIn("recurring_failure_pattern", [item["kind"] for item in recurring])
        last = store.get_processed(events[3]["event_id"])["patterns"]
        self.assertIn("frequency_spike", [item["kind"] for item in last])
        self.assertIn(events[0]["event_id"], next(item for item in second if item["kind"] == "repeated_error")["evidence_event_ids"])
        self.assertTrue(all("no causal relationship" in item["interpretation"] for item in last))
        prior_outputs = {event["event_id"]: store.get_processed(event["event_id"]) for event in events}
        replay = engine.run(reprocess=True)
        self.assertEqual(replay.processed, 4)
        self.assertEqual({event["event_id"]: store.get_processed(event["event_id"]) for event in events}, prior_outputs)
        store.close()

    def test_pattern_evidence_is_bounded_but_count_is_complete(self):
        config = ProcessingConfig(batch_size=10, patterns=PatternThresholds(repeated_error=2, recurring_failure=3, frequency_spike=100, repeated_across_services=2))
        events = [self.make_event() for _ in range(25)]
        self.ingest(events)
        store, engine = self.open_engine(config)
        engine.run()
        pattern = next(item for item in store.get_processed(events[-1]["event_id"])["patterns"] if item["kind"] == "repeated_error")
        self.assertEqual(pattern["count"], 25)
        self.assertEqual(len(pattern["evidence_event_ids"]), 20)
        self.assertIn(events[-1]["event_id"], pattern["evidence_event_ids"])
        self.assertTrue(pattern["evidence_truncated"])
        store.close()

    def test_processing_is_idempotent_and_explicit_reprocess_records_history(self):
        event = self.make_event(severity="INFO", event_type="request_received")
        self.ingest([event])
        store, engine = self.open_engine()
        first = engine.run()
        original_output = store.get_processed(event["event_id"])
        second = engine.run()
        self.assertEqual(first.processed, 1)
        self.assertEqual(second.received, 0)
        replay = engine.run(reprocess=True)
        self.assertEqual((replay.reprocessed, replay.processed), (1, 1))
        self.assertEqual(store.get_processed(event["event_id"]), original_output)
        self.assertEqual(store.get_state(event["event_id"])["attempts"], 2)
        history = store.history(event["event_id"])
        self.assertEqual(sum(item["stage"] == "complete" for item in history), 2)
        self.assertEqual(store.get_processed(event["event_id"])["original_event"], event)
        store.close()

    def test_pipeline_failure_is_recorded_and_retry_recovers_without_losing_input(self):
        event = self.make_event()
        self.ingest([event])

        class FailingClassifier:
            def classify(self, _event):
                raise RuntimeError("classifier unavailable")

        pipeline = ProcessingPipeline(self.config, clock=self.fixed_clock, classifier=FailingClassifier())
        store, engine = self.open_engine(pipeline=pipeline)
        with self.assertLogs("payflow_simulator.processing.engine", level="WARNING") as captured:
            failed = engine.run()
        self.assertIn("event_processing_failed", captured.output[0])
        self.assertEqual((failed.processed, failed.failed), (0, 1))
        state = store.get_state(event["event_id"])
        self.assertEqual((state["status"], state["current_stage"]), ("failed", "classification"))
        self.assertIsNone(store.get_processed(event["event_id"]))
        self.assertIsNotNone(store.connection.execute("SELECT 1 FROM events WHERE event_id=?", (event["event_id"],)).fetchone())
        self.assertTrue(any(row["status"] == "failed" and row["stage"] == "classification" for row in store.history(event["event_id"])))
        recovered = ProcessingEngine(store, self.config, ProcessingPipeline(self.config, clock=self.fixed_clock)).run()
        self.assertEqual((recovered.processed, recovered.failed), (1, 0))
        self.assertEqual(store.get_state(event["event_id"])["status"], "processed")
        store.close()

    def test_stale_processing_claim_can_be_recovered(self):
        event = self.make_event(severity="INFO", event_type="request_received")
        self.ingest([event])
        store = SQLiteProcessingStore(self.database)
        first = store.claim_batch(1, run_id="worker-one")
        self.assertEqual(len(first), 1)
        store.connection.execute("UPDATE processing_state SET updated_at=0 WHERE event_id=?", (event["event_id"],))
        store.connection.commit()
        second = store.claim_batch(1, stale_after_seconds=1, run_id="worker-two")
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0].attempt, 2)
        store.close()

    def test_report_includes_stage_latency_and_throughput(self):
        self.ingest([self.make_event(severity="INFO", event_type="request_received")])
        store, engine = self.open_engine()
        report = engine.run()
        self.assertGreater(report.events_per_second, 0)
        self.assertGreaterEqual(report.average_event_latency_ms, 0)
        self.assertEqual(set(report.stage_durations_seconds), {"input_validation", "enrichment", "classification", "temporal", "pattern_detection"})
        store.close()

    def test_stage1_sample_ingestion_to_processed_output_end_to_end(self):
        sample = Path(__file__).parents[1] / "data" / "sample_events.jsonl"
        with SQLiteEventStore(self.database) as input_store:
            ingest_report = IngestionEngine(input_store, self.quarantine).ingest(JSONFileAdapter(sample))
        self.assertEqual(ingest_report.accepted, 63)
        store, engine = self.open_engine()
        process_report = engine.run()
        self.assertEqual((process_report.received, process_report.processed, process_report.failed), (63, 63, 0))
        self.assertEqual(store.state_counts(), {"processed": 63})
        store.close()


if __name__ == "__main__":
    unittest.main()
