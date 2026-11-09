# J.A.R.V.I.S. — Stages 1–5: PayFlow Event Intelligence Prototype

J.A.R.V.I.S. currently includes the Stage 1 deterministic PayFlow simulator and the Stage 2 multi-source event ingestion engine. Python 3.10+ is required; no third-party dependencies are used.

## Quick start

```bash
python3 -m payflow_simulator.cli --scenario all --seed 42 --payments 3 --output data/sample_events.jsonl
python3 -m payflow_simulator.ingest_cli --source json --input data/sample_events.jsonl
python3 -m payflow_simulator.process_cli --database data/events.sqlite
python3 -m unittest discover -s tests -v
```

Use `python3 -m payflow_simulator.cli --help` for options. Scenarios: `all`, `normal`, `db_pool_exhaustion`, `downstream_failure`. The fixed default UTC start time and seed make output reproducible.

## Structure

- `payflow_simulator/models.py`: event schema and validation.
- `payflow_simulator/simulator.py`: scenario engine and JSONL output.
- `payflow_simulator/cli.py`: CLI.
- `payflow_simulator/ingestion/`: source adapters, canonicalization, batch engine, quarantine, and SQLite storage.
- `payflow_simulator/ingest_cli.py`: ingestion CLI.
- `payflow_simulator/processing/`: enrichment, classification, temporal windows, pattern detection, state, and output storage.
- `payflow_simulator/process_cli.py`: processing runner.
- `payflow_simulator/correlation/`: candidate generation, evidence scoring, incident lifecycle, SQLite persistence, and synthetic evaluation.
- `payflow_simulator/correlation_cli.py`: correlation and incident investigation CLI.
- `tests/`: Stage 1–4 unit and integration tests.
- `data/sample_events.jsonl`: generated sample.
- `docs/`: architecture, engineering, specification, milestone and troubleshooting notes.

The five payment services remain represented as simulator event producers. Ingestion accepts JSON/JSONL, CSV, REST GET, and simulated live events. The processing command enriches and classifies ingested rows, annotates event-time windows, detects repeat/frequency patterns, and writes recoverable output to the same SQLite database. Stage 4 correlates processed records with explainable evidence, conservative incident grouping, stable IDs, and history. Stage 5 ranks competing root-cause hypotheses over incident evidence, preserves report snapshots, and explicitly allows inconclusive outcomes. It does not confirm causes or equate correlation with causation. See the [RCA architecture](docs/architecture/root-cause-analysis-architecture.md), [Stage 5 report](docs/milestones/milestone-05.md), and [known limitations](docs/troubleshooting/known-issues.md).

## Correlation and investigation

After ingestion and processing, run:

```bash
python3 -m payflow_simulator.correlation_cli --database data/events.sqlite --config data/correlation-config.example.json run --measure-memory
python3 -m payflow_simulator.correlation_cli --database data/events.sqlite list
python3 -m payflow_simulator.correlation_cli --database data/events.sqlite stats
python3 -m payflow_simulator.rca_cli --database data/events.sqlite investigate INCIDENT_ID
python3 -m payflow_simulator.rca_cli --database data/events.sqlite compare INVESTIGATION_ID
```

Inspect an incident with `show INCIDENT_ID`, `events INCIDENT_ID`, `evidence INCIDENT_ID`, and `history INCIDENT_ID`; inspect event neighbors with `related EVENT_ID`. Correlation scores are heuristics, not probabilities, and event relationships do not establish cause. RCA exposes `investigate`, `show`, `hypothesis`, `evidence`, `compare`, `history`, and `report`; see [RCA API/CLI](docs/specifications/rca-api.md). Reproduce Stage 4 evaluation with `python3 -m payflow_simulator.correlation.evaluate --output-dir data/evaluation`; reproduce Stage 5 evaluation and data with `python3 -m payflow_simulator.rca.evaluate --output data/evaluation/stage5_rca_metrics.json --dataset-dir data/evaluation`.
