# Classification taxonomy

Classification is configurable, deterministic rule matching. Rules are sorted by `(priority, rule_id)`; every matching rule contributes a category, and duplicate categories are removed while retaining that stable order. Rule predicates (when provided) all must match: event type, severity, service, and message regular expression.

Supported default categories:

| Category | Default signal |
|---|---|
| `infrastructure_failures` | Database pool exhaustion |
| `database_failures` | Error/critical event from database service |
| `network_failures` | Downstream failure event |
| `authentication_failures` | Error/critical event from authentication service |
| `application_errors` | Other error/critical events; fallback for unknown event types |
| `performance_degradation` | Slow/latency/timeout/pool-exhaustion message |
| `service_lifecycle_events` | Start, stop, restart, or health check events |
| `security_related` | Security alert event or configured security message pattern |

Known events with no matching rule are `uncategorized`. Unknown event types set `unknown_event_type: true` and use `application_errors` when no configured rule matches. Stage 2 rejects unsupported types at ingestion, while the processor remains tolerant of unknown type strings in legacy/out-of-band rows already present in its queue. Multiple categories may apply. Classification labels describe event content; they do not establish a causal relationship or root cause.
