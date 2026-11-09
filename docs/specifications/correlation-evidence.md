# Correlation evidence and heuristic confidence

Each relationship contains sorted source and target event IDs and one or more evidence records with strategy, human-readable description, supporting attributes, optional event-time difference, strategy score, combined heuristic confidence score, and evaluation timestamp.

Per-strategy scores are rule-based: trace 1.0; resource 0.95; dependency 0.7; pattern similarity is similarity × 0.6; temporal proximity decays linearly within the configured window with a 0.25 floor; cross-service support 0.65. Values are configurable through `strategy_weights`, which weight the combined weighted mean. Weights and the incident minimum are validated in `[0,1]`.

These are heuristic confidence scores, not probabilities. No calibration, training, or statistical claim is made. Evidence records carry the same combined score and retain the strategy-specific score separately. All source fields and metadata remain available in `original_event`.

An edge can be retained without becoming incident membership. The grouping policy needs a trace/resource strategy or both temporal and dependency strategies and the configured combined score threshold. When events have distinct non-empty trace IDs, a shared resource is required to bridge them. Pattern and cross-service labels are not qualifying strong signals by themselves. The API exposes only observed supporting evidence; it does not manufacture explanations for every absent pair.
