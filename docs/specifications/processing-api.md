# Event processing API

## Python

```python
from payflow_simulator.processing import ProcessingConfig, ProcessingEngine, SQLiteProcessingStore

config = ProcessingConfig(environment="staging", window_seconds=60)
with SQLiteProcessingStore("data/events.sqlite") as store:
    report = ProcessingEngine(store, config).run()
print(report.to_dict())
```

The engine processes pending and failed input rows in SQLite batches until none remain. `run(limit=N)` caps attempts for that invocation. `run(reprocess=True)` explicitly replays completed rows and replaces derived output for the same event ID. `ProcessingReport` includes received/attempted, processed, failed, patterns emitted, reprocessed, total duration, throughput, average event latency, and summed successful per-stage durations.

`SQLiteProcessingStore` implements the `ProcessingStore` protocol. A pipeline accepts replaceable enrichment, classification, temporal, and pattern stage objects, which supports alternate implementations without changing orchestration.

## CLI

```bash
python3 -m payflow_simulator.process_cli --database data/events.sqlite
python3 -m payflow_simulator.process_cli --database data/events.sqlite --config processing.json --limit 1000
python3 -m payflow_simulator.process_cli --database data/events.sqlite --reprocess
```

The CLI emits a JSON report to stdout and structured JSON logs to stderr for stage/persistence failures. The same SQLite database must contain the Stage 2 `events` table; an empty or newly initialized database reports zero work.

## Processed event representation

The `processed_events.payload` JSON object contains schema version, event ID, untouched `original_event`, `processing_timestamp`, and separate `enrichment`, `classification`, `temporal`, and `patterns` objects/lists. Measured stage durations are reported as operational metrics and are not embedded in event data. The processed table is keyed by event ID; source rows remain in `events`.
