# Ingestion API and CLI

## Python interface

```python
from payflow_simulator.ingestion import IngestionEngine, SQLiteEventStore
from payflow_simulator.ingestion.adapters import JSONFileAdapter

with SQLiteEventStore("data/events.sqlite") as store:
    report = IngestionEngine(store, "data/quarantine.jsonl").ingest(
        JSONFileAdapter("data/sample_events.jsonl")
    )
print(report.to_dict())
```

`ingest(adapter)` accepts a `SourceAdapter` or iterable of `SourceRecord` and returns `IngestionReport` with `received`, `accepted`, `rejected`, `duplicates`, `duration_seconds`, and `events_per_second`. Counts satisfy `received = accepted + rejected + duplicates`. Throughput uses all received records, including duplicates and rejects. Reports contain aggregate metrics; rejection details are in quarantine.

## CLI

```bash
python3 -m payflow_simulator.ingest_cli --source json --input data/sample_events.jsonl
python3 -m payflow_simulator.ingest_cli --source csv --input events.csv --database data/events.sqlite
python3 -m payflow_simulator.ingest_cli --source rest --url http://localhost:8000/events --timeout 5
python3 -m payflow_simulator.ingest_cli --source live --seed 42 --payments 3
```

Options: `--database` (default `data/events.sqlite`), `--quarantine` (default `data/quarantine.jsonl`), `--timeout` (REST seconds, default 10), `--seed` and `--payments` (simulated live source). JSON input chooses JSONL by `.jsonl`/`.ndjson` extension and otherwise parses one JSON document. REST supports optional auth headers via `RESTAPIAdapter` from Python; the CLI does not expose secrets/credential flags.

## REST source behavior

The REST adapter issues an HTTP `GET` with a bounded timeout. It accepts an event object, array, `{ "events": [...] }` envelope, or JSONL response (`application/jsonl`/`application/x-ndjson` or `.jsonl`/`.ndjson` URL). It does not paginate, retry, or POST acknowledgements.
