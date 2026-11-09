# Development setup

Requirements: Python 3.10 or newer. No packages need installation.

From repository root:

```bash
python3 -m payflow_simulator.cli --help
python3 -m payflow_simulator.cli --scenario all --seed 42 --payments 3 --output data/sample_events.jsonl
python3 -m payflow_simulator.ingest_cli --source json --input data/sample_events.jsonl
python3 -m payflow_simulator.process_cli --database data/events.sqlite
python3 -m unittest discover -s tests -v
```

The output directory is created when needed. `--start-time` accepts a timezone-aware ISO-8601 value; payment count must be positive.

Ingestion defaults to persistent SQLite at `data/events.sqlite` and appends invalid records to `data/quarantine.jsonl`. Select `--source csv --input FILE`, `--source json --input FILE`, `--source rest --url URL`, or `--source live`. See [ingestion API](../specifications/ingestion-api.md).

Processing reads ingested rows and writes `processed_events` and state/history tables into the same database. Use `--config docs/path.json` for processing rules and windows, and `--reprocess` only when intentionally replaying completed rows. See [processing configuration](../specifications/processing-configuration.md).
