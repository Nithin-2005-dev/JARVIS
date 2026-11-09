# Technical research

The implementation uses Python standard-library facilities: `dataclasses` and `Enum` for the event contract, `argparse` for CLI, `random.Random(seed)` for replayable jitter and attributes, `json` for JSONL, and `unittest` for local verification. No third-party runtime dependencies are required. No claims are made about real payment provider behavior.

Stage 2 adds `urllib` for bounded HTTP GET ingestion and `sqlite3` for persistent local storage. JSONL/CSV adapters stream records; SQLite's primary key enforces idempotency across process restarts. Quarantine is append-only JSONL. These remain standard-library components.

Stage 3 continues with the standard library: SQLite transactions for atomic claims and output, regular expressions for configurable rules/signatures, `time.perf_counter` for monotonic durations, and `logging` with a JSON formatter. Fixed UTC epoch windows and explicit count thresholds keep pattern behavior deterministic and explainable. No statistical/ML claims are made.
