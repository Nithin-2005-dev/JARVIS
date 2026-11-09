"""Reproducible synthetic ground-truth generator and pair-level evaluation."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from ..processing.storage import SQLiteProcessingStore
from .engine import CorrelationEngine
from .storage import SQLiteCorrelationStore


def synthetic_events(groups: int = 20, unrelated_pairs: int = 20) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Return fixed synthetic processed payloads and group labels (not fed to engine)."""
    events: list[dict[str, Any]] = []
    labels: dict[str, str] = {}
    base_epoch = 1735689600  # 2025-01-01 UTC
    for group_no in range(groups):
        group_id = f"synthetic-incident-{group_no:04d}"
        trace = str(uuid5(NAMESPACE_URL, f"trace:{group_id}"))
        stamp = base_epoch + group_no * 600
        for offset, service in enumerate(("api-gateway", "payment-service", "database-service")):
            event_id = str(uuid5(NAMESPACE_URL, f"event:{group_id}:{service}"))
            resource = f"db-{group_no:04d}" if service in {"payment-service", "database-service"} else None
            metadata = {"database_id": resource} if resource else {"request_id": group_id}
            event = _processed(event_id, service, stamp + offset, trace, metadata, "database connection failed", ["database_failures", "application_errors"])
            events.append(event)
            labels[event_id] = group_id
    # Coincident but independent error records deliberately have no trace/resource
    # overlap and come from services outside the dependency registry.
    for pair_no in range(unrelated_pairs):
        stamp = base_epoch + (groups + pair_no) * 600
        for side in ("left", "right"):
            event_id = str(uuid5(NAMESPACE_URL, f"unrelated:{pair_no}:{side}"))
            service = f"isolated-{side}-{pair_no}"
            events.append(_processed(event_id, service, stamp, "", {"resource_id": f"private-{pair_no}-{side}"},
                                     "database connection failed", ["database_failures", "application_errors"]))
    return events, labels


def run_evaluation(output_dir: str | Path, groups: int = 20, unrelated_pairs: int = 20) -> dict[str, Any]:
    """Persist a reproducible JSONL fixture and report measured pair precision/recall."""
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    events, labels = synthetic_events(groups, unrelated_pairs)
    (destination / "stage4_events.jsonl").write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in events), encoding="utf-8")
    (destination / "stage4_ground_truth.json").write_text(json.dumps(labels, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with tempfile.TemporaryDirectory() as temp:
        db = Path(temp) / "evaluation.sqlite"
        with SQLiteProcessingStore(db):
            pass
        with SQLiteCorrelationStore(db) as store:
            store.connection.executemany("INSERT INTO processed_events(event_id,payload,processed_at) VALUES(?,?,?)",
                [(item["event_id"], json.dumps(item, sort_keys=True), item["processing_timestamp"]) for item in events])
            store.connection.commit()
            report = CorrelationEngine(store).run(measure_memory=True)
            predicted: set[tuple[str, str]] = set()
            for incident in store.list_incidents():
                ids = incident["event_ids"]
                predicted.update((a, b) for i, a in enumerate(ids) for b in ids[i + 1:])
    expected = {(a, b) for a, ga in labels.items() for b, gb in labels.items() if ga == gb and a < b}
    true_positive = len(predicted & expected)
    precision = true_positive / len(predicted) if predicted else 0.0
    recall = true_positive / len(expected) if expected else 0.0
    return {"method": "pairwise co-membership against synthetic group labels; labels are never supplied to correlation",
            "events": len(events), "ground_truth_groups": groups, "unrelated_pairs": unrelated_pairs,
            "ground_truth_related_pairs": len(expected), "predicted_related_pairs": len(predicted),
            "true_positive_pairs": true_positive, "false_positive_pairs": len(predicted - expected),
            "false_negative_pairs": len(expected - predicted), "precision": precision, "recall": recall,
            "performance": report.to_dict(), "dataset": str(destination / "stage4_events.jsonl"),
            "ground_truth": str(destination / "stage4_ground_truth.json")}


def _processed(event_id: str, service: str, epoch: int, trace: str, metadata: dict[str, Any], message: str,
               categories: list[str]) -> dict[str, Any]:
    from datetime import datetime, timezone
    stamp = datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")
    original = {"event_id": event_id, "timestamp": stamp, "service": service, "event_type": "db_query",
                "severity": "ERROR", "message": message, "source": "synthetic-evaluation", "trace_id": trace, "metadata": metadata}
    return {"schema_version": "1.0", "event_id": event_id, "original_event": original,
            "processing_timestamp": "2025-01-02T00:00:00Z", "classification": {"categories": categories},
            "temporal": {"event_timestamp": stamp, "processing_timestamp": "2025-01-02T00:00:00Z", "late_arrival": False},
            "patterns": []}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and evaluate deterministic Stage 4 synthetic data")
    parser.add_argument("--output-dir", default="data/evaluation")
    parser.add_argument("--groups", type=int, default=20)
    parser.add_argument("--unrelated-pairs", type=int, default=20)
    args = parser.parse_args()
    if args.groups < 1 or args.unrelated_pairs < 0:
        parser.error("groups must be positive and unrelated-pairs non-negative")
    print(json.dumps(run_evaluation(args.output_dir, args.groups, args.unrelated_pairs), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
