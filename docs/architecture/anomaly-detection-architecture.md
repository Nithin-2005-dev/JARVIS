# Anomaly Detection Architecture

The detectors operate on per-service, epoch-aligned UTC window features from Stage 3 processed events. They use only strictly earlier windows for the target window. Defaults are a 300-second window, 100-window rolling lookback, 4-window statistical baseline minimum, 12-window Isolation Forest minimum, and deterministic random seed 17. These values are configurable with `IntelligenceConfig` or the CLI JSON configuration.

## Statistical detector

For each available numeric feature `x`, the baseline stores the prior-window arithmetic mean `μ`, population standard deviation `σ`, and sample count. The raw deviation is `abs(x - μ) / σ`. A score at or above 3.0 emits a finding. If `σ = 0`, an unchanged value scores 0 and any changed value receives the explicit sentinel `threshold + 1`; the finding identifies this zero-variance comparison. Missing observations are skipped rather than imputed. The score is not a probability.

## Isolation Forest detector

The second detector is a seeded, standard-library implementation of Isolation Forest. Each target vector is scored against up to 64 strictly prior service windows using 48 random isolation trees. The implementation chooses a random feature and a random split between its observed minimum and maximum, recursively partitioning until a leaf or `ceil(log2(sample_size))`. It normalizes mean path length using the expected unsuccessful binary-search path length and uses the resulting isolation score. A configured heuristic threshold of 0.62 emits an anomaly finding. Scores are not probabilities. No z-score is combined with the forest score.

Training features are the numeric window vector: event count, error rate, critical count, warning count, mean interarrival seconds, and explicit latency mean when available. A feature missing in any training row or target row is omitted for that target model; no value is manufactured. Isolation Forest does not require scaling for axis-aligned random partitions because positive affine rescaling preserves split ordering. The seed is derived from configured seed, service, target window, and config version. Persisted model artifacts contain sampled trees, feature names, seed, and training window IDs.

The persisted feature row also retains normalized event-type counts, observed severity counts/distribution, exact normalized signature counts, and resource-identifier counts read only from supplied metadata (`resource_id`, `resource_ids`, `resources`, database/server/host/API/network keys). Event types are lower-cased for feature counting, severity labels are upper-cased, and service IDs are trimmed. A missing severity makes the error-rate feature absent for that window; unknown severity remains explicit in the distribution.

## Finding semantics

Each detector result retains its own detector name/version, feature or multivariate vector, observed value, expected prior history, raw score, evidence event references, limitations, and status (`heuristic_anomaly_signal`, `no_anomaly_flag`, or `insufficient_data`). Detector disagreement is preserved. No shared score is invented. Cold starts return no score. The engine does not claim an incident or a cause.

The first available data windows will commonly be insufficient for one or both detectors. Statistical and ML minimum history differ intentionally. A missing latency field remains absent; the statistical detector skips latency, and the forest excludes it from the target vector if it cannot be formed consistently.

## Current limits

Time-of-day/day-of-week baselines are not enabled. Event frequency is measured for windows that contain source events; the batch input has no explicit service coverage interval from which to synthesize empty windows safely. Event volume drops in silent periods therefore cannot be detected without such a coverage contract. Severity/event-type distributions are stored as baseline context; statistical alerts currently evaluate numeric features only. Thresholds are uncalibrated engineering settings.
