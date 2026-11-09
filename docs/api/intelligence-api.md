# Intelligence API and CLI

## Python API

```python
from payflow_simulator.intelligence import IntelligenceConfig, IntelligenceEngine, SQLiteIntelligenceStore

with SQLiteIntelligenceStore("data/events.sqlite") as store:
    engine = IntelligenceEngine(store, IntelligenceConfig())
    features = engine.extract_features()            # Stage 3 processed_events
    baselines = engine.build_baselines(features["features"])
    detectors = engine.detect(features["features"], baselines["baselines"])
    snapshot = engine.run()                         # temporal, patterns, Stage 6, persistence
    previous = store.get_run(snapshot["run_id"])
    runs = store.history()
```

`extract_features`, `build_baselines`, and `detect` are independently callable. `run(events=...)` accepts caller-supplied processed-event-shaped mappings; otherwise it reads `processed_events`. `SQLiteIntelligenceStore` provides processed event/incident/graph reads and transactional run/history/evaluation persistence. An unavailable Stage 6 graph is returned as `dependency_graph_unavailable` and is not fabricated.

## CLI

```bash
python3 -m payflow_simulator.intelligence.intelligence_cli features
python3 -m payflow_simulator.intelligence.intelligence_cli baseline
python3 -m payflow_simulator.intelligence.intelligence_cli detect
python3 -m payflow_simulator.intelligence.intelligence_cli temporal
python3 -m payflow_simulator.intelligence.intelligence_cli patterns
python3 -m payflow_simulator.intelligence.intelligence_cli cross-service
python3 -m payflow_simulator.intelligence.intelligence_cli analyze
python3 -m payflow_simulator.intelligence.intelligence_cli history
python3 -m payflow_simulator.intelligence.intelligence_cli history --run-id RUN_ID
python3 -m payflow_simulator.intelligence.intelligence_cli evaluate --output-dir data/evaluation
```

Use `--database PATH` to select the shared Stage 2–6 SQLite file and `--config FILE.json` for explicit `IntelligenceConfig` fields; `data/intelligence-config.example.json` contains defaults, including both cross-service candidate and output caps. Component CLI commands currently execute and persist the complete deterministic pipeline, then select the requested output section. Evaluation writes the synthetic JSONL, ground truth, and metrics under its output directory and saves a metrics snapshot in the selected database.

## Snapshot schema

Findings contain deterministic finding ID, type, affected service IDs, event-time window, observed facts, baseline reference, detector, detector-specific raw score/interpretation, traceable evidence references, linked Stage 4 incident/Stage 5 RCA/Stage 6 analysis IDs where event membership overlaps, comparative hypothesis/structural-impact overlap notes, limitations, uncertainty state, detector/config versions, and creation timestamp. A candidate overlap remains context and does not confirm cause or impact. Source event records remain unchanged. See `intelligence_runs`, `intelligence_features`, `intelligence_baselines`, `intelligence_findings`, `intelligence_models`, and `intelligence_evaluations` tables.
