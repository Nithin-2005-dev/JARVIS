# Milestone 07 — Advanced AI Intelligence Engine

## Implementation

Added the independent `payflow_simulator.intelligence` package. It reads Stage 3 processed events without editing them; extracts normalized UTC service-window features; builds strictly-prior, configurable rolling baselines; runs a statistical mean/std detector and seeded standard-library Isolation Forest separately; summarizes temporal changes and late/invalid times; mines exact/approximate event signatures and recurring Stage 4 incident structures; and contextualizes anomalous service windows against Stage 6 graph paths. Stage 4/5/6 IDs are linked through matching incident-member event IDs only. No intelligence finding creates an incident, changes RCA, or confirms cause.

The CLI and Python API persist fingerprints, feature windows, baseline snapshots, detector findings, forest tree artifacts, evaluations, graph version, configuration, and history in additive SQLite tables. A repeated run for identical processed events/config/graph reuses the same immutable snapshot.

## Important decisions

- No new dependencies: the inspected environment lacks scikit-learn, and the repository has no dependency manifest. A small seeded Isolation Forest implementation is used as a second genuinely distinct approach, and evaluated separately.
- Baseline targets never train themselves; rolling lookback is capped and model seeds are derived deterministically.
- Raw detector scores are not probabilities and are not combined across detectors.
- Cross-service outputs group signals by service/window, join graph-reachable pairs within a configurable lag, and cap output at 500 by default after an initial all-pairs prototype produced excessive duplicate results.
- Time-of-day/day-of-week baselines and synthetic empty windows are not implemented. No service coverage interval exists in the event contract.

## Final verification

Recorded after implementation:

- Stage 7 focused suite: 16 test cases passed as part of the final full suite.
- Full Stage 1–7 suite: 92 tests passed, 0 failures/errors in 6.350 seconds.
- Evaluation fixture: 2,432 events, 241 service/window rows, 27 positive and 94 negative evaluation service/windows, time-ordered indices 0–19/20–39, no-future-data assertion passed.
- Statistical: TP 18, FP 0, FN 9, TN 94; precision 1.000, recall 0.667, F1 0.800, FPR 0/94.
- Isolation Forest: TP 23, FP 39, FN 4, TN 55; precision 0.371, recall 0.852, F1 0.517, FPR 39/94.
- Exact recurring signature: precision 1/9, recall 1/1. Labeled cross-service and dependency-precedence links found 4/4; 393 contextual relationships were emitted, with no precision claim because the fixture does not label every possible relationship.
- Baseline coverage 120/121 evaluation windows; 25/241 total windows insufficient; two malformed/missing timestamps explicit.
- Evaluation runtime 0.314690 seconds and scenario breakdown in `docs/evaluation/stage-07-evaluation.md` and `data/evaluation/stage7_intelligence_metrics.json`.

### End-to-end verification

Temporary SQLite pipeline using Stage 1 seed 42: 63 generated/accepted, 63 processed, 0 rejected/duplicates/processing failures, 9 incidents, 9 RCA snapshots, Stage 6 graph valid, and one incident blast-radius scenario. Stage 7 stored a run over 63 events/5 service windows with 11 findings, 10 insufficient-data findings, and 10 findings linked to existing incident/RCA/blast-radius context. All 63 explicit finding event IDs resolved to simulator event IDs. Repeated run ID, baseline output, and detector inference were deterministic. The Stage 7 CLI `analyze` returned exit 0 and the same run ID. The full local pipeline plus replay/CLI checks took 1.4694 seconds in this run.

The temporary-database `evaluate` CLI also exited 0, wrote all three expected evaluation artifacts, returned 12 scenarios, and persisted one evaluation record.

The ML and pattern precision results are deliberately reported as measured, including poor performance. Synthetic results are not production quality claims.

## Known issues and next improvements

See `docs/troubleshooting/known-issues.md`. Before production use, obtain representative labeled incidents, set a service coverage contract, validate dependency topology and anomaly labels, calibrate decision thresholds, benchmark artifact growth, and compare the local Isolation Forest implementation against a maintained library in an environment with dependency management. No Stage 8 work is included.
