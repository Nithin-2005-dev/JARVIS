# RCA API and CLI

## Python API

```python
from payflow_simulator.rca import RCAConfig, RCAEngine, SQLiteRCAStore

with SQLiteRCAStore("data/events.sqlite") as store:
    report = RCAEngine(store, RCAConfig()).investigate("INCIDENT_ID")
```

`RCAEngine.investigate(incident_id)` returns a JSON-serializable report dictionary and raises `KeyError` when the incident does not exist. The storage API exposes `get_investigation`, `latest_investigation`, `hypothesis`, `evidence`, `compare`, and `history`. Repeating an unchanged investigation returns the existing snapshot.

## CLI

```bash
python3 -m payflow_simulator.rca_cli --database data/events.sqlite investigate INCIDENT_ID
python3 -m payflow_simulator.rca_cli --database data/events.sqlite show INVESTIGATION_ID
python3 -m payflow_simulator.rca_cli --database data/events.sqlite show INCIDENT_ID --latest
python3 -m payflow_simulator.rca_cli --database data/events.sqlite hypothesis INVESTIGATION_ID EVENT_ID
python3 -m payflow_simulator.rca_cli --database data/events.sqlite evidence INVESTIGATION_ID EVENT_ID
python3 -m payflow_simulator.rca_cli --database data/events.sqlite compare INVESTIGATION_ID
python3 -m payflow_simulator.rca_cli --database data/events.sqlite history INCIDENT_ID
python3 -m payflow_simulator.rca_cli --database data/events.sqlite report INVESTIGATION_ID --output report.json
```

Optional JSON configuration fields: `evidence_weights`, `contradictory_weight`, `evidence_reliability`, `minimum_supporting_families`, `minimum_heuristic_score`, `competing_margin`, `service_dependencies`, and `abnormal_severities`. Unknown keys and out-of-range weights are rejected. The CLI prints JSON to stdout; `report --output` writes the same stored snapshot to a file.
