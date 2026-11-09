"""Service registry enrichment without modifying the source event."""

from __future__ import annotations

from typing import Any, Mapping

from ..models import Event
from .config import ProcessingConfig


class EventEnricher:
    """Attach registry and deployment context as a separate enrichment object."""

    def __init__(self, config: ProcessingConfig):
        self.config = config

    def enrich(self, event: Event | Mapping[str, Any], processing_timestamp: str) -> dict[str, Any]:
        """Return enrichment metadata while retaining the original mapping elsewhere."""
        source = event.to_dict() if isinstance(event, Event) else dict(event)
        service = source["service"]
        registry = self.config.service_registry
        entry = registry.get(service)
        return {
            "environment": self.config.environment,
            "application": self.config.application,
            "service_metadata": dict(entry) if entry is not None else {},
            "enrichment_provenance": {
                "registry_version": self.config.registry_version,
                "registry_match": entry is not None,
                "source_service": service,
                "enriched_at": processing_timestamp,
            },
        }
