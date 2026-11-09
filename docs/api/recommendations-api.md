# Recommendations API and CLI

## Python API

```python
from payflow_simulator.recommendations import RecommendationEngine, RecommendationConfig, SQLiteRecommendationStore

with SQLiteRecommendationStore("data/events.sqlite") as store:
    result = RecommendationEngine(store, RecommendationConfig()).generate(incident_id="INCIDENT_ID")
    # or: .generate(service_id="payment-service")
    current = store.get_recommendation(result["recommendations"][0]["recommendation_id"])
    store.update_status(current["recommendation_id"], "acknowledged")
```

`generate(incident_id=..., service_id=...)` accepts exactly one target through the CLI and reads persisted Stage 3–7 context. `generate(context=...)` supports deterministic integrations and tests. Return objects include `context_status`, `run_id`, recommendations, and summary; insufficient inputs return a structured `insufficient_context` outcome without raising. A usable context with no applicable rule returns `no_applicable_rule`.

`SQLiteRecommendationStore` also exposes `list_recommendations`, `get_recommendation`, `get_run`, `get_run_by_fingerprint`, `history`, `record_feedback`, `feedback_history`, and `save_evaluation`. `RecommendationEngine` exposes the modular generator. `Recommendation`, `RecommendationConfig`, and `RecommendationFeedback` validate public records.

## CLI

The shared database option comes before the subcommand:

```bash
python3 -m payflow_simulator.recommendations.cli --database data/events.sqlite generate --incident-id INCIDENT_ID
python3 -m payflow_simulator.recommendations.cli --database data/events.sqlite generate --service payment-service
python3 -m payflow_simulator.recommendations.cli --database data/events.sqlite list --incident-id INCIDENT_ID
python3 -m payflow_simulator.recommendations.cli --database data/events.sqlite show --recommendation-id ID
python3 -m payflow_simulator.recommendations.cli --database data/events.sqlite update --recommendation-id ID --status acknowledged
python3 -m payflow_simulator.recommendations.cli --database data/events.sqlite feedback --recommendation-id ID --outcome inconclusive --notes "Need current metrics"
python3 -m payflow_simulator.recommendations.cli --database data/events.sqlite history --recommendation-id ID
python3 -m payflow_simulator.recommendations.cli --database data/events.sqlite evaluate
```

Feedback `--evidence` accepts a JSON list of evidence references. `update --status dismissed` requires `--reason`; invalid lifecycle changes return a validation error. No CLI command executes a suggested action.

## Recommendation record

The record includes stable IDs, incident/run identifiers, rule/version provenance, title/description/type, services, priority/urgency, confidence label, supporting/contradictory evidence, assumptions, expected benefit, risk/side effects, prerequisites, implementation/verification/rollback steps, related Stage 5–7 identifiers, lifecycle status, creation time, and score breakdown. Source evidence remains referenced rather than copied wholesale; small direct event fields relevant to the rule (including selected pool metrics) are included for traceability.
