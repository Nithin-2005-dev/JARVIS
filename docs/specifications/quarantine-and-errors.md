# Error handling and quarantine

Invalid payloads, malformed JSON records, source-read errors, and record validation failures are isolated as individual rejected records whenever the source format provides record boundaries. Rejected input is appended to UTF-8 `quarantine.jsonl` with `adapter`, `locator`, `reason`, and `raw_record`. Existing quarantine data is not overwritten. A bad record does not prevent later records in the same batch from being processed.

Batch-level metrics distinguish accepted new events, rejected records, and valid duplicates. The report keeps aggregate counts; full rejection details live in quarantine so large invalid batches do not accumulate in memory. Storage/quarantine filesystem failures can still abort ingestion because the engine cannot safely claim data was persisted/quarantined.

Adapters expose missing file, HTTP, decoding, and parse failures as rejected source records. For syntactically malformed whole-document JSON there is no reliable item boundary, so the document is represented as one rejected raw record. JSONL and CSV retain line/row boundaries.
