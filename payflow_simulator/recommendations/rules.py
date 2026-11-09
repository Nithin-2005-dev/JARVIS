"""Versioned, independently identifiable evidence-gated recommendation rules."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class RecommendationRule:
    rule_id: str
    version: str
    description: str
    input_conditions: tuple[str, ...]
    required_evidence: tuple[str, ...]
    excluded_conditions: tuple[str, ...]
    template: Mapping[str, Any]
    priority_logic: str
    confidence_logic: str
    risk_assessment: str
    verification_procedure: tuple[str, ...]


DEFAULT_RULES = (
    RecommendationRule("db_pool_diagnostics", "1", "Investigate observed database connection pool exhaustion.",
        ("event type or message explicitly identifies pool exhaustion",), ("processed event id and event type",),
        ("no matching source event",), {"type":"investigation", "title":"Inspect database connection pool utilization", "risk":"low"},
        "critical evidence -> high, otherwise medium", "multiple direct events -> moderate; single -> weak", "read-only investigation",
        ("Compare active and waiting connections with the configured pool limit.", "Inspect long-running and blocked transactions.", "Check whether connection wait time and transaction failures return toward baseline.")),
    RecommendationRule("pool_admission_control", "1", "Consider temporary payment admission control only after repeated pool saturation is directly observed.",
        ("at least two pool exhaustion events show active_connections >= pool_size and positive wait_ms", "verified prerequisites: current_saturation_confirmed, approved_runbook, payment_owner_approval"),
        ("two distinct event ids with pool size, active connections, and wait time",),
        ("missing current saturation evidence or missing change approval/runbook",),
        {"type":"mitigation", "title":"Consider temporary payment admission control", "risk":"high"},
        "medium; investigation rules rank first", "moderate based on repeated explicit saturation observations; still unconfirmed", "high: may reject or delay valid payments",
        ("If the incident is active and current metrics confirm saturation, follow the approved admission-control runbook.",
         "Monitor database waits, payment success rate, and rejected or delayed requests.",
         "Remove the temporary cap after database utilization and transaction latency remain within the service objective.")),
    RecommendationRule("auth_failure_diagnostics", "1", "Investigate directly observed authentication failures.",
        ("authentication service or authentication failure event",), ("event id and service/type evidence",),
        ("no authentication failure evidence",), {"type":"investigation", "title":"Inspect authentication failure patterns", "risk":"low"},
        "critical evidence -> high, otherwise medium", "multiple direct events -> moderate; single -> weak", "read-only investigation",
        ("Compare authentication failures by error type and dependent service.", "Check identity-provider and token-validation dependency health.", "Verify successful authentication requests recover.")),
    RecommendationRule("notification_failure_diagnostics", "1", "Investigate directly observed notification delivery failures.",
        ("notification provider failure, timeout, retry, or queue signal",), ("event id and notification service/type evidence",),
        ("no notification failure evidence",), {"type":"investigation", "title":"Inspect notification retries and delivery backlog", "risk":"low"},
        "critical evidence -> high, otherwise medium", "multiple direct events -> moderate; single -> weak", "read-only investigation",
        ("Inspect queue depth, retry count, and oldest message age.", "Check downstream notification-provider availability.", "Verify delivery success and queue drain behavior.")),
    RecommendationRule("service_error_diagnostics", "1", "Investigate directly observed service degradation.",
        ("service has explicit error events or Stage 7 anomaly",), ("event or finding evidence reference",),
        ("no event or finding for requested service",), {"type":"investigation", "title":"Compare service error rate and dependency health", "risk":"low"},
        "incident severity and repeated observations", "direct event evidence moderate; anomaly-only weak", "read-only investigation",
        ("Compare service error rates with the prior baseline.", "Check direct dependency health and relevant logs.", "Verify whether error rate and successful request volume recover.")),
    RecommendationRule("rca_candidate_diagnostics", "1", "Gather discriminating evidence for an unconfirmed RCA candidate.",
        ("RCA is competing or inconclusive",), ("RCA investigation id and candidate reference",),
        ("candidate lacks a service or event reference",), {"type":"investigation", "title":"Validate competing incident hypothesis", "risk":"low"},
        "medium; elevate only on direct severity", "weak unless direct evidence corroborates candidate", "read-only investigation",
        ("Collect the candidate-specific missing metrics and logs.", "Compare event timing against alternative candidates.", "Record results without treating the candidate as confirmed.")),
    RecommendationRule("detector_disagreement_diagnostics", "1", "Investigate detector disagreement without selecting one detector as truth.",
        ("Stage 7 statistical and ML findings differ for a service/window",), ("both detector identities and finding ids",),
        ("only one detector result exists",), {"type":"diagnostic", "title":"Review conflicting anomaly detector signals", "risk":"low"},
        "informational or medium", "weak; detector outputs are not probabilities", "read-only comparison",
        ("Compare each detector's feature, observed value, and baseline.", "Check the source events for the window and known traffic variation.", "Use independent service telemetry before treating the signal as incident evidence.")),
    RecommendationRule("potential_blast_radius_check", "1", "Verify structurally downstream services when blast-radius analysis identifies potential impact.",
        ("Stage 6 potential impacted services exist",), ("blast-radius analysis id and impacted service ids",),
        ("no persisted blast-radius analysis",), {"type":"investigation", "title":"Verify potentially affected dependent services", "risk":"low"},
        "medium for critical dependents", "weak: structural possibility only", "read-only service health verification",
        ("Check health and request success for each listed dependent service.", "Compare observed failures with the dependency paths in the snapshot.", "Separate confirmed failures from potential structural impact.")),
    RecommendationRule("recurrence_monitoring", "1", "Add targeted monitoring when a repeated failure signature is observed.",
        ("Stage 3 repeated pattern or Stage 7 recurring pattern finding",), ("pattern finding id and supporting event ids",),
        ("no historical recurrence evidence",), {"type":"monitoring", "title":"Add monitoring for the recurring failure signature", "risk":"low"},
        "low to medium", "weak: recurrence does not establish cause", "monitoring-only change, review before deployment",
        ("Alert on the observed event signature or resource failure count.", "Validate alert behavior against the referenced historical events.", "Review false-positive rate after deployment.")),
)


def rules_as_dict(rules: tuple[RecommendationRule, ...] = DEFAULT_RULES) -> list[dict[str, Any]]:
    from dataclasses import asdict
    return [asdict(rule) for rule in rules]
