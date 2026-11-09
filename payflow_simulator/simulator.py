"""Deterministic PayFlow transaction scenarios and JSONL output."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from uuid import UUID

from .models import Event, EventType, Severity, validate_event

SERVICES = ("api-gateway", "authentication-service", "payment-service", "database-service", "notification-service")


class Scenario(str):
    """Supported repeatable scenario identifiers."""

    NORMAL = "normal"
    DB_POOL_EXHAUSTION = "db_pool_exhaustion"
    DOWNSTREAM_FAILURE = "downstream_failure"
    ALL = "all"


@dataclass
class Simulator:
    """Generate deterministic event streams using a seeded RNG and fixed start time."""

    seed: int = 42
    start_time: datetime = datetime(2025, 1, 15, 12, 0, tzinfo=timezone.utc)
    db_pool_size: int = 10

    def __post_init__(self) -> None:
        if self.start_time.tzinfo is None:
            raise ValueError("start_time must be timezone-aware")
        if self.db_pool_size < 1:
            raise ValueError("db_pool_size must be positive")
        self._rng = random.Random(self.seed)
        self._counter = 0

    def generate(self, scenario: str = Scenario.ALL, payments: int = 3) -> list[Event]:
        """Generate events for one named scenario or all scenarios in stable order."""
        if scenario not in (Scenario.NORMAL, Scenario.DB_POOL_EXHAUSTION, Scenario.DOWNSTREAM_FAILURE, Scenario.ALL):
            raise ValueError(f"unknown scenario: {scenario}")
        if payments < 1:
            raise ValueError("payments must be positive")
        scenarios = [Scenario.NORMAL, Scenario.DB_POOL_EXHAUSTION, Scenario.DOWNSTREAM_FAILURE] if scenario == Scenario.ALL else [scenario]
        events: list[Event] = []
        for scenario_index, name in enumerate(scenarios):
            for payment_no in range(1, payments + 1):
                events.extend(self._payment(name, scenario_index, payment_no))
        return events

    def _payment(self, scenario: str, scenario_index: int, payment_no: int) -> list[Event]:
        trace = self._uuid(scenario_index * 1000 + payment_no)
        payment_id = f"pay-{scenario_index + 1:02d}-{payment_no:04d}"
        # Each transaction has a fixed monotonic schedule. A few milliseconds of
        # seeded jitter preserve realistic ordering without compromising repeatability.
        base = self.start_time + timedelta(seconds=scenario_index * 60 + (payment_no - 1) * 2)
        cursor = 0
        out: list[Event] = []

        def emit(service: str, kind: EventType, severity: Severity, message: str, metadata: dict[str, object]) -> None:
            nonlocal cursor
            cursor += 1
            moment = base + timedelta(milliseconds=cursor * 20 + self._rng.randrange(0, 8))
            event = Event(self._uuid(self._counter), moment.isoformat(timespec="milliseconds").replace("+00:00", "Z"), service, kind, severity, message, "simulator", trace, metadata)
            self._counter += 1
            validate_event(event.to_dict())
            out.append(event)

        common = {"payment_id": payment_id, "scenario": scenario}
        emit("api-gateway", EventType.REQUEST_RECEIVED, Severity.INFO, "Payment request received", {**common, "method": "POST", "path": "/payments"})
        emit("authentication-service", EventType.AUTHENTICATED, Severity.INFO, "Client authenticated", {**common, "principal": "merchant-demo"})
        emit("payment-service", EventType.PAYMENT_CREATED, Severity.INFO, "Payment intent created", {**common, "amount_minor": self._rng.randrange(1200, 50000), "currency": "USD"})

        fail_db = scenario == Scenario.DB_POOL_EXHAUSTION and payment_no == 1
        fail_downstream = scenario == Scenario.DOWNSTREAM_FAILURE and payment_no == 1
        if fail_db:
            emit("database-service", EventType.DB_POOL_EXHAUSTED, Severity.CRITICAL, "Database connection pool exhausted", {**common, "pool_size": self.db_pool_size, "active_connections": self.db_pool_size, "wait_ms": 2000})
            emit("payment-service", EventType.REQUEST_FAILED, Severity.ERROR, "Payment failed while acquiring database connection", {**common, "reason": "db_pool_exhausted"})
            emit("api-gateway", EventType.REQUEST_FAILED, Severity.ERROR, "Payment request returned an error", {**common, "http_status": 503})
            return out

        emit("database-service", EventType.DB_QUERY, Severity.INFO, "Payment record persisted", {**common, "operation": "insert", "table": "payments"})
        emit("payment-service", EventType.PAYMENT_PROCESSED, Severity.INFO, "Payment authorized", {**common, "result": "approved"})
        if fail_downstream:
            emit("notification-service", EventType.DOWNSTREAM_FAILURE, Severity.ERROR, "Notification provider timed out", {**common, "dependency": "mail-provider", "timeout_ms": 3000, "retryable": True})
            emit("payment-service", EventType.PAYMENT_PROCESSED, Severity.WARNING, "Payment succeeded; notification queued for retry", {**common, "notification_status": "queued"})
        else:
            emit("notification-service", EventType.NOTIFICATION_SENT, Severity.INFO, "Payment receipt notification sent", {**common, "channel": "email"})
        emit("api-gateway", EventType.REQUEST_COMPLETED, Severity.INFO, "Payment request completed", {**common, "http_status": 201})
        return out

    def _uuid(self, number: int) -> str:
        """Build stable UUID-shaped IDs from the seed namespace and sequence."""
        namespace = UUID(int=self.seed % (1 << 128))
        return str(UUID(int=(namespace.int ^ (number + 1)) % (1 << 128)))


def write_jsonl(events: Iterable[Event], path: str | Path) -> int:
    """Validate events and write UTF-8 JSON Lines; return the number written."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with target.open("w", encoding="utf-8", newline="\n") as stream:
        for event in events:
            row = event.to_dict()
            validate_event(row)
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            count += 1
    return count
