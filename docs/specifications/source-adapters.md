# Source adapter contract

The extension point is in `payflow_simulator.ingestion.adapters`:

```python
class SourceAdapter(Protocol):
    def records(self) -> Iterable[SourceRecord]: ...
```

`SourceRecord` has `data` (untrusted decoded payload), `adapter` (source kind), `locator` (file line, URL, or live sequence), and optional `error` (adapter parse/read error). Adapters must continue after record-level errors when framing allows it and yield a record carrying that error. The core engine does not contain adapter-specific branches.

| Adapter | Accepted input | Record boundary |
|---|---|---|
| `JSONFileAdapter` | `.json` object/array or `events` envelope; `.jsonl`/`.ndjson` lines | object/array item or non-empty line |
| `CSVFileAdapter` | Header row whose columns are canonical event keys | CSV data row; `metadata` column contains JSON object text |
| `RESTAPIAdapter` | HTTP GET response with JSON, JSON envelope, or JSONL content type/extension | object/array item or non-empty JSONL line |
| `LiveEventAdapter` | Iterable of mappings or `Event` objects | One iterable value |

An adapter is reusable when `records()` constructs a fresh read; live iterables may be one-shot. The REST adapter accepts optional headers and timeout for library callers. The CLI currently supports URL and timeout but not credential configuration.
