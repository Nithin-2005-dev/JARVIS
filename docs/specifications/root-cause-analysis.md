# RCA specification

## Candidate identification

Each incident member is eligible when severity is configured as abnormal (`ERROR`, `CRITICAL`, `FATAL` by default), or it has a non-lifecycle classification category. Candidate hints include pool/resource exhaustion language, database/network/infrastructure classifications, event-time order, configured dependency relationships, shared normalized resource identifiers, Stage 3 `patterns`, and Stage 4 edges. Earliest abnormality is only a low-weight temporal consistency cue; a later explicit pool failure can outrank an earlier generic symptom.

Records with invalid/missing event time remain in the candidate set and timeline with `event_time: null`. Their order is not fabricated. Events that are not abnormal remain factual timeline entries but are not scored candidates.

## Evidence model and types

Every evidence item has `family`, `polarity` (`supporting`, `contradictory`, or `missing`), `evidence_type` (`observed_fact`, `correlated_relationship`, or `inferred_dependency`), description, event IDs, strength, configured weight, configured reliability, and source details. Stage 4 edge strategy, score, description, and attributes are retained. A Stage 4 edge means relatedness only.

Temporal evidence compares event timestamps; processing timestamps are not substituted. The timeline shows both timestamps and Stage 3 late/out-of-order flags. Candidate evidence includes the event-time differences to later observed abnormal events; these indicate sequence only. The engine records earliest observed abnormality and competing earlier signals, but does not claim the observed start is the true incident start. Shared resource IDs are evidence of context, not proof of resource failure. Stage 3 pattern observations indicate recurrence, not cause. Configured dependency paths describe plausible influence and can be stale or wrong.

Metrics and independent verification are explicit evidence gaps because Stage 1–4 has no metrics integration or independent verifier. Missing trace IDs are recorded as gaps; absence is never treated as negative evidence.

## Hypothesis scoring

Default weights are defined in `RCAConfig`: initiating failure 0.8, resource exhaustion 1.0, infrastructure failure 0.9, dependency path 0.45, Stage 4 correlation 0.35, resource context 0.35, Stage 3 pattern 0.35, and temporal precedence 0.15. Observed event facts default to reliability 1.0; Stage 4 association to 0.55; configured dependency to 0.5. Contradictory evidence is multiplied by `contradictory_weight` (0.65). Strength is rule-based from the documented event signal and is not a measured likelihood.

For supporting evidence `S` and contradictory evidence `C`:

`score = clamp((Σ(weight × reliability × strength for S) − contradiction_weight × Σ(weight × reliability × strength for C)) / Σ(weight × reliability for S ∪ C), 0, 1)`.

The result is `heuristic_evidence_score_not_probability`. A candidate must meet the configured score threshold (0.45) and have at least two supporting evidence families. If none do, the report is `inconclusive`. If the top qualifying candidates are within the configured margin (0.12), the status is `competing_hypotheses`. Otherwise the status is `leading_hypothesis`. Thresholds and weights are user-configurable. No threshold represents statistical calibration.

## Causal safeguards

- Temporal precedence is weak consistency evidence; it does not establish cause.
- Stage 4 relationships remain explicitly correlated relationships and have no causal direction.
- Shared resources do not prove resource failure or causal influence.
- The earliest event is not forced to the top; explicit failure-domain indicators can outrank it.
- Missing trace, metrics, timestamp, or independent verification data remain unknown evidence gaps.
- Multiple candidates are retained and ranked; close candidates remain competing.
- No root cause is marked confirmed without an independent verifier; current reports return `confirmed_causes: []`.
- A low-evidence incident returns inconclusive rather than inventing an answer.

## Structured report

The snapshot includes investigation/incident IDs, content fingerprint, status, summary, time range, investigation timestamp, leading and alternative hypotheses, all ranked hypotheses, empty confirmed-cause list, affected services, factual timeline, correlated relationships, evidence gaps, recommended investigations, confidence limitations, and the configuration snapshot. `leading_hypothesis` is null for competing or inconclusive assessments; ranked candidates remain available in `hypotheses`, so the report does not declare a winner when evidence is close. Each candidate contains score breakdown and supporting, contradictory, and missing evidence. Reports can be retrieved as stored JSON; historical snapshots are immutable.

## Persistence

`rca_investigations` stores unique `(incident_id, fingerprint)` report snapshots; `rca_hypotheses` stores candidate rank/score and full payload; `rca_evidence` stores individual evidence assessments; `rca_history` records first-time investigations. Inserts happen in one SQLite transaction. Source event payloads and Stage 4 records remain unchanged. A database backup is still needed for local durability; the engine does not currently provide retention/pruning.
