# Technical research

The implementation uses Python standard-library facilities: `dataclasses` and `Enum` for the event contract, `argparse` for CLI, `random.Random(seed)` for replayable jitter and attributes, `json` for JSONL, and `unittest` for local verification. No third-party runtime dependencies are required. No claims are made about real payment provider behavior.

Stage 2 adds `urllib` for bounded HTTP GET ingestion and `sqlite3` for persistent local storage. JSONL/CSV adapters stream records; SQLite's primary key enforces idempotency across process restarts. Quarantine is append-only JSONL. These remain standard-library components.

Stage 3 continues with the standard library: SQLite transactions for atomic claims and output, regular expressions for configurable rules/signatures, `time.perf_counter` for monotonic durations, and `logging` with a JSON formatter. Fixed UTC epoch windows and explicit count thresholds keep pattern behavior deterministic and explainable. No statistical/ML claims are made.
# Stage 4 implementation research notes

No third-party similarity, graph, ORM, or web packages were added. Python's standard library provides timestamp parsing, UUID5 identifiers, sequence similarity, and SQLite persistence. The graph components use a small deterministic union-find implementation; transactional state remains in SQLite.

Candidate generation was chosen around exact trace/resource keys and temporal failure/service indexes. A generic all-pairs scan was rejected because dense input would make work grow quadratically even when pairs are irrelevant. Dense true buckets still imply quadratic candidate output, so the configured pair ceiling makes this visible as a failed run rather than allowing unbounded growth.

Similarity scores are transparent heuristics, not statistical estimates. We deliberately restrict approximate text comparison to event-time-near categorized failures and reuse Stage 3 evidence IDs. The synthetic labels measure pair co-membership on controlled cases only; representative operational data is required before making a quality claim.
