# Known issues and limitations

- The event contract is illustrative, not a production payment or audit schema.
- Pool exhaustion is injected at request boundary; occupancy, wait queues, concurrency, and recovery are not modeled.
- A downstream timeout marks the notification queued, but no retry/backoff event is emitted.
- Service calls and database writes are synthetic.
- Metadata fields are not strictly validated beyond requiring an object.
- The default timestamp is fixed for reproducibility; select `--start-time` to change the timeline.
- IDs are deterministic for fixture generation and are not globally unique across independent streams/seeds.
- JSON document input is loaded as one document; use JSONL for large files. CSV and JSONL adapters stream rows/lines.
- REST ingestion performs one GET, reads the response body before processing, and does not paginate or retry. Large REST responses require memory proportional to response size.
- SQLite is a single-host store. It commits every 500 newly inserted rows and at batch completion; an abrupt exit may lose the current pending commit batch.
- Quarantine is append-only and has no built-in rotation or retention enforcement.
- Repeated event IDs keep the first accepted payload without comparing later payload differences.
- REST CLI does not configure auth headers; Python adapter callers can supply headers.
- Processing classification is only as complete as its registry and configured rules; an unmatched known event is labeled `uncategorized`.
- The event-time watermark is global and serial in the local processor. Out-of-order events are annotated and retained in their original windows, but not buffered or reordered; multiple workers are not a supported ordering guarantee.
- Pattern signatures require matching event type, severity, and normalized message. Small wording changes split counts; event volume uses fixed absolute thresholds, not learned baselines.
- Pattern evidence lists are capped at 20 IDs while pattern counts remain total counts.
- Processing claims use a stale timeout without lease renewal. Keep one local processor; a long-running attempt could be reclaimed by another process after the timeout.
- Failed rows are retained and retried on later runs; there is no automatic retry limit or purge/dead-letter policy.
- Processing history and pattern observations have no automatic retention policy.
- SQLite finalizes each event atomically; local write/commit latency dominates the 5,000-event benchmark. This milestone establishes correctness and recoverability, not a high-throughput target.
- The additive lifecycle/security event types are available to producers but the Stage 1 simulator does not emit them.
# Stage 4 known limitations

- Scores are heuristic, not statistically calibrated; a high score is not a causal statement or a probability.
- Trace incompleteness is only an observation: without expected span/service manifests, a single observed service cannot prove a missing span.
- Similar-message matching is limited to nearby failure candidates or Stage 3 pattern evidence, so distant repeat failures may not link.
- Dense trace/resource/time buckets can exceed `max_candidates`; the run fails before replacing persisted correlation relationships.

# Stage 7 intelligence limits

- The Isolation Forest is a small dependency-free seeded implementation. It is tested for repeatability, but its synthetic precision is low; do not use it for alerting without representative labeled evaluation.
- The statistical 3.0 and forest 0.62 thresholds, minimum histories, time windows, lookback, support, and similarity values are configurable engineering choices, not calibrated probabilities.
- Baselines assume recent service windows are comparable. Time-of-day/day-of-week seasonality is not implemented.
- The input contract has no explicit service-coverage interval. Empty intervals are not synthesized, so silent services and event-volume drops during no-event periods cannot be reliably detected.
- Batch reruns use event time and create a new immutable snapshot when inputs change; there is no streaming watermark, incremental late-event state, or online retraining.
- Exact signatures recur in normal and failure traffic. The synthetic pattern precision is low; findings are investigation hints, not incident identities or causal evidence.
- Cross-service outputs depend on the Stage 6 configured topology, can be affected by stale/missing edges, and are capped at 5,000 candidate pairs and 500 emitted relationships by default; cap/truncation indicators are returned.
- Per-window Isolation Forest artifacts retain trees and training-window references. Long histories can make SQLite snapshots large; no retention/compaction policy is implemented.
- Findings link to Stage 4 incidents, Stage 5 RCA, and Stage 6 blast-radius snapshots only when evidence event IDs match stored incident membership.
- SQLite is a local single-writer store. There is no multi-host coordination, network REST server, retention/archival process, or asynchronous streaming correlation.
- Full processed-event reevaluation on each run can become expensive as the local database grows.
- Synthetic evaluation has easy, explicit labels and should not be read as production precision or recall.
# Stage 5 RCA limitations

- There is no metrics or independent verification adapter. Reports include explicit missing evidence and never mark a cause confirmed.
- Dependency relationships come from configurable local settings; stale topology may create or hide plausible paths.
- Heuristic weights/strengths are rule-based and not calibrated. Treat rank as an investigation aid, not a probability.
- Shared resources and Stage 4 edges express context/relatedness and do not establish causal direction.
- Synthetic metrics in `data/evaluation/stage5_rca_metrics.json` come from six handcrafted scenarios and should not be used as a production accuracy estimate.
- Current candidate/resource comparison is quadratic in the size of one incident; very large incidents need indexed resource evidence.

# Stage 6 dependency graph and blast-radius limitations

- The PayFlow graph is static configuration derived from simulator behavior; topology is not discovered from deployments or runtime calls.
- The retry queue is simulated. No broker or external mail-provider service node is modeled.
- Blast radius means possible structural/business capability impact, not that a dependent service is down. Error events are observed signals, not independent health confirmation.
- Criticality, dependency importance/confidence, depth decay, and fanout are heuristic inputs. Scores are not probabilities or measured business loss.
- Simple-path enumeration is capped by `max_paths_per_service`; dense graphs may omit alternate paths and emit a warning.
- Unknown endpoints and insufficiently verified edges remain visible. They may cause incomplete impact estimates until registry definitions are reviewed.
- Incident integration reads the latest Stage 5 snapshot and does not rerun RCA or choose a winner among competing/inconclusive hypotheses.
- SQLite graph/history records have no retention policy and remain a local single-host store.
# Stage 8 recommendation limitations

- The default rules read the latest available Stage 7 run, latest RCA snapshot for an incident, and persisted Stage 6 blast-radius records. Missing optional stage tables produce no context from that source; they are not treated as negative evidence.
- The engine cannot query live telemetry. Historical pool metrics must be independently checked before the guarded admission-control proposal is acted on.
- Current service criticality values are PayFlow-specific defaults used only for heuristic ranking.
- Rule descriptors are versioned, but conditions are implemented in Python branches. New rules need code and tests as well as a descriptor.
- The engine does not provide generic mitigation/recovery suggestions for every service. If the evidence does not satisfy a rule, it favors investigation or returns no applicable rule.
- SQLite generation snapshots are immutable, but lifecycle state is a separate mutable current record with append-only audit rows.
