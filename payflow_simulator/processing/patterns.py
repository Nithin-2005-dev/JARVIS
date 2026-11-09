"""Window-local repeated-event signals, separate from incident correlation."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from .config import PatternThresholds


def failure_signature(event: Mapping[str, Any]) -> str:
    """Build a deterministic, non-causal signature for exact repeated messages."""
    normalized_message = re.sub(r"\s+", " ", str(event.get("message", "")).strip().lower())
    return f"{event.get('event_type', '')}|{event.get('severity', '')}|{normalized_message}"


class PatternDetector:
    """Detect count-based repetition and volume signals inside fixed event windows."""

    FAILURE_TYPES = {"db_pool_exhausted", "downstream_failure", "request_failed"}

    def __init__(self, thresholds: PatternThresholds):
        self.thresholds = thresholds

    def observation(self, event: Mapping[str, Any], window_start: str) -> dict[str, Any]:
        severity = str(event.get("severity", "")).upper()
        return {
            "event_id": event["event_id"],
            "window_start": window_start,
            "service": event["service"],
            "event_type": event["event_type"],
            "severity": severity,
            "signature": failure_signature(event),
            "is_failure": severity in {"ERROR", "CRITICAL"} or event["event_type"] in self.FAILURE_TYPES,
        }

    def detect(self, current: Mapping[str, Any], context: Mapping[str, Any], window_start: str) -> list[dict[str, Any]]:
        """Return count-threshold signals using bounded evidence summaries."""
        current_observation = self.observation(current, window_start)
        is_failure = bool(current_observation["is_failure"])
        signature_count = int(context["signature_failure_count"]) + int(is_failure)
        service_count = int(context["service_event_count"]) + 1
        services = set(context["signature_services"])
        services.add(current_observation["service"])
        signature_evidence = list(context["signature_evidence_ids"])
        if is_failure:
            signature_evidence.append(current_observation["event_id"])
        service_evidence = list(context["service_evidence_ids"])
        service_evidence.append(current_observation["event_id"])
        patterns: list[dict[str, Any]] = []
        signature_evidence = self._bounded_evidence(signature_evidence, current_observation["event_id"])
        service_evidence = self._bounded_evidence(service_evidence, current_observation["event_id"])
        matching_services = tuple(sorted(services))
        if is_failure and signature_count >= self.thresholds.repeated_error:
            patterns.append(self._pattern("repeated_error", current_observation, signature_count, signature_evidence, matching_services))
        if is_failure and signature_count >= self.thresholds.recurring_failure:
            patterns.append(self._pattern("recurring_failure_pattern", current_observation, signature_count, signature_evidence, matching_services))
        if service_count >= self.thresholds.frequency_spike:
            patterns.append(self._pattern("frequency_spike", current_observation, service_count, service_evidence, (current_observation["service"],)))
        if is_failure and len(services) >= self.thresholds.repeated_across_services:
            patterns.append(self._pattern("repeated_across_services", current_observation, signature_count, signature_evidence, tuple(sorted(services))))
        return patterns

    @staticmethod
    def _bounded_evidence(event_ids: Sequence[str], current_event_id: str) -> list[str]:
        prior = sorted(set(event_ids) - {current_event_id})[:19]
        return sorted(prior + [current_event_id])

    @staticmethod
    def _pattern(kind: str, observation: Mapping[str, Any], count: int, evidence_ids: Sequence[str], services: tuple[str, ...]) -> dict[str, Any]:
        return {
            "kind": kind,
            "window_start": observation["window_start"],
            "signature": observation["signature"],
            "count": count,
            "services": list(services),
            "evidence_event_ids": list(evidence_ids),
            "evidence_truncated": count > len(evidence_ids),
            "interpretation": "frequency/repetition signal only; no causal relationship inferred",
        }
