# Milestone progress tracker

## Stage 1

- [x] Inspect existing files.
- [x] Implement typed events and schema validation.
- [x] Implement normal and two failure scenarios.
- [x] Implement deterministic CLI and JSONL writer.
- [x] Generate sample dataset.
- [x] Add and run unit tests.
- [x] Create required documentation.

## Verification record

- `python3 -m payflow_simulator.cli --scenario all --seed 42 --payments 3 --output data/sample_events.jsonl` — completed; wrote 63 events.
- `python3 -m unittest discover -s tests -v` — completed; 6 tests passed, 0 failures/errors.
- The generated JSONL is included at `data/sample_events.jsonl` (21 events per scenario; 9 traces total).

## Stage 2

- [x] Stage 2 — Event Ingestion Engine implemented; verification below.
- [x] Inspect Stage 1 models, sample data, tests, and documentation before changes.
- [x] Add JSON/JSONL, CSV, REST, and live source adapters.
- [x] Add validation, normalization, durable deduplication, quarantine, and metrics.
- [x] Add CLI/API, unit and integration coverage, and lifecycle documentation.
- [x] Preserve and verify Stage 1 simulation and sample dataset compatibility.
- [x] Stage 3 — implemented; verification recorded below.

## Stage 3

- [x] Inspect Stage 1/2 code, database contracts, docs, and regressions.
- [x] Add enrichment, configurable classification, temporal annotations, and event-time patterns.
- [x] Add durable state, history, idempotency, retry, stale claim recovery, and explicit replay.
- [x] Add structured logs, metrics, configuration, CLI, and required documentation.
- [x] Run Stage 1/2 regression and Stage 3 tests.
- [x] Stage 4 — Event Correlation Engine implemented; verification and evaluation recorded below.

## Stage 4

- [x] Inspect existing event schema, Stage 2 ingestion, Stage 3 processed payloads/storage, docs, and regression suite.
- [x] Add indexed temporal, trace, dependency, resource, signature, and cross-service candidate generation with a hard candidate ceiling.
- [x] Add independently scored evidence, heuristic confidence, trace diagnostics, conservative incident grouping, stable IDs, merge/split/re-resolution history, and late-event reevaluation.
- [x] Add additive SQLite persistence, idempotent runs, CLI investigation commands, configuration, deterministic labeled evaluation, and Stage 1–3 regression tests.
- [x] Update architecture, schema, engineering, specifications, decisions, evaluation, known issues, milestone report, and progress tracker.
- [ ] Stage 5 — not started; requires explicit authorization.

### Stage 4 synthetic evaluation and performance

`python3 -m payflow_simulator.correlation.evaluate --output-dir data/evaluation` on the default 100-event fixture: 20 labeled three-event incidents and 20 unrelated simultaneous pairs. Pairwise co-membership: 60 ground-truth related pairs, 60 predicted, 60 true positives, 0 false positives, 0 false negatives; precision 1.000, recall 1.000. This fixture is intentionally controlled and is not a production accuracy estimate. One final local measurement reported 80 candidate pairs, 0.1012 s candidate generation, 0.0969 s relationship evaluation, 0.3138 s total run, 319 events/s, and 586,997 traced peak bytes. Timings vary by host.

### Stage 4 verification

- `python3 -m unittest discover -s tests -v` — 53 tests passed, 0 failures/errors in 6.621 seconds, including Stage 1–3 regression.
- Correlation CLI help displayed run/list/show/events/evidence/history/related/stats commands.
- Evaluation generated `data/evaluation/stage4_events.jsonl` and `data/evaluation/stage4_ground_truth.json` with the measured results above.
- Temporary-database end-to-end sample: 63 ingested, 63 processed, 0 failed, 221 correlation edges and 9 active incidents.
- Empty-database CLI `stats` reports zero processed records and no incidents.

### Performance measurement

A 5,000-row (1,840,000-byte) JSONL fixture was ingested into a temporary SQLite database: 5,000 received, 5,000 accepted, 0 rejected, 0 duplicates, 5,000 stored; 0.2981 seconds and 16,771 events/second on this run. This is one local measurement, not a performance guarantee.

### Final Stage 2 verification

- `python3 -m unittest discover -s tests -v` — 18 tests passed, 0 failures/errors (1.671 seconds).
- Stage 1 CLI regenerated 63 events with seed 42 and default arguments; generated sample was byte-identical to `data/sample_events.jsonl` (SHA-256 `4de9e191a1e09b69ddb8809b3cda0a7215dc5d6a351096ed17562a66a0369883`).
- Stage 2 ingestion CLI read `data/sample_events.jsonl`: 63 received, 63 accepted, 0 rejected, 0 duplicates.
- `python3 -m payflow_simulator.ingest_cli --help` — completed and displayed all source and storage options.

### Stage 3 performance measurement

End-to-end ingestion plus processing benchmarked 5,000 synthetic records in a temporary SQLite database. All 5,000 were accepted and processed, with 0 failures. Processing took 16.7041 seconds at 299.33 events/second; mean per-event latency was 3.267 ms. Stage time totals: input validation 0.8140 s, enrichment 0.0407 s, classification 0.2452 s, temporal 0.3090 s, pattern detection 0.7471 s. The fixture placed events in separate event-time windows to measure baseline pipeline cost without repetition-count growth. This is one local run, not a service-level guarantee.

### Final Stage 3 verification

- `python3 -m unittest discover -s tests -v` — 35 tests passed, 0 failures/errors (2.743 seconds), including Stage 1 and Stage 2 regression coverage.
- End-to-end CLI: Stage 2 ingested the sample dataset (63 accepted); Stage 3 processed 63 with 0 failures; a second normal processing CLI run received 0 and processed 0.
- Stage 3 CLI help and `git diff --check` completed successfully.
