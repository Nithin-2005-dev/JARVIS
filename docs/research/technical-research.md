# Technical research

The implementation uses Python standard-library facilities: `dataclasses` and `Enum` for the event contract, `argparse` for CLI, `random.Random(seed)` for replayable jitter and attributes, `json` for JSONL, and `unittest` for local verification. No third-party runtime dependencies are required. No claims are made about real payment provider behavior.
