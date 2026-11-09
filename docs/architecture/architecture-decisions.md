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
