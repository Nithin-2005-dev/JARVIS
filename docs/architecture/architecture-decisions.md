# Architecture decisions

## ADR-001: In-process simulation

**Decision:** Model service behavior with one Python process and service-tagged records. **Reason:** Stage 1 requires realistic event generation, not infrastructure. This keeps setup simple and deterministic. **Trade-off:** No real network boundaries or concurrency are exercised.

## ADR-002: Standard library only

**Decision:** Use dataclasses, enums, argparse, json, random, pathlib, and unittest. **Reason:** A small CLI does not need framework overhead. **Trade-off:** Validation is a maintained Python contract rather than a schema package.

## ADR-003: Seeded RNG and fixed clock

**Decision:** Seed generated jitter and default to a fixed UTC instant. **Reason:** Identical inputs must reproduce output. **Trade-off:** The default dataset is not wall-clock current.

## ADR-004: JSONL output

**Decision:** Emit one event per line. **Reason:** It is stream-friendly and easy to inspect. **Trade-off:** There is no index or transaction envelope.

## Rejected approaches

Kafka/Kubernetes, a web framework, and live timestamps were deferred because they add operational complexity or reduce reproducibility before the event contract is established.

## ADR-005: Common streaming source adapter contract

**Decision:** Adapters yield `SourceRecord` items through a `records()` method. **Reason:** File, HTTP, and live inputs can be added without branching in the core engine. **Trade-off:** Each adapter translates source framing and parse failures into records.

## ADR-006: SQLite idempotent local storage

**Decision:** Store canonical JSON payloads in local SQLite with `event_id` as the primary key. **Reason:** This gives durable cross-run idempotency without distributed infrastructure. **Trade-off:** A local database is single-host; commit batches balance throughput and crash durability.

## ADR-007: Append-only quarantine JSONL

**Decision:** Preserve rejected raw payloads with reason and source locator in JSONL. **Reason:** Invalid inputs remain inspectable without blocking valid records in the same batch. **Trade-off:** Operators must manage quarantine retention and file growth.
