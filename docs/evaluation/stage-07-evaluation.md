# Stage 7 Evaluation

Reproduce artifacts with:

```bash
python3 -m payflow_simulator.intelligence.evaluation --output-dir data/evaluation
```

The generator produces 2,432 deterministic event records and 241 service/window feature rows across 12 scenario categories. It labels 27 anomalous service/windows, uses indices 0–19 as earlier history, and evaluates indices 20–39 (121 service/windows, 27 positive and 94 negative). Every tested baseline records only strictly earlier window starts; the final leakage assertion passed. Outputs are in `stage7_synthetic_events.jsonl`, `stage7_ground_truth.json`, and `stage7_intelligence_metrics.json`.

## Detector results

| Detector | TP | FP | FN | TN | Precision | Recall | F1 | False-positive rate | Mean delay |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Rolling mean/std | 18 | 0 | 9 | 94 | 1.000 (18 predictions) | 0.667 (27 positives) | 0.800 | 0/94 = 0.000 | 0 seconds over 4 detected sequences |
| Isolation Forest | 23 | 39 | 4 | 55 | 0.371 (62 predictions) | 0.852 (27 positives) | 0.517 | 39/94 = 0.415 | 0 seconds over 4 detected sequences |

The forest's false-positive rate and precision are weak on this fixture. Its higher recall does not justify treating it as an alert decision. These numbers describe a small authored dataset, not production behavior. Thresholds were fixed in configuration and not calibrated against production data.

Baseline coverage was 120/121 evaluation windows (0.992). Across all 241 feature windows, 25 baselines/detector windows (0.104) were insufficient, mostly warm-up windows plus the one-window cold-start service. Two invalid timestamps were explicitly excluded from 2,432 events. The no-future-data assertion passed.

## Pattern and dependency context

The fixture labels one recurring failure signature. Exact signature discovery found it (recall 1/1) and returned 9 patterns overall, so precision was 1/9 = 0.111. Repeated normal signatures explain most false pattern discoveries; recurrence is not equivalent to abnormality. Approximate signatures remain similarity hints and are not included in this exact-match metric.

The three labeled cross-service pairs and one labeled dependency-precedence pair were all found (4/4) in the corresponding scenario checks. The analyzer emitted 393 contextual graph-reachable anomaly relationships in total, many involving detector false positives. We do not report candidate-pair precision because the synthetic ground truth does not label every plausible graph-reachable relationship. The Stage 6 graph only contextualizes observations; this evaluation does not establish propagation or cause.

Across scenarios, the statistical/ML recall was 3/5 vs 5/5 for sudden error increase; 9/15 vs 12/15 for gradual degradation; 2/3 vs 3/3 for repeated bursts; 1/1 vs 1/1 for abnormal frequency. The benign normal variation probe generated 0/20 false alarms in either detector. 46 evaluation service/windows differed between detector anomaly sets, and both outputs remain individually available.

Total evaluation time was 0.314690 seconds for feature extraction, two detectors, pattern mining, and dependency-context analysis over this fixture on the local development environment. This is one small local timing, not a capacity promise. No memory benchmark is claimed. Candidate analysis considered 393 pairs and hit neither the 5,000-pair nor 500-output cap.
