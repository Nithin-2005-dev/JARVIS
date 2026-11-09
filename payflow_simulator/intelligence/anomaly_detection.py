"""Statistical rolling detector and deterministic Isolation Forest detector."""
from __future__ import annotations

import hashlib
import math
import random
from statistics import mean, pstdev
from typing import Any, Mapping, Sequence

from .baseline import NUMERIC_FEATURES
from .models import IntelligenceConfig

ISOLATION_VERSION = "isolation-forest-small-v1"


def detect_anomalies(features: Sequence[Mapping[str, Any]], baselines: Sequence[Mapping[str, Any]],
                     config: IntelligenceConfig) -> dict[str, Any]:
    baseline_index = {(b["service_id"], b["target_window_start"]): b for b in baselines}
    ordered = sorted(features, key=lambda f: (str(f["service_id"]), str(f["window_start"])))
    prior_by_service: dict[str, list[Mapping[str, Any]]] = {}
    statistical: list[dict[str, Any]] = []
    forest: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    for feature in ordered:
        service, window = str(feature["service_id"]), str(feature["window_start"])
        baseline = baseline_index[(service, window)]
        history = prior_by_service.setdefault(service, [])
        training_history = history[-config.rolling_lookback_windows:]
        all_event_ids = list(feature.get("source_event_ids", []))
        evidence = [{"event_id": event_id, "window_start": window, "evidence_kind": "observed_source_event"}
                   for event_id in all_event_ids[:100]]
        if len(all_event_ids) > 100:
            evidence.append({"service_id": service, "window_start": window, "evidence_kind": "feature_window_reference",
                "total_source_event_count": len(all_event_ids), "sampled_event_references": 100,
                "omitted_event_references": len(all_event_ids)-100,
                "note": "Full source event IDs remain in the persisted feature window; references are sampled here to bound finding size."})
        if baseline["status"] != "ready":
            statistical.append(_insufficient(feature, baseline, "rolling_statistics", evidence,
                f"Need {baseline['minimum_required_windows']} strictly prior windows; observed {baseline['training_window_count']}.", config))
        else:
            for name in NUMERIC_FEATURES:
                observed = feature.get(name)
                summary = baseline["features"].get(name, {})
                expected, deviation = summary.get("mean"), summary.get("standard_deviation")
                if observed is None or expected is None:
                    continue
                difference = abs(float(observed) - float(expected))
                if deviation is None or float(deviation) == 0:
                    score = 0.0 if difference == 0 else config.statistical_threshold + 1.0
                    zero_variance = True
                else:
                    score = difference / float(deviation)
                    zero_variance = False
                if score >= config.statistical_threshold:
                    statistical.append({"finding_type": "statistical_anomaly", "service_id": service,
                        "window_start": window, "window_end": feature["window_end"], "feature": name,
                        "observed_value": observed, "expected_baseline": {"mean": expected,
                            "standard_deviation": deviation, "training_windows": baseline["training_window_starts"]},
                        "deviation_score": round(score, 6), "detector": "rolling_mean_standard_deviation",
                        "detector_version": "rolling-z-v1", "score_interpretation": "absolute standard deviations from strictly prior mean; zero-variance changes receive threshold+1 sentinel",
                        "evidence_references": evidence, "limitations": ["Window aggregation can hide within-window ordering.", "Historical mean and variance are sensitive to regime changes."],
                        "uncertainty_status": "heuristic_anomaly_signal", "zero_variance_comparison": zero_variance,
                        "baseline_version": baseline["baseline_version"], "model_version": config.version})
        if len(training_history) < config.isolation_minimum_samples:
            forest.append(_insufficient(feature, baseline, "isolation_forest", evidence,
                f"Need {config.isolation_minimum_samples} strictly prior feature windows; observed {len(training_history)}.", config,
                detector_version=ISOLATION_VERSION))
        else:
            usable = [name for name in NUMERIC_FEATURES if all(row.get(name) is not None for row in training_history) and feature.get(name) is not None]
            if not usable:
                forest.append(_insufficient(feature, baseline, "isolation_forest", evidence,
                    "No numeric feature is present throughout both training history and target window.", config,
                    detector_version=ISOLATION_VERSION))
            else:
                train = [[float(row[name]) for name in usable] for row in training_history]
                target = [float(feature[name]) for name in usable]
                seed_material = f"{config.random_seed}|{service}|{window}|{config.version}"
                seed = int(hashlib.sha256(seed_material.encode()).hexdigest()[:16], 16)
                score, model = isolation_forest_score(train, target, trees=config.isolation_trees,
                    sample_size=config.isolation_sample_size, seed=seed)
                artifact_id = hashlib.sha256(f"{seed_material}|{usable}|{len(train)}".encode()).hexdigest()
                artifacts.append({"artifact_id": artifact_id, "detector": "isolation_forest",
                    "detector_version": ISOLATION_VERSION, "service_id": service, "target_window_start": window,
                    "training_window_starts": [row["window_start"] for row in training_history], "features": usable,
                    "training_sample_count": len(train), "seed": seed, "trees": model})
                forest.append({"finding_type": "ml_anomaly" if score >= 0.62 else "ml_baseline_observation",
                    "service_id": service, "window_start": window, "window_end": feature["window_end"],
                    "feature": "multivariate_window_vector", "observed_value": dict(zip(usable, target)),
                    "expected_baseline": {"training_window_count": len(train), "training_window_starts": [row["window_start"] for row in training_history], "features": usable},
                    "deviation_score": round(score, 6), "detector": "isolation_forest",
                    "detector_version": ISOLATION_VERSION,
                    "score_interpretation": "random-partition path-length anomaly score; threshold 0.62 is an explicit heuristic, not a probability",
                    "evidence_references": evidence, "limitations": ["Small history and random partitioning can make rankings unstable.", "Training uses only earlier windows and does not model seasonality."],
                    "uncertainty_status": "heuristic_anomaly_signal" if score >= 0.62 else "no_anomaly_flag",
                    "model_artifact_id": artifact_id, "model_version": config.version})
        history.append(feature)
    return {"statistical_findings": statistical, "machine_learning_findings": forest,
            "model_artifacts": artifacts,
            "detector_comparison": {"statistical": {"name": "rolling mean/std", "raw_score": "absolute z-like deviation", "threshold": config.statistical_threshold},
                "machine_learning": {"name": "Isolation Forest", "raw_score": "normalized expected partition path length", "threshold": 0.62,
                    "implementation": ISOLATION_VERSION, "scaling": "not applied; axis-aligned random partitions are invariant to positive affine scaling"}}}


