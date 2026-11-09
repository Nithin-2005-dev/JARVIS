# Milestone progress tracker

## Stage 1

- [x] Inspect existing files.
- [x] Implement typed events and schema validation.
- [x] Implement normal and two failure scenarios.
- [x] Implement deterministic CLI and JSONL writer.
- [x] Generate sample dataset.
- [x] Add and run unit tests.
- [x] Create required documentation.
- [ ] Stage 2 — pending user approval.

## Verification record

- `python3 -m payflow_simulator.cli --scenario all --seed 42 --payments 3 --output data/sample_events.jsonl` — completed; wrote 63 events.
- `python3 -m unittest discover -s tests -v` — completed; 6 tests passed, 0 failures/errors.
- The generated JSONL is included at `data/sample_events.jsonl` (21 events per scenario; 9 traces total).
