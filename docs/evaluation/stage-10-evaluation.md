# Stage 10 Evaluation

Date: 2026-11-09. These results are local verification on one WSL2 host, not production capacity or security certification.

## Performance methodology and conditions

`python scripts/performance_benchmark.py --events N --warm-requests R` uses deterministic PayFlow normal events and a temporary SQLite database. The harness measures JSONL generation, ingestion, processing, correlation, RCA/blast-radius/recommendations for one persisted incident, intelligence, selected local FastAPI TestClient reads, database/dataset size, and peak RSS where available. One cold request and repeated warm requests are used. The workload is single-process and single-run, not a load test or SLO measurement. Python 3.12.3, a 12-CPU WSL2 host reporting approximately 8.16 GiB RAM, local temporary storage, and the locked Stage 10 Python dependencies were used.

### 1,000 events

| Stage | Runtime | Result |
|---|---:|---|
| JSONL generation | 0.0132 s | 1,000 events; 364,267 bytes |
| Ingestion | 0.0473 s | 1,000 accepted; 0 rejected/duplicates; 21,153 events/s |
| Processing | 2.9526 s | 1,000 processed; 0 failed; 338.9 events/s |
| Correlation | 3.0221 s | 16,139 candidate pairs; 143 incidents; 332 events/s |
| RCA | 0.0105 s | One incident |
| Blast radius | 0.0072 s | One incident |
| Intelligence | 0.1368 s | 11 findings |
| Recommendations | 0.0141 s | One incident |

Peak process RSS was 90,947,584 bytes; SQLite plus WAL was 26,886,144 bytes. There were no measured API request failures. Warm p50/p95: incident list 18.9/34.0 ms; incident detail 11.5/17.7 ms; service graph 69.2/76.9 ms; recommendations 6.0/6.5 ms; overview 10.1/10.7 ms. Each endpoint used one cold and five warm local TestClient calls.

### 10,000 events

The run completed. It generated a 3,642,608-byte dataset, accepted and processed all 10,000 events with no rejects or processing failures, produced 1,429 incidents and 92 intelligence findings. Ingestion: 0.485 s (20,619 events/s); processing: 30.827 s (324 events/s); correlation: 16.581 s (606 events/s, 163,868 candidate pairs, 163,868 accepted relationships). Intelligence took 0.925 s. RCA, blast-radius and recommendation timings for one incident were 0.0083, 0.0056 and 0.0315 s. Peak RSS was 406,859,776 bytes; database plus WAL was 263,532,544 bytes. Warm p50/p95: incident list 178.5/180.5 ms; incident detail 63.8/64.3 ms; service graph 790.7/831.7 ms; recommendations 7.4/8.8 ms; overview 71.8/91.7 ms. Four calls per endpoint (one cold plus three warm) and zero request failures.

The initial 10,000-event run exceeded a 180-second bound while persisting correlation results. Profiling localized repeated whole-edge scans while assembling incident membership. The persistence path now indexes edges by endpoint and computes component support once; correlation history/evidence regression tests and the full suite pass. The completed rerun is the measurement above. This is a behavior-preserving Stage 4 storage optimization; it does not change correlation scoring or grouping semantics.

### 100,000 events

Attempted with a 180-second wall-clock bound. Generation completed in 2.180 s and ingestion in 15.920 s, accepting the 100,000-event input; processing did not complete before the timeout. The process was interrupted during SQLite processing-state commits. No processing throughput, correlation, downstream stage, API, or dataset/database final-size result is claimed for this case. This is the measured capacity boundary for this run, not a maximum-capacity estimate.

## Functional, security, and recovery evaluation

- Backend regression: `python -m pytest -q` — 116 passed in 17.25 s (two upstream deprecation warnings).
- Focused Ruff checks: passed.
- `pip-audit -r requirements-lock.txt`: no known vulnerabilities found.
- Frontend lockfile audit: `npm audit --audit-level=high` — 0 vulnerabilities (run in Linux Node 22 environment).
- Frontend unit tests: 13 passed; TypeScript and ESLint passed in the Linux Node environment. See milestone report for production build/container evidence.
- Playwright: 4/4 browser tests passed against a real seeded API and production-built frontend; includes competing blast-radius scenario, smaller viewport, and API error handling. An existing compatible Chromium executable was used because downloading the pinned browser build was constrained in the local host environment.
- Compose integration: API and frontend healthy; readiness returned 200, unauthenticated protected route returned 401. An isolated backup was integrity-checked and restored to a new path. Row counts matched for events (63), processed events (63), incidents (9), correlation edges (376), RCA investigations (9), blast-radius analyses (21), intelligence findings (11), recommendations (40).
- Seeded end-to-end demo: 63 events processed, 9 incidents, 11 findings. Recommendation count in the full persisted demo database: 40.

These checks do not constitute a penetration test, formal recovery objective, cross-platform portability test, or production SLO. GitHub Actions were authored but not executed by GitHub in this local run; Gitleaks is configured in CI and was not locally run.
