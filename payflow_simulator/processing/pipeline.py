"""Composable four-stage event processing pipeline."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from ..models import EventType, event_from_dict
from .classification import EventClassifier
from .config import ProcessingConfig
from .enrichment import EventEnricher
from .patterns import PatternDetector
from .temporal import TemporalProcessor, format_utc, parse_utc


class PipelineFailure(RuntimeError):
    """Stage-attributed processing failure with completed stage history."""

    def __init__(self, stage: str, cause: Exception, history: list[dict[str, str]]):
        super().__init__(f"{stage}: {cause}")
        self.stage = stage
        self.cause = cause
        self.history = history


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Processed payload and transactional sidecar records."""

    payload: dict[str, Any]
    observation: dict[str, Any]
    watermark: str
    stage_history: list[dict[str, str]]
    stage_durations_seconds: dict[str, float]
    pattern_count: int


class ProcessingPipeline:
    """Run enrichment → classification → temporal → pattern stages in order."""

    def __init__(
        self,
        config: ProcessingConfig,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        enricher: EventEnricher | None = None,
        classifier: EventClassifier | None = None,
        temporal: TemporalProcessor | None = None,
        detector: PatternDetector | None = None,
    ):
        self.config = config
        self.clock = clock
        self.enricher = enricher or EventEnricher(config)
        self.classifier = classifier or EventClassifier(config)
        self.temporal = temporal or TemporalProcessor(config)
        self.detector = detector or PatternDetector(config.patterns)

    def process(
        self,
        raw_event: Mapping[str, Any],
        source_order: int,
        previous_max_event_time: str | None,
        pattern_context: Callable[[str, Mapping[str, Any]], dict[str, Any]],
    ) -> PipelineResult:
        """Execute stages, preserving input verbatim and attaching measured timings."""
        history: list[dict[str, str]] = []
        durations: dict[str, float] = {}

        def run_stage(name: str, operation: Callable[[], Any]) -> Any:
            started = time.perf_counter()
            try:
                result = operation()
            except Exception as exc:
                raise PipelineFailure(name, exc, list(history)) from exc
            durations[name] = time.perf_counter() - started
            history.append({"stage": name, "status": "succeeded", "detail": ""})
            return result

        source_event = run_stage("input_validation", lambda: self._validated_source_event(raw_event))
        processing_timestamp = format_utc(self.clock())
        enrichment = run_stage("enrichment", lambda: self.enricher.enrich(source_event, processing_timestamp))
        classification = run_stage("classification", lambda: self.classifier.classify(source_event))
        temporal = run_stage("temporal", lambda: self.temporal.process(source_event, processing_timestamp, previous_max_event_time))
        window_start = temporal["window_start"]
        observation = self.detector.observation(source_event, window_start)
        observation["source_order"] = source_order

        def detect_patterns() -> list[dict[str, Any]]:
            context = pattern_context(window_start, observation)
            return self.detector.detect(source_event, context, window_start)

        patterns = run_stage("pattern_detection", detect_patterns)
        event_time = parse_utc(temporal["event_timestamp"])
        previous_max = parse_utc(previous_max_event_time) if previous_max_event_time else None
        watermark = format_utc(max(event_time, previous_max) if previous_max else event_time)
        payload: dict[str, Any] = {
            "schema_version": "1.0",
            "event_id": source_event["event_id"],
            "original_event": dict(raw_event),
            "processing_timestamp": processing_timestamp,
            "enrichment": enrichment,
            "classification": classification,
            "temporal": temporal,
            "patterns": patterns,
        }
        return PipelineResult(payload, observation, watermark, history, durations, len(patterns))

    @staticmethod
    def _validated_source_event(raw_event: Mapping[str, Any]) -> dict[str, Any]:
        """Validate the canonical contract while preserving unfamiliar type labels."""
        raw_type = raw_event.get("event_type")
        if isinstance(raw_type, str) and raw_type not in {item.value for item in EventType}:
            probe = dict(raw_event)
            probe["event_type"] = EventType.REQUEST_RECEIVED.value
            normalized = event_from_dict(probe).to_dict()
            normalized["event_type"] = raw_type
            return normalized
        return event_from_dict(raw_event).to_dict()
