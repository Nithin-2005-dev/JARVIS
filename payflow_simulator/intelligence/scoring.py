"""Detector score semantics; raw outputs remain separate and non-probabilistic."""
from __future__ import annotations

from typing import Any, Mapping


def score_description(detector: str, score: Any, threshold: Any = None) -> dict[str, Any]:
    """Describe a detector's own scale without aggregating incompatible scores."""
    if detector == "rolling_mean_standard_deviation":
        return {"score": score, "scale": "absolute standard deviations from strictly-prior mean",
                "threshold": threshold, "is_probability": False}
    if detector == "isolation_forest":
        return {"score": score, "scale": "normalized expected isolation path score",
                "threshold": threshold, "is_probability": False}
    if detector == "approximate_token_similarity":
        return {"score": score, "scale": "Jaccard token similarity", "threshold": threshold, "is_probability": False}
    return {"score": score, "scale": "detector-specific or support count", "threshold": threshold, "is_probability": False}


def preserve_detector_outputs(outputs: Mapping[str, Any]) -> dict[str, Any]:
    """Return detector outputs keyed by detector; no cross-detector score is produced."""
    return {str(name): value for name, value in sorted(outputs.items())}

