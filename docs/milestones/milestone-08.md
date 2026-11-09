# Milestone 08 — Intelligent Recommendations Engine

## Features implemented

- Added validated recommendation, configuration, and responder feedback records.
- Added versioned rule catalog for database pool, authentication, notification, application errors, RCA candidate investigation, Stage 7 detector disagreement, Stage 6 potential impact verification, recurrence monitoring, and a narrowly gated database-pool admission-control mitigation suggestion.
- Added rule evidence references, score breakdowns, categorical confidence, risk/precondition fields, implementation, verification, and rollback guidance.
- Added read-only integration with Stage 3 processed events, Stage 4 incident membership, Stage 5 RCA snapshots, Stage 6 blast-radius analyses, and Stage 7 findings.
- Added deterministic generation/run IDs, SQLite snapshots, status history, feedback, history and CLI.
- Added a 15-case deterministic synthetic evaluation, including positive and negative high-risk prerequisite gates.

## Architecture decisions

- A separate `recommendations` package preserves Stage 1–7 semantics and keeps original records unchanged.
- SQLite is reused to preserve local deployment simplicity and transaction patterns.
- Rules require evidence and include excluded conditions; the engine never executes suggested operations.
- Recommendation IDs are derived from run/rule/scenario/evidence; immutable run snapshots are distinct from current lifecycle state.
- Investigations and diagnostics sort before mitigation/recovery. A guarded admission-control suggestion requires two explicit pool-saturation events and remains contingent on current metrics and approval.
- Heuristic scores and confidence labels are not success probabilities.

## Files

Added `payflow_simulator/recommendations/{__init__,models,rules,ranking,engine,storage,evaluation,cli}.py`, `tests/test_recommendations.py`, `data/evaluation/stage8_recommendation_metrics.json`, and Stage 8 docs in architecture, API, evaluation, milestone, and troubleshooting sections. README, test strategy, and progress tracker are updated.

## Verification

- `python3 -m unittest discover -s tests -v` — 104 tests passed, 0 failures/errors (8.782 seconds), including Stage 1–7 regression tests and 12 Stage 8 tests.
- `python3 -m compileall -q payflow_simulator tests` — passed.
- `git diff --check` — passed.
- Temporary full CLI pipeline: 13 simulator events, 13 accepted, 13 processed, two incidents; the selected database-pool incident had competing RCA hypotheses. Graph validation was valid, Stage 7 emitted 10 findings, Stage 8 produced 9 incident recommendations and 2 service recommendations. Incident recommendation rules included database diagnostics, service diagnostics, RCA candidate diagnostics, and potential blast-radius verification. Generation/list/show/update/feedback/history CLI commands completed; one status history transition and one feedback record were retrieved.
- Synthetic recommendation conformance: 15/15 expected outcomes; evidence traceability 13/13; verification 13/13; priority/risk checks 13/13; investigation-before-mitigation ordering 1/1; high-risk classification/prerequisites 1/1; uncertainty 4/4; idempotency 1/1; duplicate rate 0/1; lifecycle 1/1; feedback 1/1; unsupported recommendations 0/13; inappropriate mitigation 0/1.
- Local single-run microbenchmark: 5,000 supplied processed event records (~1.49 MB by Python string representation) scanned and fingerprinted in 0.037553 s, approximately 133,146 events/s, with one recommendation. The run used a temporary SQLite DB on the current development environment and is not a production throughput claim.

Exact verification invocations: `python3 -m unittest discover -s tests -v`; `python3 -m compileall -q payflow_simulator tests`; `git diff --check`; `python3 -m payflow_simulator.recommendations.evaluation --output data/evaluation/stage8_recommendation_metrics.json`; and the Stage 1–8 CLI pipeline described above using temporary JSONL/SQLite paths.

## Limitations and next improvements

The rules do not query current metrics, the high-risk mitigation is a human-reviewed suggestion rather than an operation, and criticality mapping is PayFlow-specific. Add rules only with evidence-backed fixtures and independently reviewed operational procedures. Stage 9 is not started.
