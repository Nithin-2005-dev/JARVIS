"""Deterministic heuristic ordering; scores are not success probabilities."""
from __future__ import annotations

from typing import Any, Mapping
from .models import RecommendationConfig


def rank_breakdown(*, severity: float, evidence: float, urgency: float, criticality: float,
                   potential_impact: float, benefit: float, prerequisites: float, risk: str,
                   config: RecommendationConfig) -> dict[str, float]:
    factors = {"severity": severity, "evidence": evidence, "urgency": urgency,
               "criticality": criticality, "potential_impact": potential_impact,
               "benefit": benefit, "prerequisites": prerequisites}
    if any(not 0 <= float(v) <= 1 for v in factors.values()): raise ValueError("ranking factors must be in [0, 1]")
    weighted = {f"weighted_{key}": float(value) * float(config.score_weights.get(key, 0.0)) for key, value in factors.items()}
    raw = sum(weighted.values()) - float(config.risk_penalties.get(risk, .3))
    # Risk gate and class ordering ensure investigations precede risky action suggestions.
    return {**{k: round(v, 6) for k, v in weighted.items()}, "risk_penalty": float(config.risk_penalties.get(risk, .3)),
            "score": round(max(0.0, min(1.0, raw)), 6)}


def order_recommendations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kind_order = {"investigation": 0, "diagnostic": 1, "monitoring": 2, "mitigation": 3, "recovery": 4,
                  "prevention": 5, "capacity": 6, "configuration": 7, "security": 8}
    return sorted(items, key=lambda x: (kind_order.get(x["recommendation_type"], 9), -float(x["score"]), x["recommendation_id"]))
