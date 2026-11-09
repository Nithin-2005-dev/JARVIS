"""Configurable rule-based event taxonomy; deliberately not causal analysis."""

from __future__ import annotations

import re
from typing import Any, Mapping

from ..models import Event, EventType
from .config import ClassificationRule, ProcessingConfig


class EventClassifier:
    """Apply every matching configured rule and report unmatched event types."""

    def __init__(self, config: ProcessingConfig):
        self.rules = tuple(sorted(config.classification_rules, key=lambda item: (item.priority, item.rule_id)))

    def classify(self, event: Event | Mapping[str, Any]) -> dict[str, Any]:
        """Return categories and matching rule IDs for an event mapping."""
        value = event.to_dict() if isinstance(event, Event) else event
        event_type = str(value.get("event_type", ""))
        severity = str(value.get("severity", "")).upper()
        service = str(value.get("service", ""))
        message = str(value.get("message", ""))
        matched = [rule for rule in self.rules if self._matches(rule, event_type, severity, service, message)]
        categories = list(dict.fromkeys(rule.category for rule in matched))
        known_types = {event_type for rule in self.rules for event_type in rule.event_types}
        # Stage 1/2 event types with no rule are known but uncategorized. A truly
        # unfamiliar type is explicitly exposed rather than silently discarded.
        stage_types = {item.value for item in EventType}
        unknown = event_type not in stage_types and event_type not in known_types
        if unknown and not categories:
            categories.append("application_errors")
        elif not categories:
            categories.append("uncategorized")
        return {"categories": categories, "rule_ids": [rule.rule_id for rule in matched], "unknown_event_type": unknown}

    @staticmethod
    def _matches(rule: ClassificationRule, event_type: str, severity: str, service: str, message: str) -> bool:
        return (
            (not rule.event_types or event_type in rule.event_types)
            and (not rule.severities or severity in rule.severities)
            and (not rule.services or service in rule.services)
            and (rule.message_regex is None or re.search(rule.message_regex, message) is not None)
        )
