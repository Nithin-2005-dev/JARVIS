"""CLI for the configurable service graph and hypothetical blast-radius analysis."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .dependency_graph import DependencyGraphEngine, SQLiteDependencyGraphStore
from .dependency_graph.service_registry import load_config
from .dependency_graph.evaluate import run_evaluation


def main() -> None:
    parser=argparse.ArgumentParser(description="Inspect service dependencies and analyze potential blast radius")
    parser.add_argument("--database", default="data/events.sqlite", help="shared Stage 2–6 SQLite database")
    parser.add_argument("--config", help="optional JSON service/dependency registry and scoring configuration")
    sub=parser.add_subparsers(dest="command", required=True)
    sub.add_parser("services", help="list configured services")
    graph_cmd=sub.add_parser("graph", help="show the current or historical versioned graph")
    graph_cmd.add_argument("--version", help="graph version to retrieve")
    sub.add_parser("validate", help="validate graph definitions and report findings")
    blast=sub.add_parser("blast-radius", help="analyze a hypothetical service failure")
    blast.add_argument("--service", required=True); blast.add_argument("--max-depth", type=int); blast.add_argument("--environment"); blast.add_argument("--incident-id"); blast.add_argument("--graph-version")
    incident=sub.add_parser("incident", help="analyze each Stage 5 candidate for an incident")
    incident.add_argument("--incident-id", required=True); incident.add_argument("--max-depth", type=int); incident.add_argument("--environment"); incident.add_argument("--graph-version")
    history=sub.add_parser("history", help="retrieve prior graph versions or analyses")
    history.add_argument("--incident-id"); history.add_argument("--service")
    show=sub.add_parser("show", help="retrieve an analysis snapshot"); show.add_argument("analysis_id")
    evaluate=sub.add_parser("evaluate", help="run deterministic synthetic evaluation")
    evaluate.add_argument("--output", type=Path)
    args=parser.parse_args()
    if args.command == "evaluate":
        result=run_evaluation(); encoded=json.dumps(result, sort_keys=True, indent=2)+"\n"
        if args.output: args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(encoded, encoding="utf-8")
        print(encoded, end=""); return
    config=load_config(args.config) if args.config else None
    with SQLiteDependencyGraphStore(args.database) as store:
        historical_version = getattr(args, "graph_version", None)
        engine=DependencyGraphEngine(store, config, graph_version=historical_version)
        if args.command == "services": output=[s.to_dict() for _,s in sorted(engine.graph.services.items())]
        elif args.command == "graph": output=store.graph_snapshot(args.version)
        elif args.command == "validate": output=engine.validate()
        elif args.command == "blast-radius":
            context=store.incident_context(args.incident_id) if args.incident_id else None
            if args.incident_id and context is None: output={"error":{"code":"incident_not_found","message":f"Incident {args.incident_id} was not found."}}
            else:
                try: output=engine.analyze(args.service, max_depth=args.max_depth, environment=args.environment,
                    incident_context=context, scenario_label="hypothetical_explicit_service_failure")
                except KeyError as exc: output={"error":{"code":"unknown_service","message":str(exc)}}
                except ValueError as exc: output={"error":{"code":"invalid_analysis_options","message":str(exc)}}
        elif args.command == "incident":
            try: output=engine.analyze_incident(args.incident_id, max_depth=args.max_depth, environment=args.environment)
            except ValueError as exc: output={"error":{"code":"invalid_analysis_options","message":str(exc)}}
        elif args.command == "history": output={"graph_versions":store.graph_history(), "analyses":store.analysis_history(incident_id=args.incident_id, service_id=args.service)}
        else: output=store.analysis(args.analysis_id)
    print(json.dumps(output, sort_keys=True, indent=2))


if __name__ == "__main__": main()
