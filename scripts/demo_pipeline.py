"""Build a repeatable local Stage 1–8 dataset for the Stage 9 Command Center."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from payflow_simulator.simulator import Scenario, Simulator, write_jsonl
from payflow_simulator.ingestion.adapters import JSONFileAdapter
from payflow_simulator.ingestion.engine import IngestionEngine
from payflow_simulator.ingestion.storage import SQLiteEventStore
from payflow_simulator.processing.engine import ProcessingEngine
from payflow_simulator.processing.storage import SQLiteProcessingStore
from payflow_simulator.correlation.engine import CorrelationEngine
from payflow_simulator.correlation.storage import SQLiteCorrelationStore
from payflow_simulator.rca.engine import RCAEngine
from payflow_simulator.rca.storage import SQLiteRCAStore
from payflow_simulator.dependency_graph.blast_radius import DependencyGraphEngine
from payflow_simulator.dependency_graph.graph_store import SQLiteDependencyGraphStore
from payflow_simulator.intelligence.engine import IntelligenceEngine
from payflow_simulator.intelligence.storage import SQLiteIntelligenceStore
from payflow_simulator.recommendations.engine import RecommendationEngine
from payflow_simulator.recommendations.storage import SQLiteRecommendationStore


def run(database: Path, events_path: Path, *, reset: bool = False, payments: int = 3) -> dict[str, int]:
    """Run the established Python stage APIs; no UI fixtures or business logic are duplicated."""
    if reset and database.exists(): database.unlink()
    events_path.parent.mkdir(parents=True, exist_ok=True)
    database.parent.mkdir(parents=True, exist_ok=True)
    count = write_jsonl(Simulator(seed=42).generate(Scenario.ALL, payments), events_path)
    with SQLiteEventStore(database) as store: ingestion = IngestionEngine(store, database.parent / "quarantine.jsonl").ingest(JSONFileAdapter(events_path))
    with SQLiteProcessingStore(database) as store: processing = ProcessingEngine(store).run()
    with SQLiteCorrelationStore(database) as store: correlation = CorrelationEngine(store).run()
    with SQLiteDependencyGraphStore(database) as graph_store:
        graph = DependencyGraphEngine(graph_store)
        graph.validate()
        with SQLiteCorrelationStore(database) as correlation_store:
            incidents = correlation_store.list_incidents(status=None)
        with SQLiteRCAStore(database) as rca_store:
            rca_engine = RCAEngine(rca_store)
            for incident in incidents: rca_engine.investigate(incident["incident_id"])
        for incident in incidents: graph.analyze_incident(incident["incident_id"])
    with SQLiteIntelligenceStore(database) as store: intelligence = IntelligenceEngine(store).run()
    with SQLiteRecommendationStore(database) as store:
        generator = RecommendationEngine(store)
        for incident in incidents: generator.generate(incident_id=incident["incident_id"])
    return {"events_generated": count, "events_received": ingestion.received,
            "events_processed": processing.processed, "incidents": len(incidents),
            "intelligence_findings": len(intelligence.get("findings", []))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/demo.sqlite"))
    parser.add_argument("--events", type=Path, default=Path("data/demo_events.jsonl"))
    parser.add_argument("--payments", type=int, default=3)
    parser.add_argument("--reset", action="store_true", help="delete the selected database before rebuilding the demo")
    args = parser.parse_args()
    print(run(args.database, args.events, reset=args.reset, payments=args.payments))


if __name__ == "__main__": main()
