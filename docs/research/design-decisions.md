# Design decisions log

| Decision | Rationale | Consequence |
|---|---|---|
| Fixed default start instant | Repeatable sample data | Default timeline is historical |
| Trace/payment IDs on events | Simple causal grouping | Metadata is flexible rather than normalized |
| Pool fault on first request only | Shows failure and recovery | Not sustained saturation |
| Queue notification after timeout | Payment authorization remains independent | No retry event is generated |
| Simulated producers | Compact first milestone | Does not test inter-process communication |

No failed implementation approach was needed. Kafka, Kubernetes, and web frameworks were deferred as outside this milestone's scope.
