# Design decisions log

| Decision | Rationale | Consequence |
|---|---|---|
| Fixed default start instant | Repeatable sample data | Default timeline is historical |
| Trace/payment IDs on events | Simple causal grouping | Metadata is flexible rather than normalized |
| Pool fault on first request only | Shows failure and recovery | Not sustained saturation |
| Queue notification after timeout | Payment authorization remains independent | No retry event is generated |
| Simulated producers | Compact first milestone | Does not test inter-process communication |

No failed implementation approach was needed. Kafka, Kubernetes, and web frameworks were deferred as outside this milestone's scope.

## Stage 2 additions

| Decision | Rationale | Consequence |
|---|---|---|
| Source adapters yield `SourceRecord` | Keep core engine independent from input framing | Every adapter represents parse errors in a common record shape |
| SQLite stores canonical payload with event ID primary key | Persistent local idempotency | First stored payload wins on repeated IDs |
| Commit successful inserts in batches of 500 | Improve throughput and bound pending writes | Abrupt exit can lose current uncommitted batch |
| Quarantine stores decoded payload and provenance | Keep investigation context without blocking good records | Operators need a retention/rotation policy |
| REST adapter issues GET only | Simple pull ingestion contract | Pagination, retries, and acknowledgements are not implemented |

## Stage 3 additions

| Decision | Rationale | Consequence |
|---|---|---|
| Store derived events separately | Preserve source data and make replay safe | Consumers choose source vs processed representation explicitly |
| Use configurable service metadata and conjunctive rules | Keep enrich/classify behavior visible and reviewable | No learned classification or automatic registry discovery |
| Compare input event time to successful max watermark | Simple late/out-of-order semantics for this local queue | No buffering, reordering, retractions, or multi-worker watermark coordination |
| Persist pattern observations by event ID/window | Make counts durable across processing batches and explicit replay idempotent | Exact-message signatures are sensitive to message text variation |
| Count thresholds with evidence capped at 20 IDs | Reproducible lightweight pattern signals with bounded output | Pattern counts are absolute thresholds rather than adaptive baselines |
| Persist claim attempt and stage history | Recover failures without deleting accepted source rows | History/output tables grow until operators apply retention |
