# Development setup

Requirements: Python 3.10 or newer. No packages need installation.

From repository root:

```bash
python3 -m payflow_simulator.cli --help
python3 -m payflow_simulator.cli --scenario all --seed 42 --payments 3 --output data/sample_events.jsonl
python3 -m unittest discover -s tests -v
```

The output directory is created when needed. `--start-time` accepts a timezone-aware ISO-8601 value; payment count must be positive.
