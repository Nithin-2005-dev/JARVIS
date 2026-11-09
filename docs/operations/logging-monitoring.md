# Logging and Monitoring

The HTTP API emits request logs with UTC timestamp, level, request ID, method, path, status, duration, and authenticated role. Demo/production configure JSON formatting. Authentication and authorization lifecycle events are recorded in a local SQLite audit table; passwords, cookies, and tokens are not logged. The API returns `X-Request-ID` and `X-Response-Time-Ms` headers.

`/api/v1/health/live` reports process liveness. `/api/v1/health/ready` performs a database readiness check; the generic health route remains minimal. Admin-only `/api/v1/metrics` exposes in-process request/error counts and latency summaries. These counters reset at process restart and are not a metrics backend. Ingestion and processing retain their existing stage logs; centralized cross-stage metrics/export are not implemented. Do not expose admin metrics publicly.
