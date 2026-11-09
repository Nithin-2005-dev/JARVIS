# Test Strategy

Run the complete regression suite with `python3 -m unittest discover -s tests -v`. It covers Stages 1–7; do not weaken earlier tests to accommodate a new stage.

## Stage 7 coverage

`tests/test_intelligence.py` verifies feature calculations and provenance, missing latency/resource data, UTC and invalid timestamps, fixed and rolling baselines, strict prior-window training, cold starts, zero variance, seeded Isolation Forest repeatability, late-event summaries, exact and approximate signatures, bounded pattern comparisons, cross-service dependency paths and unrelated services, competing detector outputs, Stage 4/5/6 evidence links, transaction rollback, idempotent historical snapshots, and synthetic time-ordered evaluation.

Run the deterministic evaluation with `python3 -m payflow_simulator.intelligence.evaluation --output-dir data/evaluation`. The fixture includes 12 required scenario categories and records separate statistical/ML metrics, denominator counts, detection delay, baseline coverage, insufficient-data rate, recurring-pattern metrics, detector disagreement, and future-data leakage verification. The evaluation is a small handcrafted behavior check, not a production quality claim.

Compile and whitespace checks:

```bash
python3 -m compileall -q payflow_simulator
git diff --check
```

Stage 7 integration verification uses a temporary SQLite database for simulator -> ingestion -> processing -> correlation -> RCA -> Stage 6 graph -> intelligence. Intelligence persists to additive tables and leaves earlier event, incident, RCA, and blast-radius records unchanged.
