# Service specifications

| Service ID | Responsibility represented | Events |
|---|---|---|
| `api-gateway` | Accept request and report response | `request_received`, `request_completed`, `request_failed` |
| `authentication-service` | Authenticate merchant | `authenticated` |
| `payment-service` | Create/authorize payment | `payment_created`, `payment_processed`, `request_failed` |
| `database-service` | Persist or report pool exhaustion | `db_query`, `db_pool_exhausted` |
| `notification-service` | Send receipt or report timeout | `notification_sent`, `downstream_failure` |

Behavior is emitted by the central simulator; separate service modules and processes are not implemented.

The event contract additionally permits `service_started`, `service_stopped`, `service_restarted`, `health_check`, and `security_alert` records so external producers can express lifecycle and security signals for Stage 3 classification. The Stage 1 simulator does not emit these new types.
