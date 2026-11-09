# Demo environment

Build the Stage 1–8 dataset from real simulator and stage APIs:

```bash
python scripts/demo_pipeline.py --database data/demo.sqlite --events data/demo_events.jsonl --reset
```

`--reset` deletes only the explicitly selected database before rebuilding it. The simulator uses seed 42 and the established default scenario; ingestion, processing, correlation, RCA, dependency, intelligence, and recommendation engines perform their normal persisted workflows. Without `--reset`, event IDs make ingestion repeatable, and downstream stage engines use their existing idempotency behavior.

Start the API and frontend as described in [local development](local-development.md). To use an empty database, choose a new `JARVIS_DATABASE` path; the UI presents empty states and does not substitute sample fixtures.
