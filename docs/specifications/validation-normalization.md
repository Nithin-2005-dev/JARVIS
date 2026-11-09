# Validation and normalization rules

## Validation

- A record must be a JSON object with all nine canonical fields: `event_id`, `timestamp`, `service`, `event_type`, `severity`, `message`, `source`, `trace_id`, `metadata`.
- Unknown top-level keys are rejected rather than silently dropped. Arbitrary JSON-compatible fields inside `metadata` are preserved.
- Event and trace IDs must parse as UUIDs; canonical lowercase UUID strings are stored.
- Timestamp must be a timezone-aware ISO-8601 string. Naive times and invalid values are rejected.
- Severity must be a string matching a canonical value or documented alias.
- Required text fields must be non-empty strings. Metadata must be an object.
- Event type must resolve to the existing Stage 1 `EventType` vocabulary.

## Normalization

- Convert timestamps to UTC with a `Z` suffix while retaining available fractional precision.
- Canonical severity values are `INFO`, `WARNING`, `ERROR`, and `CRITICAL`; `WARN`, `ERR`, `FATAL`, and `PANIC` map to the corresponding canonical value.
- Event type text is lowercased and whitespace/hyphens become underscores.
- Service identifiers are lowercased and whitespace/underscores become hyphens.
- Preserve `source` exactly as supplied and preserve all metadata fields. Adapter provenance is stored separately from the event payload.

No field coercion occurs for invalid data types. Each bad record is rejected and quarantined with its original decoded payload and a reason.