def isolation_forest_score(training: Sequence[Sequence[float]], target: Sequence[float], *, trees: int,
                           sample_size: int, seed: int) -> tuple[float, list[dict[str, Any]]]:
    """Fit random isolation trees on history and score one unseen vector."""
    if len(training) < 2 or not training[0]:
        raise ValueError("Isolation Forest requires at least two non-empty training vectors")
    rng = random.Random(seed)
    size = min(len(training), sample_size)
    limit = max(1, math.ceil(math.log2(size)))
    forest: list[dict[str, Any]] = []
    path_lengths = []
    for _ in range(trees):
        sample = rng.sample(list(training), size)
        tree = _build_tree(sample, 0, limit, rng)
        forest.append(tree)
        path_lengths.append(_path_length(tree, target, 0))
    average = sum(path_lengths) / len(path_lengths)
    normalizer = _harmonic(size - 1) * 2 - (2 * (size - 1) / size) if size > 2 else 1.0
    score = 2 ** (-average / max(normalizer, 1e-9))
    return min(1.0, max(0.0, score)), forest


def _build_tree(rows: Sequence[Sequence[float]], depth: int, max_depth: int, rng: random.Random) -> dict[str, Any]:
    if len(rows) <= 1 or depth >= max_depth:
        return {"size": len(rows)}
    dimensions = list(range(len(rows[0])))
    rng.shuffle(dimensions)
    for dimension in dimensions:
        values = [row[dimension] for row in rows]
        low, high = min(values), max(values)
        if low < high:
            split = rng.uniform(low, high)
            left = [row for row in rows if row[dimension] < split]
            right = [row for row in rows if row[dimension] >= split]
            if left and right:
                return {"feature_index": dimension, "split": split,
                        "left": _build_tree(left, depth + 1, max_depth, rng),
                        "right": _build_tree(right, depth + 1, max_depth, rng)}
    return {"size": len(rows)}


def _path_length(tree: Mapping[str, Any], target: Sequence[float], depth: int) -> float:
    if "size" in tree:
        return depth + _harmonic(max(0, int(tree["size"]) - 1))
    child = tree["left"] if target[int(tree["feature_index"])] < float(tree["split"]) else tree["right"]
    return _path_length(child, target, depth + 1)


def _harmonic(number: int) -> float:
    if number <= 0: return 0.0
    if number < 10000: return sum(1.0 / value for value in range(1, number + 1))
    return math.log(number) + 0.5772156649 + 1 / (2 * number) - 1 / (12 * number**2)


def _insufficient(feature: Mapping[str, Any], baseline: Mapping[str, Any], detector: str,
                  evidence: list[dict[str, Any]], reason: str, config: IntelligenceConfig,
                  detector_version: str | None = None) -> dict[str, Any]:
    return {"finding_type": "insufficient_data", "service_id": feature["service_id"],
        "window_start": feature["window_start"], "window_end": feature["window_end"],
        "feature": None, "observed_value": None, "expected_baseline": None,
        "deviation_score": None, "detector": detector, "detector_version": detector_version or "rolling-z-v1",
        "score_interpretation": "no anomaly score produced", "evidence_references": evidence,
        "limitations": [reason], "uncertainty_status": "insufficient_data",
        "baseline_version": baseline.get("baseline_version"), "model_version": config.version}
