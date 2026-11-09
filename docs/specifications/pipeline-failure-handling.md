# Pipeline failure handling

Each stage failure is recorded with its stage name, error, and successful prior stages in `processing_history`; `processing_state` becomes `failed` with `current_stage` and `last_error`. A later processing run retries that row. Pipeline exceptions are logged with event ID, attempt, stage, and error. Persistence exceptions are surfaced as operational failures and the source row remains in the ingestion table.

Processed payload, pattern observation, watermark advancement, successful stage history, and state transition are atomic. A process crash while a row is `processing` leaves the row recoverable after the configured stale claim timeout. SQLite transactions prevent partially committed final output. There is no dead-letter deletion path; failed events are retained indefinitely for retry or investigation.
