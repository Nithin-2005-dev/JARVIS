# Milestone 05 — Root Cause Analysis Engine

## Features implemented

- Incident-scoped candidate generation from abnormal processed events, including database, network, infrastructure, and resource-exhaustion signals.
- Evidence collection from event timestamps, failure categories, normalized resource metadata, configured service dependencies, Stage 3 patterns, and Stage 4 edge evidence.
- Distinct observed, correlated, inferred, contradictory, and missing evidence labels.
- Configurable deterministic heuristic scores, candidate ranks, alternative hypotheses, evidence limitations, and inconclusive/competing outcomes.
- JSON report snapshots, SQLite persistence, history, candidate evidence access, CLI, and Python APIs.
- Reproducible synthetic scenarios and held-out labels with top-1, top-k, inconclusive, false-assertion, and basic throughput measurements.

## Architecture decisions

RCA reads the existing incident/event/edge records and writes separate SQLite tables; source event payloads and Stage 4 data are preserved. Fingerprint-derived investigation IDs make retries idempotent and preserve report snapshots. The engine refuses to call any candidate confirmed because there is no independent verification source. A shared resource, timestamp precedence, or Stage 4 edge is never treated as proof of causation.

Scoring is a configurable heuristic, not a probability. Candidate and support thresholds make weak-signal cases inconclusive and close cases competing. Dependencies are configured inference inputs, not verified topology.

## Files added/updated

Implementation: `payflow_simulator/rca/{__init__,config,engine,storage,evaluate}.py`, `payflow_simulator/rca_cli.py`, and `tests/test_rca.py`.

Evaluation artifacts: `data/evaluation/stage5_synthetic_events.jsonl`, `stage5_ground_truth.json`, and `stage5_rca_metrics.json`.

Documentation: RCA architecture, scoring/evidence specification, API/CLI, evaluation methodology, ADR-016, Stage 5 progress tracker, README, testing strategy, and known issues.

## Verification and evaluation

`python3 -m unittest discover -s tests -v` — **62 tests passed**, 0 failures/errors in 5.727 seconds, including all Stage 1–4 regression coverage and nine RCA tests. `python3 -m payflow_simulator.rca_cli --help`, `python3 -m compileall -q payflow_simulator/rca payflow_simulator/rca_cli.py`, and `git diff --check` completed successfully. A first focused test run exposed an uncommitted SQLite setup fixture; the test fixture was corrected before final verification.

Synthetic results from the checked-in fixture: top-1 accuracy 1.0 (5/5 labeled groups), top-3 candidate recall 1.0 (5/5), inconclusive rate 1/6 (0.1667), false root cause assertion rate 0/6 (0.0). The final local in-memory evaluation of 15 observations took 0.001357 seconds (11,053.07 events/s); timing is host-dependent, very small, includes only in-memory evaluation, and excludes SQLite persistence. No memory measurement was collected.

## Known limitations

- No metrics, span store, health telemetry, or independent cause verifier exists; these appear as gaps.
- Dependency mapping defaults are examples and must be verified; incorrect configuration can distort plausibility.
- Candidate signal strengths and reliability weights are hand-authored and not calibrated.
- Similar event text is not analyzed as causal proof; Stage 3 patterns remain recurrence evidence.
- Resource comparisons are quadratic within a single incident in the current implementation.
- SQLite is local single-host persistence; there is no retention or distributed investigation worker.
- Synthetic scenarios are small and designed around the current rules; they do not prove field accuracy.

## Next recommended work

After approval, evaluate against representative labeled incidents and add independently sourced metrics/traces and topology validation. Do not proceed to Stage 6 until explicitly authorized.
