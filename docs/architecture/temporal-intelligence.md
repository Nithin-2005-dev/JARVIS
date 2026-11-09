# Temporal Intelligence

Features are grouped by UTC event-time windows. A timezone-aware original timestamp or Stage 3 `temporal.event_timestamp` is required. Missing, malformed, or naive timestamps are listed with their event IDs and excluded from feature aggregation; processing time is never substituted.

The rolling baseline for a target window is built from up to the preceding configured number of service windows. Its target and all later windows are excluded. The evaluator uses windows 0–19 before windows 20–39 and checks every baseline training timestamp is earlier than its target. The retained lookback defaults to 100 windows and cannot be less than the baseline minimum.

Temporal summaries report changes in first/last thirds of the supplied range, error-rate slope, statistical event-count/severity bursts, simultaneous detector windows, and arrival lag where processing timestamps exist. Whole-range trend summaries are retrospective descriptions, not historical predictions. Known incident sequence summaries use persisted Stage 4 member event times, include only detector windows ending no later than the first incident member event, and are labeled retrospective; an earlier anomaly may be unrelated.

Late events use event time during a new batch analysis. The engine recomputes a fingerprinted snapshot when its processed-event inputs change; it does not maintain streaming watermarks or amend prior snapshots. Repeated analysis over unchanged input/config/graph reuses the existing snapshot.

Dependency-neighbor analyses report configured paths, involved service/window timestamps, time deltas, and competing explanations. They remain contextual observations. They do not claim propagation or causality.
