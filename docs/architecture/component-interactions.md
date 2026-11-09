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

Ingestion is a separate downstream flow: adapters turn input into `SourceRecord` values, the engine validates and normalizes them, then writes accepted events to SQLite or invalid records to quarantine. It does not change event generation.

The processing engine claims ingested rows, enriches from its registry, applies matching classification rules, adds event-time/window annotations, and queries persisted window observations for repetition patterns. A final transaction writes the processed payload, evidence, watermark, processing history, and terminal state. A failure leaves the source row for a later retry.

Stage 4 reads only successful processed payloads. It creates bounded candidates from exact trace/resource indexes and event-time/service/failure indexes, scores each eligible strategy independently, then reconciles strong-evidence components as incidents. SQLite persists relationship evidence and lifecycle changes without modifying either canonical events or processed payloads.
# Stage 5 interaction

```mermaid
sequenceDiagram
  participant CLI as RCA CLI/API
  participant Engine as RCAEngine
  participant Store as SQLiteRCAStore
  CLI->>Engine: investigate(incident_id)
  Engine->>Store: load incident, members, processed payloads, Stage 4 edges
  Store-->>Engine: incident context
  Engine->>Engine: identify candidates and assess evidence
  Engine->>Engine: rank, gate competing/inconclusive results
  Engine->>Store: transactionally persist snapshot and assessments
  Store-->>CLI: reproducible structured report
```

RCA does not call or modify the Stage 4 engine. It consumes its stored edge evidence and preserves the distinction between relationship and cause.
