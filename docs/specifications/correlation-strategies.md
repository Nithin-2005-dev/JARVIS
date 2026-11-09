# Correlation strategy specification

All strategies are independently recorded as `CorrelationEvidence` on an event pair. Event time is used for windows; the processing timestamp remains untouched. Default window is 60 seconds. Missing or empty trace identifiers are ignored for trace matching and counted in diagnostics.

| Strategy | Rule | Evidence | Can group alone? |
|---|---|---|---|
| Trace | Equal non-empty trace ID | Trace ID, event IDs, evaluation time | Yes, subject to score threshold |
| Shared resource | Exact normalized identifier in configured metadata keys | Exact `key:value` identifiers | Yes, subject to score threshold |
| Temporal | Both events have failure categories in common and are within window | Shared categories, window, time delta | No |
| Dependency | Services appear in configured dependency registry and fall within window | Service pair and registry match | No |
| Pattern | Stage 3 pattern explicitly names peer, or cross-service normalized signatures exceed threshold in the time window | Similarity, threshold, Stage 3 signals | No |
| Cross-service | Cross-service failure candidates supported by dependency or resource and within window | Service names and supporting signal | No |

The default dependency registry in `CorrelationConfig` describes upstream-to-downstream service links. It is bidirectionally consulted for candidate eligibility but preserves service identities in evidence. A dependency is not itself an incident assertion. Events with distinct non-empty trace IDs are not grouped through dependency/time evidence alone; a shared resource is required to bridge those trace boundaries.

Resource extraction walks nested metadata and matches configured keys case-insensitively. Values are normalized to lowercase strings and recorded exactly as `key:value`. The source metadata is never changed. Producers should use stable resource IDs; free-form hostnames can over-correlate.

Trace diagnostics flag a trace with only one observed service/event and spans exceeding `max_lateness_seconds`. Events without trace IDs are listed in a missing-ID diagnostic. These describe the observed dataset; without an expected span manifest they cannot prove trace incompleteness.

Stage 3 patterns are reused only when their evidence IDs are available. Similar messages remain weak evidence. Similarity does not establish a shared incident or a common cause.
