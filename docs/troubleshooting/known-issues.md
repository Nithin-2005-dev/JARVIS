# Known issues and limitations

- The event contract is illustrative, not a production payment or audit schema.
- Pool exhaustion is injected at request boundary; occupancy, wait queues, concurrency, and recovery are not modeled.
- A downstream timeout marks the notification queued, but no retry/backoff event is emitted.
- Service calls and database writes are synthetic.
- Metadata fields are not strictly validated beyond requiring an object.
- The default timestamp is fixed for reproducibility; select `--start-time` to change the timeline.
- IDs are deterministic for fixture generation and are not globally unique across independent streams/seeds.
- JSON document input is loaded as one document; use JSONL for large files. CSV and JSONL adapters stream rows/lines.
- REST ingestion performs one GET, reads the response body before processing, and does not paginate or retry. Large REST responses require memory proportional to response size.
- SQLite is a single-host store. It commits every 500 newly inserted rows and at batch completion; an abrupt exit may lose the current pending commit batch.
- Quarantine is append-only and has no built-in rotation or retention enforcement.
- Repeated event IDs keep the first accepted payload without comparing later payload differences.
- REST CLI does not configure auth headers; Python adapter callers can supply headers.
