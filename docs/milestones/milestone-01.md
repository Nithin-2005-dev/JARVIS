# Milestone 01 — PayFlow Simulator v0.1

**Status:** Implemented and verified locally.

## Delivered

- Five named services represented in structured event streams.
- Normal flow, database pool exhaustion, and downstream notification failure.
- Typed schema, runtime validation, deterministic IDs/times, JSONL writer, and CLI.
- Sample dataset, unit tests, setup instructions, and lifecycle documentation.

## Architecture

One standard-library Python CLI generates an in-process event sequence. A fixed UTC clock and seeded PRNG make replay reproducible. Every request has a trace ID; fault scenarios model distinct failure propagation. JSONL is the inspectable output boundary.

## Verification

`python3 -m payflow_simulator.cli --scenario all --seed 42 --payments 3 --output data/sample_events.jsonl` wrote 63 events. `python3 -m unittest discover -s tests -v` ran 6 tests: all passed. Exact records are in [progress tracker](progress-tracker.md).

## Limitations and next step

There is no real concurrency, service RPC, connection pool, persistence, or retry lifecycle. Recommended next milestone: review event vocabulary, then add configurable workload/concurrency and retry timeline while retaining deterministic replay. Do not begin until approved.
