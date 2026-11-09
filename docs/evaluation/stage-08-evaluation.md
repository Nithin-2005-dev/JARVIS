# Stage 8 synthetic evaluation

Run `python3 -m payflow_simulator.recommendations.evaluation --output data/evaluation/stage8_recommendation_metrics.json` or `python3 -m payflow_simulator.recommendations.cli evaluate`. The fixture catalog is deterministic and uses a temporary SQLite database. It includes database pool exhaustion, auth degradation, notification queue failure, payment errors, competing and inconclusive RCA, detector disagreement, potential blast radius, insufficient context, recurring patterns without incidents, duplicate generation, guarded high-risk mitigation with and without verified prerequisites, contradictory RCA evidence, and no matching rule.

## Results (15 scenarios)

Results are rule/conformance metrics only, not production performance or user-quality metrics:

| Measure | Result | Denominator |
|---|---:|---:|
| Expected scenario outcome/rule | 15/15 (100%) | 15 scenarios |
| Evidence traceability | 13/13 (100%) | 13 scenarios with expected recommendation |
| Verification completeness | 13/13 (100%) | 13 scenarios with expected recommendation |
| Priority/risk gate checks | 13/13 (100%) | 13 scenarios with expected recommendation |
| Investigation before guarded mitigation | 1/1 (100%) | 1 scenario with both types |
| High-risk class and prerequisites | 1/1 (100%) | 1 guarded mitigation |
| Uncertainty preservation | 4/4 (100%) | 4 uncertainty scenarios |
| Idempotent duplicate generation | 1/1 (100%) | 1 repeated-generation scenario |
| Duplicate rate on repeated generation | 0/1 (0%) | 1 repeated-generation scenario |
| Lifecycle transition and audit check | 1/1 (100%) | 1 persisted recommendation path |
| Feedback persistence check | 1/1 (100%) | 1 feedback record |
| Unsupported recommendations | 0/13 (0%) | 13 expected recommendation scenarios |
| Inappropriate mitigation suggestion | 0/1 (0%) | 1 mitigation recommendation |

The high-risk path required two distinct event references, explicit pool size/active connection/wait data, and all three supplied attestations: current saturation confirmed, approved runbook, and payment-owner approval. It ranked after investigation. Single pool-exhaustion evidence or repeated events without those attestations did not produce that mitigation.

The fixtures were authored with the default rule catalog. A 15-case synthetic pass does not measure responder usefulness, real-world false-positive rate, mitigation success, or population-level accuracy. Scores are not calibrated probabilities. The evaluation currently has no external adjudication dataset.

## Local performance check

A one-run local scan used 5,000 supplied processed-event mappings (approximately 1.49 MB by Python string representation) and a temporary SQLite database. Generation, including hashing the input snapshot and storing one recommendation, took 0.037553 seconds (133,146 input events/second). This microbenchmark is a single development-host measurement; it excludes source database loading and makes no production throughput claim.
