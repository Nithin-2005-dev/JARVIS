# Milestone 06 — Service Dependency Graph and Blast Radius

## Architecture delivered

The new `payflow_simulator.dependency_graph` package contains service/dependency definitions, graph builder/validator, SQLite graph store, reverse-edge blast-radius analyzer, Stage 4/5 integration, and deterministic evaluator. The standalone CLI is `payflow_simulator.dependency_cli`.

Direction is fixed throughout: `A -> B` means A depends on B. Blast radius starts at failed B and traverses reverse edges to its dependents. BFS provides unique shortest depths; bounded simple paths explain direct and indirect membership. Tarjan SCC findings report cycles; visited-node and per-path guards keep analysis finite.

Scores use configurable service criticality × path importance × path verification confidence × depth decay × dependent fanout. They are heuristic structural impact scores, not failure probabilities. Reports separate structural impact, observed incident events, observed failure signals, and confirmation (always false without independent health verification).

## PayFlow graph

- API Gateway depends on Authentication Service and Payment Service.
- Payment Service depends on Database Service.
- Notification Service consumes authorized payment work from Payment Service, represented with a lower-importance simulated message-queue edge. The simulator shows notification retries do not block payment authorization.

The initial graph also reuses Stage 3 service metadata. Criticality and score mappings are configuration values.

## Stage 4/5 integration

Incident analysis reads Stage 4 incident membership and processed events plus the latest persisted Stage 5 report. A leading hypothesis produces one explicitly hypothetical scenario. Competing and inconclusive reports generate a separate scenario for every candidate service, preserve the RCA ID/status, and leave `confirmed_root_cause` false. Missing incident/RCA/service context returns structured errors. Explicit service analysis remains available.

## Files created/modified

Created `payflow_simulator/dependency_graph/{__init__,models,service_registry,graph_builder,graph_store,blast_radius,evaluate}.py`, `payflow_simulator/dependency_cli.py`, `tests/test_dependency_graph.py`; Stage 6 evaluation artifacts in `data/evaluation/`; and API, architecture, evaluation, test strategy, and milestone docs. Updated README, ADRs, system/component architecture, service specifications, engineering testing strategy, known issues, and progress tracker.

## Evaluation and verification

The deterministic fixture contains five known-root queries (database, payment, notification, authentication, and depth-bounded database), an unknown-service root with structured-error expected behavior, and an unknown dependency type/target that must remain visible in validation. On the final run, direct and indirect impacted sets were correct in 5/5 queries each; direct service precision/recall were 5/5 and indirect precision/recall 2/2. Returned impact paths were valid in 5/5 queries. Both uncertainty cases and both duplicate/cycle structural checks passed. This is a small hand-labeled contract fixture, not a production accuracy estimate.

### Final verification results

- `python3 -m unittest tests.test_dependency_graph -v` — 14 passed, 0 failures/errors (0.464 s).
- `python3 -m unittest discover -s tests -v` — 76 passed, 0 failures/errors (6.623 s), including Stage 1–5 regression. Existing tests intentionally log simulated rollback/error cases while passing.
- `python3 -m compileall -q payflow_simulator` and `git diff --check` — passed.
- `python3 -m payflow_simulator.dependency_graph.evaluate --output data/evaluation/stage6_dependency_metrics.json --dataset-dir data/evaluation` — nine scenarios; 5/5 direct and indirect scenario sets, 5/5 direct service expected items, 2/2 indirect expected items, 5/5 path checks, 2/2 uncertainty checks, and 2/2 structural checks passed. Evaluator runtime was 0.002435 s on this run.
- Temporary database end-to-end run with seed 42: 63 events generated, 63 accepted, 0 rejected/duplicates, 63 processed, 0 processing failures, 9 incidents, 9 RCA snapshots; incident blast-radius integration returned one scenario, graph validation passed, and repeat analysis produced a stable ID. Total pipeline time was 0.5156 s on this run.
- CLI smoke checks (`validate`, `blast-radius --service database-service --max-depth 3`, `history`) all exited 0 against a temporary database. Graph validation returned valid with no findings.
- Final graph version: `96c224a7fd61dc8be6c351ca9300e115a3c24839dab4655798e4fa29c300db31`.

Timing figures are single local measurements on small fixtures and should not be treated as capacity guarantees.

## Known limitations

- The graph is configured, not discovered or continuously reconciled.
- The queue is simulated and external provider nodes are omitted.
- Heuristic impact scores are not calibrated probabilities.
- Dense simple-path alternatives are bounded by a cap.
- RCA integration uses the latest persisted RCA snapshot and does not independently verify services.
- SQLite history is local and has no automatic retention.

## Recommended next steps

Validate the configured graph against deployment ownership and runtime traces, then test against representative incident/service-impact labels. Keep Stage 7 out of scope until authorized.
