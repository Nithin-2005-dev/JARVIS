# J.A.R.V.I.S. — Stages 1–7: PayFlow Event Intelligence Prototype

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
- `payflow_simulator/rca/`: candidate generation, evidence collection, transparent scoring, competing hypotheses, report snapshots, and synthetic evaluation.
- `payflow_simulator/dependency_graph/`: service/dependency registry, graph validation/versioning, cycle-safe blast-radius analysis, Stage 4/5 integration, and evaluation.
- `payflow_simulator/dependency_cli.py`: graph, validation, blast-radius, incident, and history CLI.
- `payflow_simulator/intelligence/`: feature extraction, rolling baselines, statistical and Isolation Forest detectors, temporal/pattern/cross-service analysis, SQLite persistence, and evaluation.
- `tests/`: Stage 1–7 unit and integration tests.
- `data/sample_events.jsonl`: generated sample.
- `docs/`: architecture, engineering, specification, milestone and troubleshooting notes.

The five payment services remain represented as simulator event producers. Ingestion accepts JSON/JSONL, CSV, REST GET, and simulated live events. Processing enriches and classifies records, handles event time, detects patterns, and writes recoverable output to SQLite. Stage 4 correlates processed records with explainable evidence. Stage 5 ranks competing root-cause hypotheses and permits inconclusive results. Stage 6 versions a directed service dependency graph and calculates potential structural blast radius with paths, criticality, and heuristic impact scores. It integrates with incidents and RCA snapshots without treating candidates as confirmed causes. See the [dependency graph architecture](docs/architecture/service-dependency-architecture.md), [blast-radius architecture](docs/architecture/blast-radius-architecture.md), [Stage 6 report](docs/milestones/milestone-06.md), and [known limitations](docs/troubleshooting/known-issues.md).

Stage 7 builds service-window features and strictly prior baselines, keeps statistical and Isolation Forest outputs separate, discovers recurring signatures, and adds dependency context. Anomaly signals do not create incidents or root-cause claims. See [Stage 7 architecture](docs/architecture/advanced-intelligence-architecture.md) and the [known limitations](docs/troubleshooting/known-issues.md).

## Dependency graph and blast radius

```bash
python3 -m payflow_simulator.dependency_cli validate
python3 -m payflow_simulator.dependency_cli graph
python3 -m payflow_simulator.dependency_cli blast-radius --service database-service --max-depth 3
python3 -m payflow_simulator.dependency_cli incident --incident-id INCIDENT_ID
python3 -m payflow_simulator.dependency_cli history --incident-id INCIDENT_ID
```

Graph direction is `A -> B` meaning “A depends on B”; impact traversal follows reverse edges. Scores are heuristic structural impact scores, not probabilities. Competing or inconclusive RCA candidates are analyzed as separate hypothetical scenarios. See the [Dependency Graph API](docs/api/dependency-graph-api.md) and [Blast Radius API](docs/api/blast-radius-api.md). Reproduce Stage 6 evaluation artifacts with `python3 -m payflow_simulator.dependency_graph.evaluate --output data/evaluation/stage6_dependency_metrics.json --dataset-dir data/evaluation`.

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

## Stage 7 intelligence

```bash
python3 -m payflow_simulator.intelligence.intelligence_cli --database data/events.sqlite analyze
python3 -m payflow_simulator.intelligence.intelligence_cli --database data/events.sqlite history
python3 -m payflow_simulator.intelligence.intelligence_cli --database data/events.sqlite evaluate --output-dir data/evaluation
```

Component commands include `features`, `baseline`, `detect`, `temporal`, `patterns`, and `cross-service`. Raw detector scores are detector-specific heuristic outputs, not probabilities. Insufficient history is explicit. Reproduce the synthetic benchmark with `python3 -m payflow_simulator.intelligence.evaluation --output-dir data/evaluation`. See the [Intelligence API](docs/api/intelligence-api.md), [anomaly detector design](docs/architecture/anomaly-detection-architecture.md), [temporal intelligence](docs/architecture/temporal-intelligence.md), and [Stage 7 evaluation](docs/evaluation/stage-07-evaluation.md).
