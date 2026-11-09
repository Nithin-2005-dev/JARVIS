"""Command line interface for file, REST, and simulated live ingestion."""

from __future__ import annotations

import argparse
import json

from .ingestion.adapters import CSVFileAdapter, JSONFileAdapter, LiveEventAdapter, RESTAPIAdapter
from .ingestion.engine import IngestionEngine
from .ingestion.storage import SQLiteEventStore
from .simulator import Scenario, Simulator


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest and normalize PayFlow events")
    parser.add_argument("--source", choices=("json", "csv", "rest", "live"), required=True)
    parser.add_argument("--input", help="JSON/JSONL/CSV path; required except for REST and live")
    parser.add_argument("--url", help="REST endpoint URL")
    parser.add_argument("--database", default="data/events.sqlite")
    parser.add_argument("--quarantine", default="data/quarantine.jsonl")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--seed", type=int, default=42, help="seed for simulated live source")
    parser.add_argument("--payments", type=int, default=3, help="payments per scenario for live source")
    args = parser.parse_args()
    if args.source in ("json", "csv") and not args.input:
        parser.error("--input is required for file sources")
    if args.source == "rest" and not args.url:
        parser.error("--url is required for REST source")
    if args.source == "json":
        adapter = JSONFileAdapter(args.input)
    elif args.source == "csv":
        adapter = CSVFileAdapter(args.input)
    elif args.source == "rest":
        adapter = RESTAPIAdapter(args.url, args.timeout)
    else:
        adapter = LiveEventAdapter(Simulator(seed=args.seed).generate(Scenario.ALL, args.payments), "simulated_live")
    with SQLiteEventStore(args.database) as store:
        report = IngestionEngine(store, args.quarantine).ingest(adapter)
    print(json.dumps(report.to_dict(), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
