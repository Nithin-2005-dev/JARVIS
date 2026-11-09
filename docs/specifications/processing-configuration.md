# Processing configuration

Configuration is optional UTF-8 JSON passed with `--config PATH`. Omitted fields use defaults. Unknown top-level keys, duplicate rule IDs, invalid regexes, non-positive windows/batches/thresholds, or negative allowed lateness are rejected during startup.

```json
{
  "environment": "staging",
  "application": "payflow",
  "registry_version": "services-2026-01",
  "service_registry": {
    "payment-service": {"team": "payments", "tier": 1, "kind": "backend"}
  },
  "classification_rules": [
    {"rule_id": "db-pool", "category": "infrastructure_failures", "priority": 10,
     "event_types": ["db_pool_exhausted"]}
  ],
  "window_seconds": 60,
  "allowed_lateness_seconds": 30,
  "patterns": {
    "repeated_error": 2,
    "recurring_failure": 3,
    "frequency_spike": 10,
    "repeated_across_services": 2
  },
  "batch_size": 500,
  "stale_claim_seconds": 300
}
```

Rule match fields are conjunctive when present. A configured `classification_rules` list replaces the defaults. Service registry values are copied as arbitrary JSON metadata. The `ProcessingConfig` API can also be built directly in Python.
