"""Typed configuration and finding records for Stage 7."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class IntelligenceConfig:
    window_seconds: int = 300
    rolling_lookback_windows: int = 100
    minimum_baseline_windows: int = 4
    statistical_threshold: float = 3.0
    isolation_trees: int = 48
    isolation_sample_size: int = 64
    isolation_minimum_samples: int = 12
    random_seed: int = 17
    pattern_minimum_support: int = 3
    pattern_similarity_threshold: float = 0.8
    pattern_pair_limit: int = 2000
    cross_service_max_lag_seconds: int = 900
    cross_service_max_relationships: int = 500
    cross_service_max_candidate_pairs: int = 5000
    version: str = "intelligence-v1"

    def __post_init__(self) -> None:
        if self.window_seconds < 1 or self.minimum_baseline_windows < 2 or self.rolling_lookback_windows < self.minimum_baseline_windows:
            raise ValueError("window_seconds must be positive; lookback must be at least the baseline minimum")
        if self.statistical_threshold <= 0 or self.isolation_trees < 1 or self.isolation_sample_size < 2 or self.isolation_minimum_samples < 2:
            raise ValueError("detector thresholds and sample counts must be positive")
        if self.pattern_minimum_support < 2 or not 0 <= self.pattern_similarity_threshold <= 1 or self.pattern_pair_limit < 1:
            raise ValueError("invalid pattern discovery settings")
        if self.cross_service_max_relationships < 1 or self.cross_service_max_candidate_pairs < 1:
            raise ValueError("cross-service relationship and candidate caps must be positive")
        if self.cross_service_max_lag_seconds < 0:
            raise ValueError("cross-service max lag cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FeatureWindow:
    service_id: str
    window_start: str
    window_end: str
    event_count: int
    error_rate: float | None
    critical_count: int
    warning_count: int
    event_type_counts: dict[str, int]
    severity_counts: dict[str, int]
    signature_counts: dict[str, int]
    resource_counts: dict[str, int]
    mean_interarrival_seconds: float | None
    latency_mean_ms: float | None
    missing_fields: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    source_timestamps: tuple[str, ...]
    feature_provenance: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def numeric(self) -> dict[str, float | None]:
        return {"event_count": float(self.event_count), "error_rate": self.error_rate,
                "critical_count": float(self.critical_count), "warning_count": float(self.warning_count),
                "mean_interarrival_seconds": self.mean_interarrival_seconds,
                "latency_mean_ms": self.latency_mean_ms}


@dataclass(frozen=True, slots=True)
class IntelligenceFinding:
    finding_id: str
    finding_type: str
    affected_service_ids: tuple[str, ...]
    window_start: str | None
    window_end: str | None
    observed_facts: dict[str, Any]
    expected_baseline: dict[str, Any] | None
    detector: str
    score: float | None
    score_interpretation: str
    evidence_references: tuple[dict[str, Any], ...]
    related_incidents: tuple[str, ...]
    related_rca_reports: tuple[str, ...]
    related_blast_radius_analyses: tuple[str, ...]
    limitations: tuple[str, ...]
    uncertainty_status: str
    model_version: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
