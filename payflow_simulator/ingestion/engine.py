"""Batch ingestion orchestration, validation, quarantine, and observability."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .adapters import SourceAdapter, SourceRecord
from .normalization import normalize_event
from .storage import EventStore


@dataclass(frozen=True, slots=True)
class Rejection:
    """A rejected input record retained with its provenance and reason."""

    adapter: str
    locator: str
    reason: str
    raw_record: Any


@dataclass(frozen=True, slots=True)
class IngestionReport:
    """Summary of one ingestion run."""

    received: int
    accepted: int
    rejected: int
    duplicates: int
    duration_seconds: float
    events_per_second: float

    def to_dict(self) -> dict[str, object]:
        """Serialize report metrics without embedding all rejected data."""
        return {
            "received": self.received,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "duplicates": self.duplicates,
            "duration_seconds": self.duration_seconds,
            "events_per_second": self.events_per_second,
        }


class IngestionEngine:
    """Consume source adapters and independently handle every source record."""

    def __init__(self, store: EventStore, quarantine_path: str | Path):
        self.store = store
        self.quarantine_path = Path(quarantine_path)

    def ingest(self, adapter: SourceAdapter | Iterable[SourceRecord]) -> IngestionReport:
        """Ingest a batch, quarantining failures and deduplicating by event ID."""
        started = time.perf_counter()
        received = accepted = rejected = duplicates = 0
        records = adapter.records() if hasattr(adapter, "records") else adapter
        try:
            for record in records:
                received += 1
                if record.error:
                    rejected += 1
                    self._quarantine(Rejection(record.adapter, record.locator, record.error, record.data))
                    continue
                try:
                    event = normalize_event(record.data)
                except (TypeError, ValueError) as exc:
                    rejected += 1
                    item = Rejection(record.adapter, record.locator, str(exc), record.data)
                    self._quarantine(item)
                    continue
                # Persistence errors are operational failures, not bad input;
                # let them surface instead of misclassifying/quarantining data.
                if self.store.insert_if_new(event, record.adapter, record.locator):
                    accepted += 1
                else:
                    duplicates += 1
        finally:
            self.store.flush()
        duration = time.perf_counter() - started
        rate = received / duration if duration > 0 else 0.0
        return IngestionReport(received, accepted, rejected, duplicates, duration, rate)

    def _quarantine(self, rejection: Rejection) -> None:
        self.quarantine_path.parent.mkdir(parents=True, exist_ok=True)
        entry = asdict(rejection)
        with self.quarantine_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(entry, sort_keys=True, default=repr, separators=(",", ":")) + "\n")
