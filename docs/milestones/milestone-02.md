# Milestone 02 — Event Ingestion Engine

**Status:** Implemented and verified locally.

## Features implemented

- Common streaming adapter contract (`SourceAdapter.records()` → `SourceRecord`).
- JSON object/array/envelope and JSONL/NDJSON file ingestion, CSV ingestion, HTTP REST GET ingestion, and live/simulated iterable ingestion.
- Per-record validation and normalization into the Stage 1 `Event` shape; UTC timestamps, canonical UUID strings, severity aliases, and service/event-type identifier normalization.
- Preservation of original `source` and metadata, with adapter provenance maintained separately.
- SQLite persistence with `event_id` primary-key deduplication and batch commits; first successfully stored payload wins.
- Record-level quarantine JSONL with raw record, adapter, locator, and rejection reason.
- Per-run received/accepted/rejected/duplicate counts, processing duration, and throughput.
- Ingestion CLI and Python API documentation.

## Architecture decisions

The ingestion core is source-independent and consumes records yielded by adapters. SQLite provides durable local idempotency without distributed infrastructure. Quarantine is append-only JSONL to preserve failed inputs for investigation. JSONL and CSV are streamed; full JSON documents and REST bodies are parsed as documents.

## Verification and performance

`python3 -m unittest discover -s tests -v` ran 18 tests: all passed. Stage 1's default command regenerated 63 events byte-identical to the committed sample. The ingestion CLI accepted the existing 63-event Stage 1 dataset. A measured 5,000-row JSONL run accepted all 5,000 records; elapsed time and throughput are recorded in the progress tracker.

## Known limitations

The REST adapter performs one GET and has no pagination/retry/acknowledgement protocol; its response body is read before processing. JSON arrays are loaded as a single document, so JSONL is preferred for large input. SQLite is single-host and may lose its current uncommitted group on abrupt process termination. Quarantine retention/rotation is manual. Duplicate IDs retain the first payload without comparing later payloads. See [known issues](../troubleshooting/known-issues.md).

## Recommended next milestone

Review ingestion schemas and operational behavior before Stage 3. Event correlation and root cause analysis remain unimplemented. Do not start Stage 3 until approved.
