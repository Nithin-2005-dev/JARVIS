# Component interactions

Each payment trace shares a trace ID and payment ID in metadata. Events are appended causally with increasing timestamps and seeded sub-8ms jitter. These are generated records, not RPCs.

```mermaid
sequenceDiagram
 participant G as API Gateway
 participant A as Authentication Service
 participant P as Payment Service
 participant D as Database Service
 participant N as Notification Service
 G->>A: request_received / authenticated
 A->>P: payment_created
 P->>D: db_query or db_pool_exhausted
 D-->>P: persisted / pool error
 P->>N: notification request after authorization
 N-->>P: sent or provider timeout
 P-->>G: completed or failed
```

Pool exhaustion yields no query, notification, or success event. Provider timeout preserves the approved payment and queues notification; v0.1 emits no later retry attempt.
