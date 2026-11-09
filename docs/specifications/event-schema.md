# Event schema v0.1

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

Types: `request_received`, `authenticated`, `payment_created`, `db_query`, `db_pool_exhausted`, `payment_processed`, `downstream_failure`, `notification_sent`, `request_completed`, `request_failed`.

`validate_event` rejects missing or extra keys, empty required strings, malformed UUIDs/timestamps, unsupported enum values, and non-object metadata. Metadata fields are not otherwise constrained in v0.1.
