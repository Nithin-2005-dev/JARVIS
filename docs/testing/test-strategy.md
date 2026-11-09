# Stage 6 Test Strategy

Run the complete suite with `python3 -m unittest discover -s tests -v`. `tests/test_dependency_graph.py` covers graph direction, actual PayFlow fault scenarios, max depth/environment, alternate paths and uniqueness, duplicate/unknown/missing/self/cycle/disconnected validation, unknown root, deterministic scoring, version history, repeated persistence, Stage 4 incident membership, Stage 5 competing hypotheses, missing RCA, and synthetic evaluation. The existing Stage 1–5 suites remain unchanged and run in the same command.

Run evaluation with `python3 -m payflow_simulator.dependency_graph.evaluate --output data/evaluation/stage6_dependency_metrics.json --dataset-dir data/evaluation`. The evaluator checks five known-root cases and one expected error. Its small denominators are included in the JSON report and are not predictive quality claims.

CLI validation/graph checks use a temporary SQLite file during verification so a user database is not modified. End-to-end verification runs simulator -> ingestion -> processing -> correlation -> RCA -> dependency incident analysis in a temporary workspace.
