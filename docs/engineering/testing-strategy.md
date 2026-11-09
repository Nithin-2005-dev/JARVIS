# Testing strategy

The `unittest` suite checks deterministic replay and unique event IDs, all five service identities and scenarios, expected database/downstream fault events, monotonic per-trace times and shared payment identity, rejection of malformed structures, and JSONL parse/validation. Tests are local and deterministic; no deployed service behavior is claimed.
