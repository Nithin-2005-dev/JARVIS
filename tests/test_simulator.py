"""Unit tests for event validation and deterministic scenario generation."""

import json
import tempfile
import unittest
from pathlib import Path

from payflow_simulator.models import validate_event
from payflow_simulator.simulator import Scenario, Simulator, write_jsonl


class SimulatorTests(unittest.TestCase):
    def test_repeatable_and_unique_ids(self):
        first = [e.to_dict() for e in Simulator(seed=7).generate()]
        second = [e.to_dict() for e in Simulator(seed=7).generate()]
        self.assertEqual(first, second)
        ids = [event["event_id"] for event in first]
        self.assertEqual(len(ids), len(set(ids)))

    def test_all_required_services_and_scenarios_present(self):
        events = Simulator().generate()
        self.assertEqual({e.service for e in events}, {"api-gateway", "authentication-service", "payment-service", "database-service", "notification-service"})
        self.assertEqual({e.metadata["scenario"] for e in events}, {Scenario.NORMAL, Scenario.DB_POOL_EXHAUSTION, Scenario.DOWNSTREAM_FAILURE})

    def test_failure_scenarios_emit_expected_events(self):
        db_events = Simulator().generate(Scenario.DB_POOL_EXHAUSTION, payments=1)
        self.assertIn("db_pool_exhausted", [e.event_type.value for e in db_events])
        downstream = Simulator().generate(Scenario.DOWNSTREAM_FAILURE, payments=1)
        self.assertIn("downstream_failure", [e.event_type.value for e in downstream])

    def test_trace_correlation_and_monotonic_timestamps(self):
        events = Simulator().generate(Scenario.NORMAL, payments=2)
        for trace in {event.trace_id for event in events}:
            grouped = [event for event in events if event.trace_id == trace]
            timestamps = [event.timestamp for event in grouped]
            self.assertEqual(timestamps, sorted(timestamps))
            self.assertEqual(len({event.metadata["payment_id"] for event in grouped}), 1)

    def test_schema_validation_rejects_bad_event(self):
        with self.assertRaises(ValueError):
            validate_event({"event_id": "bad"})

    def test_jsonl_round_trip(self):
        events = Simulator().generate(Scenario.NORMAL, payments=1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            self.assertEqual(write_jsonl(events, path), len(events))
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), len(events))
            for row in rows:
                validate_event(row)


if __name__ == "__main__":
    unittest.main()
