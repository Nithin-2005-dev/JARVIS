"""Leakage-safe rolling service baselines and stable baseline versions."""
from __future__ import annotations

import hashlib
import json
from statistics import mean, pstdev
from typing import Any, Mapping, Sequence

from .models import IntelligenceConfig

NUMERIC_FEATURES = ("event_count", "error_rate", "critical_count", "warning_count", "mean_interarrival_seconds", "latency_mean_ms")


def build_baselines(features: Sequence[Mapping[str, Any]], config: IntelligenceConfig) -> dict[str, Any]:
    """Build one strictly-prior baseline for every service/window feature row."""
    ordered = sorted(features, key=lambda f: (str(f["service_id"]), str(f["window_start"])))
    by_service: dict[str, list[Mapping[str, Any]]] = {}
    results = []
    for target in ordered:
        service = str(target["service_id"])
        prior = by_service.setdefault(service, [])
        history = prior[-config.rolling_lookback_windows:]
        enough = len(history) >= config.minimum_baseline_windows
        stats: dict[str, Any] = {}
        for name in NUMERIC_FEATURES:
            values = [float(row[name]) for row in history if row.get(name) is not None]
            stats[name] = {"mean": mean(values) if values else None,
                           "standard_deviation": pstdev(values) if len(values) >= 2 else None,
                           "sample_count": len(values)}
        distributions = {"severity": _severity_distribution(history),
                         "event_type": _event_type_distribution(history)}
        identity = {"service_id": service, "target_window": target["window_start"],
                    "training_window_starts": [row["window_start"] for row in history],
                    "configuration": config.to_dict(), "statistics": stats, "distributions": distributions}
        version = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        results.append({"baseline_version": version, "service_id": service,
            "target_window_start": target["window_start"], "training_window_count": len(history),
            "training_window_starts": [row["window_start"] for row in history],
            "status": "ready" if enough else "insufficient_data",
            "minimum_required_windows": config.minimum_baseline_windows,
            "features": stats, "severity_distribution": distributions["severity"],
            "event_type_distribution": distributions["event_type"],
            "leakage_guard": "Only strictly earlier service windows contribute; target and future windows are excluded. The retained history is capped by rolling_lookback_windows."})
        # Append only after baseline construction so the target never trains its own baseline.
        prior.append(target)
    return {"baselines": results, "baseline_version": config.version,
            "method": "rolling prior-window mean and population standard deviation",
            "time_of_day_grouping": {"status": "not_enabled", "reason": "Insufficient seasonality requirements are not specified; global service history is safer than a sparse fabricated subgroup."}}


def _distribution(rows: Sequence[Mapping[str, Any]], numerator: str, denominator: str) -> dict[str, float]:
    total_num = sum(float(row.get(numerator) or 0) for row in rows)
    total_den = sum(float(row.get(denominator) or 0) for row in rows)
    return {"high_severity_rate": total_num / total_den if total_den else 0.0}


def _severity_distribution(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    counts: dict[str,float]={}; total=0
    for row in rows:
        for level,count in row.get("severity_counts",{}).items():
            counts[str(level)]=counts.get(str(level),0.0)+float(count); total+=int(count)
    return {level:count/total for level,count in sorted(counts.items())} if total else {}


def _event_type_distribution(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    counts: dict[str, float] = {}
    total = 0
    for row in rows:
        types = row.get("event_type_counts", {})
        for name, count in types.items():
            counts[str(name)] = counts.get(str(name), 0.0) + float(count)
            total += int(count)
    return {key: value / total for key, value in sorted(counts.items())} if total else {}
