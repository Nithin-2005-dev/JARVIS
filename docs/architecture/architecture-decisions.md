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

## ADR-008: Separate source and processed payloads

**Decision:** Keep canonical ingested rows unchanged and store enriched output in `processed_events`. **Reason:** Processing rules and registries evolve; original data must remain auditable and replayable. **Trade-off:** The same event ID has a source representation and a derived representation.

## ADR-009: Durable local processing state

**Decision:** Store claims, attempts, status, stage history, output, and pattern observations in SQLite. **Reason:** A crash or stage failure must not discard ingested events, and safe replay needs durable state. **Trade-off:** SQLite is a local single-processor implementation; the stale claim timeout is not a distributed lease protocol.

## ADR-010: Fixed event-time windows and count patterns

**Decision:** Use epoch-aligned tumbling windows, a persisted maximum event time, and exact normalized signatures with configured thresholds. **Reason:** This makes event ordering and repetition behavior explainable and testable without ML. **Trade-off:** Threshold signals do not adapt to seasonality and do not infer causal relationships.

## ADR-011: Extend event-type vocabulary additively

**Decision:** Add lifecycle and security event types while retaining Stage 1 values and event fields. **Reason:** Those categories need representative source events to be classified through the validated pipeline. **Trade-off:** External producers still must use an explicitly supported type or extend the contract deliberately.

## ADR-012: Correlation reads processed events and stores separate evidence

**Decision:** Stage 4 reads Stage 3 `processed_events` and adds SQLite tables for runs, edges, evidence, trace diagnostics, incidents, membership, and history. **Reason:** Derived relationship evidence must not mutate canonical event records; one local database keeps Stage 1–3 lineage available. **Trade-off:** Full local reconciliation is single-host and SQLite-bound.

## ADR-013: Bounded indexed candidate generation

**Decision:** Generate pairs using trace/resource buckets and an event-time sweep keyed by failure category and service dependency; impose `max_candidates`. **Reason:** Avoid an uncontrolled all-pairs scan while preserving explicit shared-key and time-based signals. **Trade-off:** Dense keys can still create quadratic candidate output; the ceiling rejects an oversized run. Message similarity is limited to nearby failure candidates or explicit Stage 3 evidence, so distant similar events may be missed.

## ADR-014: Heuristic evidence and conservative incident policy

**Decision:** Store each strategy's evidence and score, combine with configurable weighted means, and call the result a heuristic confidence score. Require trace/resource evidence or both temporal and dependency signals; distinct trace IDs require a shared resource to bridge. **Reason:** Relationships need to be inspectable and false positives should not arise from time, text, or adjacent independent requests alone. **Trade-off:** Scores are not calibrated probabilities; strict grouping can miss genuine incidents with no trace, resource, or intersecting signals.

## ADR-015: Deterministic incident reconciliation

**Decision:** Recompute components from current processed data and reconcile membership transactionally; preserve the oldest incident ID on merge and the anchor-containing component ID on split. **Reason:** Late arrivals and changed rules must be recoverable and repeated runs idempotent. **Trade-off:** Full rebuild costs more than incremental distributed state and requires single-writer local SQLite.

## ADR-016: Evidence-driven RCA snapshots

**Decision:** Implement RCA as a separate incident-scoped layer that reads processed events and Stage 4 evidence and writes immutable fingerprinted report snapshots in SQLite. Distinguish observed facts, correlated relationships, configured dependency inferences, contradictions, and missing evidence. Use a configurable heuristic score, retain competing hypotheses, and return inconclusive when no candidate clears the evidence gate. **Reason:** Reproducibility and traceable reasoning matter more than forcing a single answer; correlation must not be represented as cause. **Trade-off:** Hand-authored strengths/reliabilities are not calibrated probabilities, configured topology may be wrong, and no cause can be independently confirmed without external signals.

## Rejected Stage 4 approaches

- All-pairs comparison: rejected because dense/O(n²) work is uncontrolled; candidate generation is indexed and bounded.
- Time-window overlap as incident identity: rejected because unrelated events can be simultaneous.
- Message similarity as a decisive signal: rejected because similar wording can describe different failures.
- Statistical probabilities, ML, LLMs, causality, Kafka, and Kubernetes: deferred because there is no calibration dataset or distributed deployment requirement in this milestone.
