# Pattern detection rules

Patterns are count-based signals over stored observations in a fixed event-time window. The current event triggers output once a configured threshold is met:

- `repeated_error`: matching failure signature count reaches `repeated_error`.
- `recurring_failure_pattern`: matching failure signature count reaches `recurring_failure`.
- `frequency_spike`: events from the same service in the window reach `frequency_spike`.
- `repeated_across_services`: matching failure signature appears from at least the configured number of distinct services.

Failure signatures use event type, severity, and whitespace-normalized lowercase message. Service identity is included as a separate dimension for service volume and cross-service counts. Each pattern carries count, window, signature, service set, evidence IDs, and an explicit statement that no causal relationship is inferred. Observations are stored only with successful event completion, so a failed attempt does not inflate counts. Explicit replay upserts the event's observation rather than counting it twice.

These are deterministic repetition/frequency indicators, not incident correlation, anomaly ML, or root cause analysis. Thresholds are configurable in JSON.
