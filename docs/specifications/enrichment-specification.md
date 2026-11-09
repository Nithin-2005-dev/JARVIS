# Enrichment specification

Each output has a separate `enrichment` object. It contains:

- `environment` and `application` from processing configuration.
- `service_metadata` looked up by the canonical service ID in the configured service registry, or `{}` when unmatched.
- `enrichment_provenance` with registry version, match result, input service ID, and enrichment processing timestamp.

The complete ingested event is retained at `original_event`; enrichment does not mutate its source or metadata. Registry fields are copied into output. There is no external service discovery, dynamic registry refresh, or environment inference from payload content in v0.3.
