# Event schema v0.3

Each JSONL row has exactly the following keys:

| Key | Type | Contract |
|---|---|---|
| `event_id` | string | UUID; unique within generated stream |
| `timestamp` | string | ISO-8601 with timezone, emitted in UTC with `Z` |
| `service` | string | Non-empty producer identifier |
| `event_type` | string | Supported type listed below |
| `severity` | string | `INFO`, `WARNING`, `ERROR`, or `CRITICAL` |
| `message` | string | Human-readable summary |
| `source` | string | Origin; currently `simulator` |
| `trace_id` | string | UUID shared by one request |
| `metadata` | object | Scenario data, including payment ID and scenario |

Types: `request_received`, `authenticated`, `payment_created`, `db_query`, `db_pool_exhausted`, `payment_processed`, `downstream_failure`, `notification_sent`, `request_completed`, `request_failed`, `service_started`, `service_stopped`, `service_restarted`, `health_check`, `security_alert`.

The canonical v0.3 representation remains backward-compatible with Stage 1's nine top-level keys. Stage 3 additively extends the `event_type` enum with lifecycle and security signal names for classification. Ingestion normalizes UUID strings to canonical lowercase form, timestamps to UTC `Z`, severity aliases to the enum, service identifiers to lowercase kebab case, and event type spacing/hyphens to lowercase underscores. `source` and metadata remain preserved.

Stage 4 does not change this source-event schema. Correlation evidence and incident data are stored in separate SQLite tables. It reads the Stage 3 processed envelope (`original_event`, `processing_timestamp`, `classification`, `temporal`, and `patterns`) and preserves event-time separately from processing time.

`validate_event` rejects missing or extra keys, empty required strings, malformed UUIDs/timestamps, unsupported enum values, and non-object metadata. Metadata contents are not otherwise constrained.
