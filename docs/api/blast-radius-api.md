# Blast Radius API

```python
from payflow_simulator.dependency_graph import DependencyGraphEngine, SQLiteDependencyGraphStore, default_config

with SQLiteDependencyGraphStore("data/events.sqlite") as store:
    engine = DependencyGraphEngine(store, default_config())
    result = engine.analyze("database-service", max_depth=3, environment="development")
    incident_result = engine.analyze_incident("INCIDENT_ID")
```

`BlastRadiusAnalyzer.analyze(service_id, max_depth=None, environment=None, incident_context=None, scenario_label=...)` raises `KeyError` for an unknown root and `ValueError` for invalid depth/environment. Reports include direct/indirect services, all bounded paths, criticality distribution, capabilities, scoring breakdowns, observed incident event evidence, unresolved dependencies, cycles, warnings, graph version, and timestamps. `DependencyGraphEngine.analyze` also persists and returns an immutable JSON-compatible snapshot; repeats with equal graph/input/config return the original record. `analyze_incident` retains competing/inconclusive RCA candidates as separate hypothetical scenarios.

CLI:

```bash
python3 -m payflow_simulator.dependency_cli blast-radius --service database-service
python3 -m payflow_simulator.dependency_cli blast-radius --service database-service --max-depth 1
python3 -m payflow_simulator.dependency_cli blast-radius --service database-service --incident-id INCIDENT_ID
python3 -m payflow_simulator.dependency_cli blast-radius --service database-service --graph-version GRAPH_VERSION
python3 -m payflow_simulator.dependency_cli incident --incident-id INCIDENT_ID
python3 -m payflow_simulator.dependency_cli history --incident-id INCIDENT_ID
python3 -m payflow_simulator.dependency_cli show ANALYSIS_ID
```

An explicit service analysis is labeled a hypothetical service failure. Incident analyses link incident and Stage 5 RCA IDs. No service failure or root cause is independently confirmed by this API.
