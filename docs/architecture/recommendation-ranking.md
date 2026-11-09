# Recommendation ranking and risk controls

## Score

Each recommendation has a deterministic heuristic score in `[0,1]`, not a probability of success:

`clamp(sum(weight_i * factor_i) - risk_penalty, 0, 1)`

Factors are incident severity, evidence basis, urgency, affected-service criticality, potential structural impact, expected benefit, and prerequisite readiness. Default weights are respectively `.18, .24, .14, .12, .10, .12, .10`; default penalties are low `0`, medium `.12`, high `.30`. The complete per-factor contributions, penalty, and score are stored in each recommendation.

All factors are bounded to `[0,1]`. Severity uses the incident's recorded severity; service criticality is currently a transparent PayFlow mapping (database, payment, gateway, and authentication `.8`, other `.45`) and is a prototype default, not an external registry claim. Potential impact is used only for Stage 6 context. These defaults are configurable through `RecommendationConfig`.

## Ordering and safety gate

After scoring, recommendations are sorted by type class: investigation, diagnostic, monitoring, mitigation, recovery, prevention, capacity, configuration, security; within each class, higher heuristic score comes first and ID breaks ties. This ensures a high-risk suggestion cannot overtake a low-risk investigation due to a score. A high-risk recommendation also requires explicit prerequisites in the model. The current admission-control rule adds current-saturation checks, service-owner/change approval, and payment impact acceptance.

Confidence labels are categorical evidence descriptions; no score threshold converts them into a probability. Detector scores are copied only as source evidence and are never averaged into recommendation confidence. Risk is separate from urgency and evidence strength.

## Known ranking limits

The fixed criticality defaults are PayFlow-specific. The score is a transparent prioritization aid, not calibrated responder utility. The rule class ordering intentionally takes precedence over numeric score and may need policy review for future rule types. Evaluation fixtures test these mechanics only; they do not establish production quality.
