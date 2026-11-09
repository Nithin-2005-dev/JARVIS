"""Recoverable processing engine over the local ingested-event queue."""

from __future__ import annotations

import logging
import time
from uuid import uuid4
from dataclasses import asdict, dataclass, field
from typing import Any

from .config import ProcessingConfig
from .pipeline import PipelineFailure, ProcessingPipeline
from .storage import ProcessingStore

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProcessingReport:
    """Counters and latency/throughput measurements for one processing run."""

    received: int
    processed: int
    failed: int
    patterns_emitted: int
    reprocessed: int
    duration_seconds: float
    events_per_second: float
    average_event_latency_ms: float
    stage_durations_seconds: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProcessingEngine:
    """Claim ingested rows, process independently, and persist recoverable state."""

    def __init__(self, store: ProcessingStore, config: ProcessingConfig | None = None, pipeline: ProcessingPipeline | None = None):
        self.store = store
        self.config = config or ProcessingConfig()
        self.pipeline = pipeline or ProcessingPipeline(self.config)

    def run(self, limit: int | None = None, reprocess: bool = False) -> ProcessingReport:
        """Process pending events; failed events remain available to a later run."""
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        started = time.perf_counter()
        received = processed = failed = patterns_emitted = reprocessed_count = 0
        latency_seconds = 0.0
        stage_totals: dict[str, float] = {}
        run_id = str(uuid4())
        remaining = limit
        while remaining is None or remaining > 0:
            batch_limit = self.config.batch_size if remaining is None else min(self.config.batch_size, remaining)
            claims = self.store.claim_batch(batch_limit, self.config.stale_claim_seconds, reprocess, run_id)
            if not claims:
                break
            for claim in claims:
                received += 1
                if reprocess:
                    reprocessed_count += 1
                event_started = time.perf_counter()
                previous_watermark = self.store.watermark_before(claim.source_order)
                try:
                    result = self.pipeline.process(claim.payload, claim.source_order, previous_watermark, self.store.pattern_context)
                    self.store.complete(claim.event_id, claim.attempt, result.payload, result.observation, result.watermark, result.stage_history)
                except PipelineFailure as exc:
                    failed += 1
                    self.store.fail(claim.event_id, claim.attempt, exc.stage, str(exc.cause), exc.history)
                    LOGGER.warning("event_processing_failed", extra={"event_id": claim.event_id, "attempt": claim.attempt, "stage": exc.stage, "error": str(exc.cause)})
                except Exception as exc:
                    # Persistence failures surface after marking recovery state when
                    # possible; no input row is deleted from the ingestion table.
                    failed += 1
                    self.store.fail(claim.event_id, claim.attempt, "persistence", str(exc), [])
                    LOGGER.exception("event_processing_persistence_failed", extra={"event_id": claim.event_id, "attempt": claim.attempt})
                else:
                    processed += 1
                    patterns_emitted += result.pattern_count
                    LOGGER.info("event_processed", extra={"event_id": claim.event_id, "attempt": claim.attempt, "pattern_count": result.pattern_count})
                    for stage, seconds in result.stage_durations_seconds.items():
                        stage_totals[stage] = stage_totals.get(stage, 0.0) + seconds
                finally:
                    latency_seconds += time.perf_counter() - event_started
            if remaining is not None:
                remaining -= len(claims)
        duration = time.perf_counter() - started
        rate = received / duration if duration > 0 else 0.0
        average_latency = (latency_seconds / received * 1000) if received else 0.0
        return ProcessingReport(received, processed, failed, patterns_emitted, reprocessed_count, duration, rate, average_latency, stage_totals)
