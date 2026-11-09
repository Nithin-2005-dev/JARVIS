# Simulator specification v0.1

## Scenarios

- `normal`: authorization, persistence, notification, and simulated 201 response succeed.
- `db_pool_exhaustion`: first payment fails acquiring a connection with a critical event and simulated 503; remaining payments are healthy.
- `downstream_failure`: first payment is authorized, provider times out, and notification is queued for retry; remaining payments are healthy.
- `all`: runs normal, database-failure, and downstream-failure scenarios in that order.

`--payments N` creates N request traces per scenario. Fault injection affects the first request in each failure scenario. Each trace has a fixed increasing event schedule, a fixed start time, and seeded sub-8ms jitter. IDs are deterministic UUID-shaped values.

## CLI

`python -m payflow_simulator.cli [--scenario ...] [--seed INT] [--payments INT] [--output PATH] [--start-time ISO8601]`

Output is UTF-8 JSONL. Defaults are all scenarios, seed 42, three payments per scenario, and `data/sample_events.jsonl`.
