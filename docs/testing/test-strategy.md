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
# Stage 8 recommendation coverage

`tests/test_recommendations.py` verifies event-backed recommendations, guarded high-risk mitigation and ordering, missing high-risk prerequisites, competing/inconclusive RCA behavior, detector disagreement, potential blast-radius wording, insufficient context, deterministic/idempotent snapshots, immutable source events, lifecycle transitions, feedback persistence, and the 15-case synthetic evaluation. The full regression command remains `python3 -m unittest discover -s tests -v`; Stage 8 adds no third-party dependencies.

Final Stage 8 regression: `python3 -m unittest discover -s tests -v` — 104 passed in 8.782 seconds. Compile check and `git diff --check` passed. The end-to-end temporary SQLite CLI pipeline accepted and processed 13/13 simulated events, built two incidents, ran RCA/graph/blast-radius/intelligence, and generated incident-level and service-level recommendations. A 5,000-record local scan measured 0.037553 seconds (single run; see Stage 8 evaluation for conditions and limitations).
