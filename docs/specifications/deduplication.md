# Deduplication and idempotency

SQLite `events.event_id` is a primary key. The ingestion engine uses `INSERT OR IGNORE`; a valid event ID inserted earlier in the current batch or any prior run is counted as a duplicate and does not replace the first stored payload. Thus the first successfully ingested event for an ID wins, including its metadata and source value. Event IDs are the idempotency key; identical payloads with different IDs remain distinct.

The store commits in batches (default 500 successful inserts) and flushes at the end of every ingestion run. This retains database-level uniqueness across runs while avoiding one fsync/commit per event. If a process terminates before a batch commit, at most the pending commit batch may be lost; rerunning the input is safe because records that were committed are detected as duplicates.
