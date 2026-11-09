"""JSON formatter for structured processing logs."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any


class JSONLogFormatter(logging.Formatter):
    """Render standard log fields and structured `extra` fields as one JSON line."""

    RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        data.update({key: value for key, value in record.__dict__.items() if key not in self.RESERVED and not key.startswith("_")})
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, sort_keys=True, default=str, separators=(",", ":"))
