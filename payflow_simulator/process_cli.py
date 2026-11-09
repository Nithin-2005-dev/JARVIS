"""Command line runner for the Event Processing Engine."""

from __future__ import annotations

import argparse
import json
import logging

from .processing.config import load_config
from .processing.engine import ProcessingEngine
from .processing.logging_config import JSONLogFormatter
from .processing.storage import SQLiteProcessingStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich, classify, and detect event patterns")
    parser.add_argument("--database", default="data/events.sqlite", help="Stage 2 SQLite database")
    parser.add_argument("--config", help="optional processing JSON configuration")
    parser.add_argument("--limit", type=int, help="maximum events to attempt in this run")
    parser.add_argument("--reprocess", action="store_true", help="explicitly replay already processed events")
    parser.add_argument("--log-level", default="WARNING", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    handler = logging.StreamHandler()
    handler.setFormatter(JSONLogFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, args.log_level))
    config = load_config(args.config)
    with SQLiteProcessingStore(args.database) as store:
        report = ProcessingEngine(store, config).run(limit=args.limit, reprocess=args.reprocess)
    print(json.dumps(report.to_dict(), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
