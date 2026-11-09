"""Repeatable full-pipeline capacity probe for a requested synthetic event count."""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import tempfile
import time
from pathlib import Path
from statistics import mean
from typing import Callable

try:
    import resource
except ImportError:  # Windows has no resource module.
    resource = None  # type: ignore[assignment]

from fastapi.testclient import TestClient

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
from payflow_simulator.http_api.app import create_app


def _timed(func: Callable[[], object], stage: str) -> tuple[object,float]:
    print(f"benchmark_stage_started={stage}", file=sys.stderr, flush=True)
    started=time.perf_counter()
    try:
        value=func()
    except Exception:
        print(f"benchmark_stage_failed={stage}", file=sys.stderr, flush=True)
        raise
    elapsed=time.perf_counter()-started
    print(f"benchmark_stage_completed={stage} duration_seconds={elapsed:.4f}", file=sys.stderr, flush=True)
    return value,elapsed


def _percentile(samples:list[float],p:float)->float:
    return sorted(samples)[min(len(samples)-1,math.ceil(p*len(samples))-1)]


def run(event_count:int, *, warm_requests:int=8)->dict[str,object]:
    if event_count<1: raise ValueError("event_count must be positive")
    logging.basicConfig(level=logging.WARNING, force=True)
    with tempfile.TemporaryDirectory(prefix="jarvis-capacity-") as temp:
        root=Path(temp); db=root/"events.sqlite"; jsonl=root/"events.jsonl"
        payments=math.ceil(event_count/7)
        all_events=Simulator(seed=202610,).generate(Scenario.NORMAL,payments)
        selected=all_events[:event_count]
        generated,generate_s=_timed(lambda:write_jsonl(selected,jsonl),"generate_jsonl")
        del all_events
        with SQLiteEventStore(db) as store:
            ingest,ingest_s=_timed(lambda:IngestionEngine(store,root/"quarantine.jsonl").ingest(JSONFileAdapter(jsonl)),"ingest")
        with SQLiteProcessingStore(db) as store:
            processing,processing_s=_timed(lambda:ProcessingEngine(store).run(),"process")
        correlation_error=None
        with SQLiteCorrelationStore(db) as store:
            try:
                correlation,correlation_s=_timed(lambda:CorrelationEngine(store).run(),"correlate")
                correlation_data=correlation.to_dict()
            except (ValueError, RuntimeError) as exc:
                correlation=None;correlation_s=0.0;correlation_error=f"{type(exc).__name__}: {exc}";correlation_data=None
            incidents=store.list_incidents(status=None)
            chosen=incidents[0]["incident_id"] if incidents else None
        rca_seconds=0.0
        if chosen:
            with SQLiteRCAStore(db) as store:
                _,rca_seconds=_timed(lambda:RCAEngine(store).investigate(chosen),"rca_one_incident")
        with SQLiteDependencyGraphStore(db) as store:
            graph=DependencyGraphEngine(store)
            _,graph_s=_timed(lambda:graph.analyze_incident(chosen),"blast_radius_one_incident") if chosen else ({},0.0)
        with SQLiteIntelligenceStore(db) as store:
            intelligence,intelligence_s=_timed(lambda:IntelligenceEngine(store).run(),"intelligence")
        rec_seconds=0.0
        if chosen:
            with SQLiteRecommendationStore(db) as store:
                _,rec_seconds=_timed(lambda:RecommendationEngine(store).generate(incident_id=chosen),"recommendations_one_incident")
        app=create_app(str(db),auth_enabled=False)
        api_samples:dict[str,dict[str,float]]={}
        with TestClient(app) as client:
            targets={"incident_list":"/api/v1/incidents?page=1&page_size=25",
                     "service_graph":"/api/v1/services" if chosen else "/api/v1/services",
                     "recommendation_list":"/api/v1/recommendations?limit=25",
                     "overview":"/api/v1/overview"}
            if chosen: targets["incident_detail"]=f"/api/v1/incidents/{chosen}"
            for label,path in targets.items():
                samples=[]
                for _ in range(warm_requests+1):
                    started=time.perf_counter(); response=client.get(path); samples.append(time.perf_counter()-started)
                    if response.status_code!=200: raise RuntimeError(f"API benchmark {label} failed with HTTP {response.status_code}")
                api_samples[label]={"cold_seconds":round(samples[0],6),"warm_mean_seconds":round(mean(samples[1:]),6),
                                    "warm_p50_seconds":round(_percentile(samples[1:],.50),6),"warm_p95_seconds":round(_percentile(samples[1:],.95),6),
                                    "requests":len(samples),"failures":0}
        db_bytes=sum(path.stat().st_size for path in root.glob("events.sqlite*"))
        max_rss=(int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
                 if resource is not None else None)
        return {"event_count_requested":event_count,"events_generated":generated,"dataset_bytes":jsonl.stat().st_size,
                "stage_seconds":{"generate_jsonl":round(generate_s,4),"ingest":round(ingest_s,4),"process":round(processing_s,4),
                    "correlate":round(correlation_s,4),"rca_one_incident":round(rca_seconds,4),"blast_radius_one_incident":round(graph_s,4),
                    "intelligence":round(intelligence_s,4),"recommendations_one_incident":round(rec_seconds,4)},
                "ingestion":ingest.to_dict(),"processing":processing.to_dict(),"correlation":correlation_data,"correlation_error":correlation_error,
                "intelligence_findings":len(intelligence.get("findings",[])),"incident_count":len(incidents),
                "database_size_bytes_including_wal":db_bytes,"peak_rss_bytes":max_rss,
                "api":api_samples,"notes":"RCA, blast-radius, and recommendations are timed for one persisted incident to bound representative work. Cold means first in-process request; warm percentiles use repeated local TestClient calls."}


def main()->None:
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--events",type=int,required=True);parser.add_argument("--warm-requests",type=int,default=8)
    args=parser.parse_args();print(json.dumps(run(args.events,warm_requests=args.warm_requests),indent=2,sort_keys=True))


if __name__=="__main__":main()
