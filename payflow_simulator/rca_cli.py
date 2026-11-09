"""CLI to investigate persisted incidents and inspect immutable RCA snapshots."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .rca import RCAConfig, RCAEngine, SQLiteRCAStore
from .rca.config import rca_config_from_dict


def main() -> None:
    parser = argparse.ArgumentParser(description="Investigate incident evidence without claiming causation")
    parser.add_argument("--database", default="data/events.sqlite", help="Stage 2–4 SQLite database")
    parser.add_argument("--config", help="optional JSON RCA scoring and dependency settings")
    sub = parser.add_subparsers(dest="command", required=True)
    investigate = sub.add_parser("investigate", help="run or safely repeat an incident investigation")
    investigate.add_argument("incident_id")
    show = sub.add_parser("show", help="retrieve an investigation snapshot")
    show.add_argument("id", help="investigation ID, or incident ID with --latest")
    show.add_argument("--latest", action="store_true")
    hyp = sub.add_parser("hypothesis", help="retrieve one ranked candidate hypothesis")
    hyp.add_argument("investigation_id"); hyp.add_argument("candidate_event_id")
    ev = sub.add_parser("evidence", help="retrieve evidence for one candidate")
    ev.add_argument("investigation_id"); ev.add_argument("candidate_event_id")
    compare = sub.add_parser("compare", help="compare ranked competing hypotheses")
    compare.add_argument("investigation_id")
    history = sub.add_parser("history", help="retrieve investigation history for an incident")
    history.add_argument("incident_id")
    report = sub.add_parser("report", help="write a snapshot as structured JSON")
    report.add_argument("investigation_id"); report.add_argument("--output")
    args = parser.parse_args()
    config = RCAConfig()
    if args.config:
        config = rca_config_from_dict(json.loads(Path(args.config).read_text(encoding="utf-8")))
    with SQLiteRCAStore(args.database) as store:
        if args.command == "investigate": output: Any = RCAEngine(store, config).investigate(args.incident_id)
        elif args.command == "show": output = store.latest_investigation(args.id) if args.latest else store.get_investigation(args.id)
        elif args.command == "hypothesis": output = store.hypothesis(args.investigation_id, args.candidate_event_id)
        elif args.command == "evidence": output = store.evidence(args.investigation_id, args.candidate_event_id)
        elif args.command == "compare": output = store.compare(args.investigation_id)
        elif args.command == "history": output = store.history(args.incident_id)
        else:
            output = store.get_investigation(args.investigation_id)
            if args.output and output is not None:
                Path(args.output).write_text(json.dumps(output, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(output, sort_keys=True, indent=2))


if __name__ == "__main__": main()
