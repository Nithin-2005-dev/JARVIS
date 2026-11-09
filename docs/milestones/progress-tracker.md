# Milestone progress tracker

## Stage 1

- [x] Inspect existing files.
- [x] Implement typed events and schema validation.
- [x] Implement normal and two failure scenarios.
- [x] Implement deterministic CLI and JSONL writer.
- [x] Generate sample dataset.
- [x] Add and run unit tests.
- [x] Create required documentation.
- [x] Stage 2 — Event Ingestion Engine implemented; verification below.

## Verification record

- `python3 -m payflow_simulator.cli --scenario all --seed 42 --payments 3 --output data/sample_events.jsonl` — completed; wrote 63 events.
- `python3 -m unittest discover -s tests -v` — completed; 6 tests passed, 0 failures/errors.
- The generated JSONL is included at `data/sample_events.jsonl` (21 events per scenario; 9 traces total).

## Stage 2

- [x] Inspect Stage 1 models, sample data, tests, and documentation before changes.
- [x] Add JSON/JSONL, CSV, REST, and live source adapters.
- [x] Add validation, normalization, durable deduplication, quarantine, and metrics.
- [x] Add CLI/API, unit and integration coverage, and lifecycle documentation.
- [x] Preserve and verify Stage 1 simulation and sample dataset compatibility.
- [ ] Stage 3 — pending user approval.

### Performance measurement

A 5,000-row (1,840,000-byte) JSONL fixture was ingested into a temporary SQLite database: 5,000 received, 5,000 accepted, 0 rejected, 0 duplicates, 5,000 stored; 0.2981 seconds and 16,771 events/second on this run. This is one local measurement, not a performance guarantee.

### Final Stage 2 verification

- `python3 -m unittest discover -s tests -v` — 18 tests passed, 0 failures/errors (1.671 seconds).
- Stage 1 CLI regenerated 63 events with seed 42 and default arguments; generated sample was byte-identical to `data/sample_events.jsonl` (SHA-256 `4de9e191a1e09b69ddb8809b3cda0a7215dc5d6a351096ed17562a66a0369883`).
- Stage 2 ingestion CLI read `data/sample_events.jsonl`: 63 received, 63 accepted, 0 rejected, 0 duplicates.
- `python3 -m payflow_simulator.ingest_cli --help` — completed and displayed all source and storage options.
