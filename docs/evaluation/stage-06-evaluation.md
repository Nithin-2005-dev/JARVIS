# Stage 6 Evaluation

Run `python3 -m payflow_simulator.dependency_graph.evaluate --output data/evaluation/stage6_dependency_metrics.json --dataset-dir data/evaluation`.

The fixture has nine deterministic scenarios over the five configured services: database, payment, notification, and authentication failures; a depth-bounded database failure; an unknown external-service root for which the correct result is a structured error; an unregistered dependency target/type that must be retained and reported; a duplicate-edge collapse check; and a cycle-safety check. Manually specified expected directly and indirectly impacted service sets are in `data/evaluation/stage6_dependency_ground_truth.json`; graph/scenarios are in `stage6_dependency_scenarios.json`.

Denominators: direct and indirect scenario accuracy use five known-root scenarios; service-level precision/recall use the expected impacted-service occurrence counts (five direct and two indirect); path validity checks every returned impacted service's path starts at the root, ends at that service, and each step reverses an actual configured edge. Two scenarios check cannot-establish/unresolved behavior, and two evaluate duplicate/cycle safeguards. Config versioning, incident integration, and repeated scoring are also covered by unit/integration tests, not statistical observations.

Latest recorded run: direct and indirect scenario set accuracy 5/5 each; direct service precision/recall 5/5; indirect service precision/recall 2/2; path validity 5/5; uncertainty scenarios 2/2; duplicate/cycle structural checks 2/2. Evaluator time was 0.002435 seconds for this small in-memory fixture. These values describe implementation contract checks only, not production impact prediction.

Results are deterministic contract checks, not real-world accuracy estimates. The graph is a small handcrafted topology derived from simulator behavior; no production topology or outage history was used.
