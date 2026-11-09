"""Unit and local integration tests for Stage 2 ingestion."""

from __future__ import annotations

import csv
import json
import tempfile
import threading
import unittest
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

from payflow_simulator.ingestion.adapters import CSVFileAdapter, JSONFileAdapter, LiveEventAdapter, RESTAPIAdapter
from payflow_simulator.ingestion.engine import IngestionEngine
from payflow_simulator.ingestion.storage import SQLiteEventStore
from payflow_simulator.simulator import Scenario, Simulator, write_jsonl


class EventHandler(BaseHTTPRequestHandler):
    payload = b"[]"
    content_type = "application/json"

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", self.content_type)
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, *_args):
        pass


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / "events.sqlite"
        self.quarantine = self.root / "quarantine.jsonl"
        self.base = Simulator().generate(Scenario.NORMAL, payments=1)[0].to_dict()

    def tearDown(self):
        self.temp.cleanup()

    def engine(self):
        return IngestionEngine(SQLiteEventStore(self.db_path), self.quarantine)

    def test_json_array_and_jsonl_ingestion(self):
        array_path = self.root / "events.json"
        second = deepcopy(self.base)
        second["event_id"] = str(uuid4())
        array_path.write_text(json.dumps([self.base, second]), encoding="utf-8")
        report = self.engine().ingest(JSONFileAdapter(array_path))
        self.assertEqual((report.received, report.accepted, report.rejected), (2, 2, 0))

        jsonl_path = self.root / "fixture.jsonl"
        jsonl_path.write_text(json.dumps(self.base) + "\n", encoding="utf-8")
        report = self.engine().ingest(JSONFileAdapter(jsonl_path))
        self.assertEqual((report.received, report.duplicates), (1, 1))

    def test_malformed_json_is_quarantined_without_crashing(self):
        path = self.root / "bad.jsonl"
        path.write_text("{invalid json}\n" + json.dumps(self.base) + "\n", encoding="utf-8")
        report = self.engine().ingest(JSONFileAdapter(path))
        self.assertEqual((report.received, report.accepted, report.rejected), (2, 1, 1))
        row = json.loads(self.quarantine.read_text(encoding="utf-8").splitlines()[0])
        self.assertIn("malformed JSON", row["reason"])
        self.assertEqual(row["raw_record"], "{invalid json}")

    def test_malformed_json_document_quarantine(self):
        path = self.root / "broken.json"
        path.write_text("{not valid", encoding="utf-8")
        report = self.engine().ingest(JSONFileAdapter(path))
        self.assertEqual((report.received, report.rejected), (1, 1))

    def test_csv_ingestion_and_metadata_preservation(self):
        path = self.root / "events.csv"
        row = dict(self.base)
        row["metadata"] = json.dumps({"nested": {"keep": [1, 2]}, "scenario": "csv"})
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=row.keys())
            writer.writeheader()
            writer.writerow(row)
        report = self.engine().ingest(CSVFileAdapter(path))
        self.assertEqual(report.accepted, 1)
        stored = SQLiteEventStore(self.db_path)
        canonical = stored.get(self.base["event_id"])
        self.assertEqual(canonical["metadata"], {"nested": {"keep": [1, 2]}, "scenario": "csv"})
        stored.close()

    def test_rest_api_ingestion_with_local_server(self):
        event = deepcopy(self.base)
        event["severity"] = "warn"
        EventHandler.payload = json.dumps({"events": [event]}).encode()
        EventHandler.content_type = "application/json"
        server = ThreadingHTTPServer(("127.0.0.1", 0), EventHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            report = self.engine().ingest(RESTAPIAdapter(f"http://127.0.0.1:{server.server_port}/events"))
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
        self.assertEqual(report.accepted, 1)
        store = SQLiteEventStore(self.db_path)
        self.assertEqual(store.get(self.base["event_id"])["severity"], "WARNING")
        store.close()

    def test_normalization_and_validation_failures_are_isolated(self):
        good = deepcopy(self.base)
        good["timestamp"] = "2025-01-15T07:00:00-05:00"
        good["severity"] = "warn"
        good["service"] = "Payment_Service"
        good["source"] = "original-producer"
        good["metadata"]["custom"] = {"kept": True}
        invalids = []
        missing = deepcopy(self.base)
        del missing["trace_id"]
        invalids.append(missing)
        bad_timestamp = deepcopy(self.base)
        bad_timestamp["event_id"] = str(uuid4())
        bad_timestamp["timestamp"] = "yesterday"
        invalids.append(bad_timestamp)
        bad_severity = deepcopy(self.base)
        bad_severity["event_id"] = str(uuid4())
        bad_severity["severity"] = "verbose"
        invalids.append(bad_severity)
        bad_uuid = deepcopy(self.base)
        bad_uuid["event_id"] = "not-a-uuid"
        invalids.append(bad_uuid)
        batch = [good, *invalids]
        report = self.engine().ingest(LiveEventAdapter(batch))
        self.assertEqual((report.received, report.accepted, report.rejected), (5, 1, 4))
        self.assertEqual(len(self.quarantine.read_text(encoding="utf-8").splitlines()), 4)
        store = SQLiteEventStore(self.db_path)
        normalized = store.get(good["event_id"])
        self.assertEqual(normalized["timestamp"], "2025-01-15T12:00:00Z")
        self.assertEqual(normalized["service"], "payment-service")
        self.assertEqual(normalized["severity"], "WARNING")
        self.assertEqual(normalized["source"], "original-producer")
        self.assertEqual(normalized["metadata"]["custom"], {"kept": True})
        store.close()

    def test_duplicate_ids_within_and_across_repeated_batches(self):
        batch = [deepcopy(self.base), deepcopy(self.base)]
        first = self.engine().ingest(LiveEventAdapter(batch))
        second = self.engine().ingest(LiveEventAdapter(batch))
        self.assertEqual((first.accepted, first.duplicates), (1, 1))
        self.assertEqual((second.accepted, second.duplicates), (0, 2))

    def test_simulated_live_adapter_accepts_stage1_events(self):
        events = Simulator(seed=9).generate(Scenario.NORMAL, payments=1)
        report = self.engine().ingest(LiveEventAdapter(events, "simulated_live"))
        self.assertEqual(report.accepted, len(events))

    def test_large_jsonl_batch_streams_and_reports_throughput(self):
        path = self.root / "large.jsonl"
        event = deepcopy(self.base)
        with path.open("w", encoding="utf-8") as stream:
            for index in range(5000):
                row = deepcopy(event)
                row["event_id"] = str(uuid4())
                stream.write(json.dumps(row) + "\n")
        report = self.engine().ingest(JSONFileAdapter(path))
        self.assertEqual((report.received, report.accepted, report.rejected), (5000, 5000, 0))
        self.assertGreater(report.events_per_second, 0)
        store = SQLiteEventStore(self.db_path)
        self.assertEqual(store.count(), 5000)
        store.close()

    def test_read_stage1_sample_dataset_unchanged(self):
        sample = Path(__file__).parents[1] / "data" / "sample_events.jsonl"
        report = self.engine().ingest(JSONFileAdapter(sample))
        self.assertEqual((report.received, report.accepted, report.rejected), (63, 63, 0))


if __name__ == "__main__":
    unittest.main()
