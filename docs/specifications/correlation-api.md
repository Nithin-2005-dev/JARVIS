# Correlation API and CLI

The Python API is `CorrelationEngine(SQLiteCorrelationStore, CorrelationConfig).run(measure_memory=False)`. It returns a `CorrelationReport` with run ID, events received, candidate/accepted counts, incidents created, duration, stage timings, throughput, late/skipped counts, trace diagnostics count, and optional peak traced memory.

`SQLiteCorrelationStore` provides `list_incidents(status="active")`, `get_incident(id)`, `incident_events(id)`, `incident_evidence(id)`, `incident_history(id)`, `related_events(event_id)`, `get_trace_diagnostics()`, and `statistics()`. Statistics include the last run's `completed` or `failed` status. This service interface is framework-free; there is no network REST server in Stage 4.

CLI examples (global database/config options precede the subcommand):

```bash
python3 -m payflow_simulator.correlation_cli --database data/events.sqlite run --measure-memory
python3 -m payflow_simulator.correlation_cli --database data/events.sqlite list
python3 -m payflow_simulator.correlation_cli --database data/events.sqlite list --all
python3 -m payflow_simulator.correlation_cli --database data/events.sqlite show INCIDENT_ID
python3 -m payflow_simulator.correlation_cli --database data/events.sqlite events INCIDENT_ID
python3 -m payflow_simulator.correlation_cli --database data/events.sqlite evidence INCIDENT_ID
python3 -m payflow_simulator.correlation_cli --database data/events.sqlite history INCIDENT_ID
python3 -m payflow_simulator.correlation_cli --database data/events.sqlite related EVENT_ID
python3 -m payflow_simulator.correlation_cli --database data/events.sqlite stats
```

`run` requires the Stage 3 `processed_events` table in the Stage 2/3 database. There are no write APIs for manually editing incidents; grouping is derived from current processed events and configured rules.

The JSON shape and defaults are illustrated by [`data/correlation-config.example.json`](../../data/correlation-config.example.json). Unknown configuration keys and out-of-range weights/thresholds fail fast. Dependency values are lists of downstream service IDs.
