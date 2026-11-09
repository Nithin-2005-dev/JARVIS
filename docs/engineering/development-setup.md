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
# Stage 4 commands

Correlation uses the same Python 3.10+ standard-library setup and existing Stage 2/3 SQLite database. After processing events, use `python3 -m payflow_simulator.correlation_cli --database data/events.sqlite run`. Inspect commands with `python3 -m payflow_simulator.correlation_cli --help`. Copy `data/correlation-config.example.json` to a project-specific config when adjusting thresholds or service dependencies. Generate evaluation fixtures with `python3 -m payflow_simulator.correlation.evaluate --output-dir data/evaluation`.
