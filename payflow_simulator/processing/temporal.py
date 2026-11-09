"""Event-time ordering, late-arrival flags, and fixed UTC window assignment."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .config import ProcessingConfig


def parse_utc(value: str) -> datetime:
    """Parse timezone-aware ISO-8601 timestamp and return UTC datetime."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("event timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def format_utc(value: datetime) -> str:
    """Format UTC timestamps with a Z suffix and trimmed fractional seconds."""
    value = value.astimezone(timezone.utc)
    fraction = f".{value.microsecond:06d}".rstrip("0") if value.microsecond else ""
    return value.strftime("%Y-%m-%dT%H:%M:%S") + fraction + "Z"


class TemporalProcessor:
    """Annotate arrival order and fixed event-time windows without reordering input."""

    def __init__(self, config: ProcessingConfig):
        self.config = config

    def process(self, event: Mapping[str, Any], processing_timestamp: str, previous_max_event_time: str | None) -> dict[str, Any]:
        event_time = parse_utc(str(event["timestamp"]))
        previous_max = parse_utc(previous_max_event_time) if previous_max_event_time else None
        out_of_order = previous_max is not None and event_time < previous_max
        late = previous_max is not None and event_time < previous_max - timedelta(seconds=self.config.allowed_lateness_seconds)
        epoch = int(event_time.timestamp())
        start_epoch = (epoch // self.config.window_seconds) * self.config.window_seconds
        start = datetime.fromtimestamp(start_epoch, tz=timezone.utc)
        end = start + timedelta(seconds=self.config.window_seconds)
        return {
            "event_timestamp": format_utc(event_time),
            "processing_timestamp": processing_timestamp,
            "out_of_order": out_of_order,
            "late_arrival": late,
            "previous_max_event_timestamp": format_utc(previous_max) if previous_max else None,
            "window_start": format_utc(start),
            "window_end": format_utc(end),
        }
