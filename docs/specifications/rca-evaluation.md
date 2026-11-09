# RCA synthetic evaluation methodology

Run `python3 -m payflow_simulator.rca.evaluate --output data/evaluation/stage5_rca_metrics.json --dataset-dir data/evaluation`.

The deterministic fixture has six incident groups and 15 processed observations: five groups have one or more manually labeled initiating event IDs; one group has no defensible known cause and should be inconclusive. Cases cover database pool exhaustion and cascade, network initiation, resource exhaustion, simultaneous alternatives, missing/weak signals, and a misleading earliest generic error. Ground truth is written separately from JSONL observations and never passed to `RCAEngine`.

- Top-1 accuracy is the fraction of labeled scenarios where the first ranked candidate is in the labeled initiator set.
- Top-k candidate recall is the fraction of labeled scenarios where any known initiator appears in the first k candidates.
- Inconclusive rate is inconclusive reports divided by all scenarios.
- False root cause assertion rate counts a leading answer on an unlabeled no-answer scenario, an inconclusive labeled scenario, or a leading candidate outside the labeled set, divided by all scenarios.

The current fixture yields top-1 1.0 (5/5), top-3 recall 1.0 (5/5), inconclusive 1/6 (0.1667), and false assertion 0/6 (0.0). These values are fixture-specific, tiny-sample measurements and do not estimate real-world performance, calibration, or causal validity. The evaluator reports wall-clock throughput for 15 in-memory events; it is not a storage or production benchmark. Memory is not measured.
