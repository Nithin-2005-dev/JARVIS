"""CLI for generating and managing advisory Stage 8 recommendations."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .evaluation import evaluate
from .engine import RecommendationEngine
from .models import RecommendationConfig, RecommendationFeedback
from .storage import SQLiteRecommendationStore


def main() -> None:
    parser=argparse.ArgumentParser(description="Generate evidence-backed recommendations; no remediation is executed")
    parser.add_argument("--database",default="data/events.sqlite",help="shared Stage 2–7 SQLite database")
    sub=parser.add_subparsers(dest="command",required=True)
    generate=sub.add_parser("generate"); target=generate.add_mutually_exclusive_group(required=True); target.add_argument("--incident-id"); target.add_argument("--service")
    listing=sub.add_parser("list"); listing.add_argument("--incident-id"); listing.add_argument("--service"); listing.add_argument("--status"); listing.add_argument("--limit",type=int,default=100)
    show=sub.add_parser("show"); show.add_argument("--recommendation-id",required=True)
    update=sub.add_parser("update"); update.add_argument("--recommendation-id",required=True); update.add_argument("--status",required=True); update.add_argument("--reason",default=""); update.add_argument("--notes",default="")
    feedback=sub.add_parser("feedback"); feedback.add_argument("--recommendation-id",required=True); feedback.add_argument("--outcome",choices=["successful","unsuccessful","inconclusive","not_attempted"],required=True); feedback.add_argument("--evidence",default="[]",help="JSON list of evidence references"); feedback.add_argument("--notes",default=""); feedback.add_argument("--actual-result",default=""); feedback.add_argument("--incident-state")
    history=sub.add_parser("history"); history.add_argument("--recommendation-id",required=True)
    evaluate_parser=sub.add_parser("evaluate")
    args=parser.parse_args()
    with SQLiteRecommendationStore(args.database) as store:
        if args.command=="generate": output=RecommendationEngine(store).generate(incident_id=args.incident_id,service_id=args.service)
        elif args.command=="list": output=store.list_recommendations(incident_id=args.incident_id,service_id=args.service,status=args.status,limit=args.limit)
        elif args.command=="show": output=store.get_recommendation(args.recommendation_id)
        elif args.command=="update": output=store.update_status(args.recommendation_id,args.status,reason=args.reason,notes=args.notes)
        elif args.command=="history": output={"status_history":store.history(args.recommendation_id),"feedback":store.feedback_history(args.recommendation_id)}
        elif args.command=="feedback":
            data=RecommendationFeedback(args.recommendation_id,args.outcome_status if hasattr(args,"outcome_status") else args.outcome,tuple(json.loads(args.evidence)),args.notes,args.actual_result,args.incident_state).to_dict()
            output=store.record_feedback(data)
        else:
            output=evaluate(); evaluation_id=hashlib.sha256(json.dumps(output,sort_keys=True).encode()).hexdigest(); store.save_evaluation(evaluation_id,output)
    print(json.dumps(output,sort_keys=True,indent=2,default=str))


if __name__=="__main__": main()
