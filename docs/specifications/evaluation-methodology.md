# Stage 4 synthetic evaluation methodology

`python3 -m payflow_simulator.correlation.evaluate --output-dir data/evaluation` generates deterministic UUID5-based processed event rows plus a separate ground-truth mapping. The default fixture has 20 three-event incidents (60 true related pairs) and 20 pairs of simultaneous but isolated error events. It includes shared traces/resources for known groups and intentionally no shared identifiers for unrelated events. Ground-truth labels are never inserted into `processed_events` or passed to `CorrelationEngine`.

Evaluation measures pairwise co-membership, not edge detection: every pair in the same predicted incident is a predicted related pair. Precision = true positive pairs / predicted pairs; recall = true positive pairs / ground-truth related pairs. This penalizes both missed group connections and over-grouping. Dataset construction is deliberately simple and favorable to the configured deterministic rules; it does not represent production class imbalance or ambiguous telemetry.

Performance is measured with `time.perf_counter` around candidate generation, evaluation, and the entire correlation run. Optional peak memory uses Python `tracemalloc` and does not include SQLite/native allocator memory. Reproduce with the CLI; timing and memory vary by host. Performance figures in the Stage 4 report are one local run, not an SLO.
