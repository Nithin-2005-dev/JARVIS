"""Command line entry point for the PayFlow simulator."""

from __future__ import annotations

import argparse
from datetime import datetime

from .simulator import Scenario, Simulator, write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic PayFlow service events")
    parser.add_argument("--scenario", choices=[Scenario.ALL, Scenario.NORMAL, Scenario.DB_POOL_EXHAUSTION, Scenario.DOWNSTREAM_FAILURE], default=Scenario.ALL)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--payments", type=int, default=3, help="payments generated per scenario")
    parser.add_argument("--output", default="data/sample_events.jsonl")
    parser.add_argument("--start-time", default="2025-01-15T12:00:00+00:00", help="ISO-8601 timezone-aware timestamp")
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start_time.replace("Z", "+00:00"))
    events = Simulator(seed=args.seed, start_time=start).generate(args.scenario, args.payments)
    count = write_jsonl(events, args.output)
    print(f"Wrote {count} events to {args.output} (scenario={args.scenario}, seed={args.seed})")


if __name__ == "__main__":
    main()
