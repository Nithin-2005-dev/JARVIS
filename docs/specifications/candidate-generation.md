# Candidate generation algorithms

1. Sort processed records by event timestamp: O(n log n).
2. Index non-empty trace IDs and extracted resource identifiers; exact bucket joins generate pairs only within a matching key.
3. Sweep timestamps while retaining only failure-classified events inside the configured time window. Active indexes are keyed by failure category and service dependency, so unrelated informational events are not compared.
4. Reuse explicit Stage 3 pattern evidence IDs. Compare normalized message signatures only for cross-service, time-near failure candidates.
5. Deduplicate candidate pairs, attach the strategies that made each pair eligible, and reject work above `max_candidates` (default 250,000).

Expected sparse cost is O(n log n + k), with O(n + k) memory; `k` is the emitted candidate count. If many events share one trace/resource or occupy one dense failure window, `k` can be quadratic because the relationships themselves are dense. The configured ceiling bounds memory and stops the correlation run before persistence. A rejected dense run does not replace prior stored edges/incidents.

The algorithm intentionally does not compare every event pair. It also intentionally restricts approximate message similarity to time-near failure candidates: this can miss a repeated signature far apart in time unless Stage 3 pattern output explicitly links the events. This is a documented precision/performance trade-off.
