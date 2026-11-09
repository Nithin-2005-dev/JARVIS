# Milestone 04 — Event Correlation Engine

**Status:** Implemented. Verification and the synthetic evaluation are documented here and in the [progress tracker](progress-tracker.md).

## Features implemented

- Correlation over successful Stage 3 processed records using trace, resource, event-time, configured service dependency, cross-service, and Stage 3 pattern evidence.
- Indexed candidate generation with a configurable 250,000-pair default ceiling; failure-category and dependency-aware time sweep; optional traced memory measurement.
- Per-strategy evidence with source/target IDs, strategy, description, supporting attributes, optional event-time difference, strategy score, combined heuristic confidence, and evaluation timestamp.
- Trace diagnostics for missing IDs, single-service observations, and spans beyond the configured lateness diagnostic.
- Conservative incident grouping, stable initial IDs, deterministic merge/split policies, severity updates, late-event reevaluation, current unique membership, and lifecycle history.
- Additive SQLite persistence, idempotent run IDs, transactional edge/incident changes, durable completed/failed correlation status, investigation API methods, config JSON, and `correlation_cli` commands.
- Deterministic synthetic labeled dataset and pairwise co-membership evaluation.

## Architecture and decisions

The engine reads `processed_events`; it leaves `events` and `processed_events` unchanged. Candidate generation avoids a blanket all-pairs join. The sparse expected cost is O(n log n + k), where `k` is emitted candidate pairs. Dense keys can still produce quadratic output, so `max_candidates` fails an oversized run before persisted edges/incidents are replaced.

Relationship confidence is a heuristic weighted mean, not a calibrated probability. Incident grouping requires a trace/shared-resource edge or temporal plus dependency evidence above threshold. Events with distinct non-empty trace IDs require shared-resource evidence to bridge. Text similarity and temporal overlap alone do not group; no relationship implies causality. Initial IDs use UUID5; merges keep the oldest incident ID, and splits keep the ID with the anchor event.

SQLite adds `correlation_runs`, `correlation_edges`, `trace_diagnostics`, `incidents`, `incident_members`, `incident_history`, and `correlation_metrics`. Data and lifecycle changes commit atomically. Stage 1–3 event payloads remain intact. A single-writer local database was selected to avoid premature distributed infrastructure.

## CLI and API

Use `python3 -m payflow_simulator.correlation_cli --database data/events.sqlite run`. Other commands are `list`, `show INCIDENT_ID`, `events INCIDENT_ID`, `evidence INCIDENT_ID`, `history INCIDENT_ID`, `related EVENT_ID`, and `stats`. The Python API is `CorrelationEngine.run()` and the retrieval methods on `SQLiteCorrelationStore`. There is no network REST server in Stage 4.

For a full workflow, generate/ingest/process the sample using the README commands, then run correlation. The checked in evaluation fixture is generated with:

```bash
python3 -m payflow_simulator.correlation.evaluate --output-dir data/evaluation
```

## Tests and actual results

`python3 -m unittest discover -s tests -v` — 53 tests passed, 0 failures/errors in 6.621 seconds. This includes all Stage 1–3 regression tests and 18 Stage 4 tests covering trace/resource/temporal/dependency evidence, distinct trace boundaries, false positives, missing/malformed inputs, late events, severity updates, merge/split, replay, rollback, and sparse large input.

The default synthetic evaluation generated 100 records: 20 groups of three (60 ground-truth related pairs) plus 20 simultaneous unrelated pairs. Ground-truth labels were not supplied to correlation. Observed pair results: 60 predicted pairs, 60 true positives, 0 false positives, 0 false negatives; precision 1.000, recall 1.000. This controlled fixture is not a production quality estimate.

One final local run measured 80 candidates, 0.1012 seconds candidate generation, 0.0969 seconds evaluation, 0.3138 seconds total, 319 events/second, and 586,997 bytes traced peak Python memory. Timings vary by host; `tracemalloc` omits SQLite/native allocator memory. The sparse 1,200-event test also completed and asserts candidate count under three times the record count.

End-to-end Stage 1 sample verification in a temporary database: 63 ingested, 63 processed, 0 processing failures, 63 correlated; 221 pair relationships retained and 9 active incidents after the trace-boundary safeguard.

## Documentation updated

- `docs/architecture/event-correlation-architecture.md` and Stage 4 interactions/overview.
- Correlation strategy, candidate generation, evidence/scoring, lifecycle, SQLite schema, API/CLI, and evaluation specifications.
- ADR-012 through ADR-015, design decisions, test strategy, README, known issues, and milestone tracker.

## Known limitations

- Scores are heuristic and not calibrated; association does not establish causality.
- Trace incompleteness is a dataset observation, not proof without expected span manifests.
- Distant similar messages may not be paired unless Stage 3 pattern evidence explicitly names peers.
- Dense candidate sets above the ceiling are rejected; local SQLite is single-writer.
- Every run reevaluates all successful processed events; retention and a network REST service are not provided.
- Synthetic precision/recall reflects only deliberately labeled straightforward cases.

## Recommended next improvement

Before a subsequent milestone, collect representative labeled incident and non-incident telemetry, tune the conservative grouping thresholds against it, and decide retention and multi-writer requirements. Stage 5 is not started; explicit authorization is required.
