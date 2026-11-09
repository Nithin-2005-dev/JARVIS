"""CLI for repeatable correlation runs and incident investigation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .correlation.config import CorrelationConfig, correlation_config_from_dict
from .correlation.engine import CorrelationEngine
from .correlation.storage import SQLiteCorrelationStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Correlate processed events and inspect incidents")
    parser.add_argument("--database", default="data/events.sqlite", help="Stage 2/3 SQLite database")
    parser.add_argument("--config", help="optional JSON correlation configuration")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="evaluate processed events and reconcile incidents").add_argument("--measure-memory", action="store_true")
    sub.add_parser("list", help="list active incidents").add_argument("--all", action="store_true", help="include merged/resolved incidents")
    for name in ("show", "events", "evidence", "history", "related"):
        cmd = sub.add_parser(name)
        cmd.add_argument("id", help="incident ID, or event ID for related")
    sub.add_parser("stats", help="show latest correlation metrics")
    args = parser.parse_args()
    config = CorrelationConfig()
    if args.config:
        raw = json.loads(Path(args.config).read_text(encoding="utf-8"))
        config = correlation_config_from_dict(raw)
    with SQLiteCorrelationStore(args.database) as store:
        if args.command == "run":
            output = CorrelationEngine(store, config).run(measure_memory=args.measure_memory).to_dict()
        elif args.command == "list":
            output = store.list_incidents(None if args.all else "active")
        elif args.command == "show":
            output = store.get_incident(args.id)
        elif args.command == "events":
            output = store.incident_events(args.id)
        elif args.command == "evidence":
            output = store.incident_evidence(args.id)
        elif args.command == "history":
            output = store.incident_history(args.id)
        elif args.command == "related":
            output = store.related_events(args.id)
        else:
            output = store.statistics()
    print(json.dumps(output, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
