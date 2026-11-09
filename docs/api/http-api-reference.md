# HTTP API reference — v1

All endpoints use `/api/v1`. Collection responses use `{items, total}`; incident listing also returns `page` and `page_size`. Errors include a machine-readable code and human-readable message. The OpenAPI document at `/api/docs` is authoritative for request schema details.

| Method and path | Behavior |
|---|---|
| `GET /health` | API process and selected database path |
| `GET /overview` | Stored counts, latest incidents/findings, configured services; health availability is explicit |
| `GET /incidents` | Paginated records with status, severity, service, search, start/end time, and severity/activity sorting |
| `GET /incidents/{id}` | Incident, events, correlation evidence/history, latest RCA, blast-radius snapshots, findings, recommendations |
| `GET /incidents/{id}/events` | Events and correlation evidence |
| `GET /incidents/{id}/rca` | Latest RCA snapshot or null |
| `GET /incidents/{id}/blast-radius` | Stored hypothetical analyses |
| `GET /incidents/{id}/intelligence` | Related persisted findings |
| `GET /incidents/{id}/recommendations` | Incident recommendations |
| `GET /services` | Configured graph services |
| `GET /services/{id}` | Metadata, edges, incident, analysis, finding, and recommendation context |
| `GET /services/{id}/dependencies` | Incoming/outgoing configured edges and direction semantics |
| `GET /services/{id}/recommendations` | Service recommendations |
| `GET /intelligence/findings` | Bounded finding list; filter by service and finding type |
| `GET /intelligence/findings/{id}` | Finding detail |
| `GET /recommendations` | Bounded recommendations; filter by status/category/priority/risk/service/incident |
| `GET /recommendations/{id}` | Recommendation with status and feedback history |
| `PATCH /recommendations/{id}/status` | Validated Stage 8 status transition; dismissal requires reason |
| `POST /recommendations/{id}/feedback` | Record feedback; no automatic model tuning |
| `GET /history` | Bounded incident, recommendation, intelligence, and blast-radius history |

Status PATCH body: `{"status":"acknowledged|in_progress|completed|dismissed|superseded","reason":"","notes":""}`. Feedback body uses Stage 8 outcome values and bounded evidence/notes fields. The API does not accept arbitrary SQL filters or commands.
