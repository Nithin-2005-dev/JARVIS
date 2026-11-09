# J.A.R.V.I.S. — Stage 1: PayFlow Simulator

J.A.R.V.I.S. currently includes the Stage 1 deterministic PayFlow simulator and the Stage 2 multi-source event ingestion engine. Python 3.10+ is required; no third-party dependencies are used.

## Quick start

```bash
python3 -m payflow_simulator.cli --scenario all --seed 42 --payments 3 --output data/sample_events.jsonl
python3 -m payflow_simulator.ingest_cli --source json --input data/sample_events.jsonl
python3 -m unittest discover -s tests -v
```

Use `python3 -m payflow_simulator.cli --help` for options. Scenarios: `all`, `normal`, `db_pool_exhaustion`, `downstream_failure`. The fixed default UTC start time and seed make output reproducible.

## Structure

- `payflow_simulator/models.py`: event schema and validation.
- `payflow_simulator/simulator.py`: scenario engine and JSONL output.
- `payflow_simulator/cli.py`: CLI.
- `payflow_simulator/ingestion/`: source adapters, canonicalization, batch engine, quarantine, and SQLite storage.
- `payflow_simulator/ingest_cli.py`: ingestion CLI.
- `tests/`: Stage 1 unit tests and Stage 2 unit/integration tests.
- `data/sample_events.jsonl`: generated sample.
- `docs/`: architecture, engineering, specification, milestone and troubleshooting notes.

The five payment services remain represented as simulator event producers. Ingestion accepts JSON/JSONL, CSV, REST GET, and simulated live events, normalizes records, stores unique IDs in SQLite, and quarantines invalid input. See [ingestion architecture](docs/architecture/event-ingestion-architecture.md), [Stage 2 report](docs/milestones/milestone-02.md), and [known limitations](docs/troubleshooting/known-issues.md).
