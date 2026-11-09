"""Source adapters that expose records through one streaming contract."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """One source item, including adapter provenance and a stable locator."""

    data: Any
    adapter: str
    locator: str
    error: str | None = None


class SourceAdapter(Protocol):
    """Common interface implemented by all ingestion source adapters."""

    def records(self) -> Iterable[SourceRecord]:
        """Yield source records without converting them to the canonical model."""


def _decoded_json_records(text: str, adapter: str, locator: str, jsonl: bool) -> Iterator[SourceRecord]:
    if jsonl:
        for line_number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                yield SourceRecord(json.loads(line), adapter, f"{locator}:{line_number}")
            except json.JSONDecodeError as exc:
                yield SourceRecord(line, adapter, f"{locator}:{line_number}", f"malformed JSON: {exc.msg} at column {exc.colno}")
        return
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        yield SourceRecord(text, adapter, locator, f"malformed JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}")
        return
    if isinstance(document, dict) and isinstance(document.get("events"), list):
        document = document["events"]
    if isinstance(document, list):
        for index, value in enumerate(document, 1):
            yield SourceRecord(value, adapter, f"{locator}#{index}")
    else:
        yield SourceRecord(document, adapter, locator)


@dataclass(frozen=True, slots=True)
class JSONFileAdapter:
    """Read a JSON object/array or line-delimited JSON file."""

    path: str | Path

    def records(self) -> Iterable[SourceRecord]:
        path = Path(self.path)
        adapter = "jsonl_file" if path.suffix.lower() in {".jsonl", ".ndjson"} else "json_file"
        if adapter == "jsonl_file":
            try:
                with path.open(encoding="utf-8") as stream:
                    for line_number, line in enumerate(stream, 1):
                        if not line.strip():
                            continue
                        try:
                            yield SourceRecord(json.loads(line), adapter, f"{path}:{line_number}")
                        except json.JSONDecodeError as exc:
                            yield SourceRecord(line.rstrip("\r\n"), adapter, f"{path}:{line_number}", f"malformed JSON: {exc.msg} at column {exc.colno}")
            except (OSError, UnicodeError) as exc:
                yield SourceRecord(None, adapter, str(path), f"source read error: {exc}")
            return
        try:
            with path.open(encoding="utf-8") as stream:
                text = stream.read()
        except (OSError, UnicodeError) as exc:
            yield SourceRecord(None, adapter, str(path), f"source read error: {exc}")
            return
        yield from _decoded_json_records(text, adapter, str(path), False)


@dataclass(frozen=True, slots=True)
class CSVFileAdapter:
    """Stream rows from a CSV file using its header as event field names."""

    path: str | Path

    def records(self) -> Iterable[SourceRecord]:
        path = Path(self.path)
        try:
            with path.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                if not reader.fieldnames:
                    yield SourceRecord(None, "csv_file", f"{path}:1", "CSV is missing a header row")
                    return
                for row in reader:
                    locator = f"{path}:{reader.line_num}"
                    try:
                        item: dict[str, Any] = dict(row)
                        metadata = item.get("metadata")
                        if isinstance(metadata, str) and metadata:
                            item["metadata"] = json.loads(metadata)
                        yield SourceRecord(item, "csv_file", locator)
                    except (json.JSONDecodeError, TypeError) as exc:
                        yield SourceRecord(dict(row), "csv_file", locator, f"invalid CSV metadata: {exc}")
        except (OSError, UnicodeError, csv.Error) as exc:
            yield SourceRecord(None, "csv_file", str(path), f"source read error: {exc}")


@dataclass(frozen=True, slots=True)
class RESTAPIAdapter:
    """Fetch an event document from an HTTP endpoint using a bounded timeout."""

    url: str
    timeout_seconds: float = 10.0
    headers: Mapping[str, str] | None = None

    def records(self) -> Iterable[SourceRecord]:
        request = Request(self.url, headers=dict(self.headers or {}), method="GET")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
                content_type = response.headers.get("Content-Type", "").lower()
                is_jsonl = any(marker in content_type for marker in ("jsonl", "ndjson")) or self.url.lower().split("?", 1)[0].endswith((".jsonl", ".ndjson"))
            yield from _decoded_json_records(body, "rest_api", self.url, is_jsonl)
        except (HTTPError, URLError, TimeoutError, OSError, UnicodeError) as exc:
            yield SourceRecord(None, "rest_api", self.url, f"HTTP source error: {exc}")


@dataclass(frozen=True, slots=True)
class LiveEventAdapter:
    """Adapt an iterable of live or simulated event objects to source records."""

    events: Iterable[Any]
    source_name: str = "live"

    def records(self) -> Iterable[SourceRecord]:
        for index, event in enumerate(self.events, 1):
            if hasattr(event, "to_dict"):
                event = event.to_dict()
            yield SourceRecord(event, self.source_name, str(index))
