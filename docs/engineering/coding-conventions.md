# Coding conventions

- Target Python 3.10+ and standard-library dependencies only.
- Type public functions and use dataclasses/enums for structured immutable events.
- Keep event contract in `models.py`, scenarios/output in `simulator.py`, and CLI parsing in `cli.py`.
- Use snake_case Python identifiers, kebab-case service IDs, and lower snake case event keys.
- Validate generated events before writing UTF-8 JSONL.
- Implement new sources as `SourceAdapter` streams of `SourceRecord` values; keep source parsing outside the ingestion engine.
- Keep ingestion streaming for JSONL/CSV and retain rejected input with adapter provenance and an actionable reason.
- Use deterministic `unittest` cases without network or external services.
