"""CLI for Stage 7 feature, baseline, anomaly, temporal, pattern and history APIs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .engine import IntelligenceEngine
from .evaluation import write_evaluation
from .models import IntelligenceConfig
from .storage import SQLiteIntelligenceStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Run explainable, non-causal intelligence analysis")
    parser.add_argument("--database", default="data/events.sqlite", help="shared Stage 2–6 SQLite database")
    parser.add_argument("--config", help="optional JSON IntelligenceConfig")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("features", "baseline", "detect", "temporal", "patterns", "cross-service", "analyze"):
        sub.add_parser(name, help=f"run analysis and return {name} output")
    history = sub.add_parser("history", help="list or retrieve immutable intelligence runs")
    history.add_argument("--run-id")
    evaluate = sub.add_parser("evaluate", help="run deterministic time-ordered synthetic evaluation")
    evaluate.add_argument("--output-dir", default="data/evaluation")
    args = parser.parse_args()
    config = IntelligenceConfig(**json.loads(Path(args.config).read_text(encoding="utf-8"))) if args.config else IntelligenceConfig()
    with SQLiteIntelligenceStore(args.database) as store:
        if args.command == "history":
            output: Any = store.get_run(args.run_id) if args.run_id else store.history()
        elif args.command == "evaluate":
            output = write_evaluation(args.output_dir)
            evaluation_id = hashlib.sha256(json.dumps(output, sort_keys=True).encode()).hexdigest()
            store.save_evaluation(evaluation_id, output)
        else:
            result = IntelligenceEngine(store, config).run()
            if args.command == "features": output = {"run_id":result["run_id"],"features":result["features"],"feature_summary":result["feature_summary"]}
            elif args.command == "baseline": output = {"run_id":result["run_id"],"baselines":result["baselines"],"baseline_method":result["baseline_method"]}
            elif args.command == "detect": output = {"run_id":result["run_id"],"detectors":result["detectors"],"findings":[x for x in result["findings"] if x["finding_type"] in {"statistical_anomaly","ml_anomaly","insufficient_data","ml_baseline_observation"}]}
            elif args.command == "temporal": output = {"run_id":result["run_id"],"temporal_analysis":result["temporal_analysis"]}
            elif args.command == "patterns": output = {"run_id":result["run_id"],"patterns":result["patterns"]}
            elif args.command == "cross-service": output = {"run_id":result["run_id"],"cross_service_analysis":result["cross_service_analysis"]}
            else: output = result
        print(json.dumps(output, sort_keys=True, indent=2, default=str))


if __name__ == "__main__": main()

