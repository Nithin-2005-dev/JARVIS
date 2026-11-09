# Coding conventions

- Target Python 3.10+ and standard-library dependencies only.
- Type public functions and use dataclasses/enums for structured immutable events.
- Keep event contract in `models.py`, scenarios/output in `simulator.py`, and CLI parsing in `cli.py`.
- Use snake_case Python identifiers, kebab-case service IDs, and lower snake case event keys.
- Validate generated events before writing UTF-8 JSONL.
- Use deterministic `unittest` cases without network or external services.
