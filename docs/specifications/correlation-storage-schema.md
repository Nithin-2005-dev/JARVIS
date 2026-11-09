# Correlation storage schema

The Stage 4 migration is additive and runs when `SQLiteCorrelationStore` opens the existing Stage 2/3 database.

| Table | Key fields | Purpose |
|---|---|---|
| `correlation_runs` | `run_id` primary key, created timestamp, status, details, metrics | Idempotent run identity, configuration and completed/failed result status |
| `correlation_edges` | source ID, target ID, strategy composite primary key; run ID, evidence JSON, score | Current evaluated relationships and strategy evidence |
| `trace_diagnostics` | run ID, diagnostic key | Incomplete/inconsistent observations and missing trace IDs |
| `incidents` | incident ID primary key, status, severity, stable anchor, merged target | Current and retained incident identity/lifecycle |
| `incident_members` | event ID primary key, incident ID foreign key | Current unique event membership |
| `incident_history` | append-only history ID, incident ID, action, detail, recorded time | Creation, additions, merges, splits, resolutions |
| `correlation_metrics` | run ID primary key, JSON metrics, missing-trace count | Current measured run counters and performance |

Event payloads remain in existing `events` and `processed_events`; Stage 4 does not rewrite them. Correlation updates use one immediate SQLite transaction for run details, edges, diagnostics, memberships, incident rows and history. A failed transaction is rolled back and then recorded with status `failed`; rerunning the same deterministic input/config ID can transition it to `completed`. The metrics summary is upserted immediately after the run transaction because total timings are finalized after reconciliation; it is stored in both `correlation_metrics` and the `correlation_runs.metrics` field. WAL and a 30-second busy timeout match Stage 3 local storage behavior. A new empty database can still open and report zero processed records; `run` then records an empty idempotent correlation result.
