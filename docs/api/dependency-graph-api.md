# Dependency Graph API

```python
from payflow_simulator.dependency_graph import DependencyGraphBuilder, default_config

graph = DependencyGraphBuilder(default_config()).build()
graph.to_dict()  # graph_version, services, dependencies, findings, config
```

The Python API exposes `DependencyGraphBuilder.build(services=None, dependencies=None)`, `DependencyGraphEngine.validate()`, `DependencyGraph.to_dict()`, and `SQLiteDependencyGraphStore.graph_snapshot(version=None)` / `graph_history()`. Validation returns structured findings (`code`, `severity`, `message`, `context`) rather than dropping invalid records. Unknown endpoint edges and unknown dependency types remain in the graph snapshot; only edges with known service endpoints participate in traversal.

Config is JSON with `services`, `dependencies`, `known_dependency_types`, `criticality_factors`, `verification_factors`, `depth_decay`, `fanout_base`, `fanout_increment`, `max_paths_per_service`, and `version_label`. `--config` replaces the default registry; every run stores the normalized version snapshot.

CLI examples:

```bash
python3 -m payflow_simulator.dependency_cli services
python3 -m payflow_simulator.dependency_cli graph
python3 -m payflow_simulator.dependency_cli graph --version GRAPH_VERSION
python3 -m payflow_simulator.dependency_cli blast-radius --service database-service --graph-version GRAPH_VERSION
python3 -m payflow_simulator.dependency_cli validate
```
