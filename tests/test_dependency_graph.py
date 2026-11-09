"""Stage 6 graph, blast-radius, persistence, and incident integration tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from payflow_simulator.dependency_graph import (BlastRadiusAnalyzer, DependencyGraphBuilder,
    DependencyGraphEngine, DependencyGraphConfig, SQLiteDependencyGraphStore)
from payflow_simulator.dependency_graph.evaluate import run_evaluation
from payflow_simulator.dependency_graph.models import Dependency, Service
from payflow_simulator.dependency_graph.service_registry import default_config


def graph_config(dependencies: tuple[Dependency, ...], services: tuple[Service, ...] | None = None) -> DependencyGraphConfig:
    base = default_config()
    return DependencyGraphConfig(services=services or base.services, dependencies=dependencies)


class DependencyGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = default_config()
        self.graph = DependencyGraphBuilder(self.config).build()

    def test_graph_direction_database_failure_impacts_payment_then_gateway_and_notifications(self) -> None:
        report = BlastRadiusAnalyzer(self.graph).analyze("database-service")
        self.assertEqual([x["service_id"] for x in report["directly_impacted_services"]], ["payment-service"])
        self.assertEqual({x["service_id"] for x in report["indirectly_impacted_services"]}, {"api-gateway", "notification-service"})
        paths = {x["service_id"]: x["dependency_paths"][0] for x in report["impacted_services"]}
        self.assertEqual(paths["api-gateway"], ("database-service", "payment-service", "api-gateway"))
        self.assertEqual(report["impact_depth"], 2)
        self.assertFalse(any(x["evidence"]["confirmed_failure"] for x in report["impacted_services"]))

    def test_service_failure_scenarios_have_expected_dependents(self) -> None:
        analyzer = BlastRadiusAnalyzer(self.graph)
        expected = {
            "payment-service": {"api-gateway", "notification-service"},
            "notification-service": set(),
            "authentication-service": {"api-gateway"},
        }
        for root, services in expected.items():
            with self.subTest(root=root):
                result = analyzer.analyze(root)
                self.assertEqual({x["service_id"] for x in result["impacted_services"]}, services)

    def test_depth_limit_and_environment_filter(self) -> None:
        analyzer = BlastRadiusAnalyzer(self.graph)
        one = analyzer.analyze("database-service", max_depth=1)
        self.assertEqual({x["service_id"] for x in one["impacted_services"]}, {"payment-service"})
        with self.assertRaises(ValueError): analyzer.analyze("database-service", max_depth=0)
        prod = DependencyGraphBuilder(DependencyGraphConfig(
            services=tuple(Service(s.service_id, s.service_name, s.description, s.service_type, s.criticality,
                                  s.business_capability, "prod", s.metadata) for s in self.config.services),
            dependencies=self.config.dependencies)).build()
        self.assertEqual(len(BlastRadiusAnalyzer(prod).analyze("database-service", environment="prod")["impacted_services"]), 3)
        with self.assertRaises(ValueError): BlastRadiusAnalyzer(prod).analyze("database-service", environment="dev")
        mixed_services=tuple(Service(s.service_id,s.service_name,s.description,s.service_type,s.criticality,s.business_capability,
            "prod" if s.service_id in {"database-service","payment-service"} else "dev",s.metadata) for s in self.config.services)
        mixed=DependencyGraphBuilder(DependencyGraphConfig(services=mixed_services,dependencies=self.config.dependencies)).build()
        filtered=BlastRadiusAnalyzer(mixed).analyze("database-service",environment="prod")
        self.assertEqual(len(filtered["environment_excluded_dependencies"]),2)

    def test_duplicate_paths_preserve_alternatives_but_no_duplicate_service(self) -> None:
        deps = (*self.config.dependencies, Dependency("api-gateway", "database-service", "database", .6))
        graph = DependencyGraphBuilder(graph_config(deps)).build()
        report = BlastRadiusAnalyzer(graph).analyze("database-service")
        api = next(x for x in report["impacted_services"] if x["service_id"] == "api-gateway")
        self.assertEqual(api["depth"], 1)
        self.assertEqual(len(api["dependency_paths"]), 2)
        self.assertEqual(len([x for x in report["impacted_services"] if x["service_id"] == "api-gateway"]), 1)

    def test_alternative_path_cap_is_reported(self) -> None:
        deps = (*self.config.dependencies, Dependency("api-gateway", "database-service", "database", .6))
        config = DependencyGraphConfig(services=self.config.services, dependencies=deps, max_paths_per_service=1)
        report = BlastRadiusAnalyzer(DependencyGraphBuilder(config).build()).analyze("database-service")
        self.assertTrue(any("path enumeration" in warning for warning in report["warnings"]))
        api = next(x for x in report["impacted_services"] if x["service_id"] == "api-gateway")
        self.assertEqual(len(api["dependency_paths"]), 1)

    def test_validation_reports_duplicates_unknown_nodes_types_cycles_and_disconnected(self) -> None:
        services = (Service("a", "A"), Service("b", "B"), Service("alone", "Alone"), Service("nameless", ""))
        deps = (Dependency("a", "b", "custom_bus"), Dependency("a", "b", "custom_bus"),
                Dependency("b", "a", "other"), Dependency("a", "missing", "database"),
                Dependency("a", "a", "other"), Dependency("missing-source", "b", "other"))
        graph = DependencyGraphBuilder(graph_config(deps, services)).build()
        codes = {f.code for f in graph.findings}
        self.assertTrue({"duplicate_dependency", "unknown_dependency_type", "missing_source_service", "missing_target_service", "self_dependency", "dependency_cycle", "disconnected_service", "missing_service_name"} <= codes)
        self.assertEqual(len(graph.dependencies), 5)  # duplicate collapsed; invalid definitions remain visible
        self.assertFalse(BlastRadiusAnalyzer(graph).analyze("a")["cycle_findings"] == [])

    def test_graph_version_is_independent_of_definition_order(self) -> None:
        first = DependencyGraphBuilder(self.config).build()
        reverse = DependencyGraphBuilder(DependencyGraphConfig(
            services=tuple(reversed(self.config.services)), dependencies=tuple(reversed(self.config.dependencies)))).build()
        self.assertEqual(first.graph_version, reverse.graph_version)

    def test_unknown_service_and_unresolved_dependency_are_explicit(self) -> None:
        with self.assertRaises(KeyError): BlastRadiusAnalyzer(self.graph).analyze("not-registered")
        graph = DependencyGraphBuilder(graph_config((*self.config.dependencies, Dependency("api-gateway", "future-db", "database")))).build()
        result = BlastRadiusAnalyzer(graph).analyze("payment-service")
        self.assertTrue(result["unresolved_dependencies"])

    def test_impact_scores_are_deterministic_and_not_probabilities(self) -> None:
        analyzer = BlastRadiusAnalyzer(self.graph)
        first = analyzer.analyze("database-service"); second = analyzer.analyze("database-service")
        scores = lambda result: [(x["service_id"], x["impact_score"], x["score_breakdown"]) for x in result["impacted_services"]]
        self.assertEqual(scores(first), scores(second))
        self.assertIn("not_failure_probability", first["impacted_services"][0]["score_breakdown"]["score_kind"])

    def test_registry_graph_snapshot_history_idempotency_and_version_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, SQLiteDependencyGraphStore(Path(tmp)/"db.sqlite") as store:
            engine = DependencyGraphEngine(store, self.config)
            first = engine.analyze("database-service")
            repeated = engine.analyze("database-service")
            self.assertEqual(first, repeated)
            self.assertEqual(len(store.analysis_history(service_id="database-service")), 1)
            old_version = engine.graph.graph_version
            changed = DependencyGraphConfig(services=self.config.services,
                dependencies=tuple(Dependency(d.source_service_id, d.target_service_id, d.dependency_type,
                    d.importance, d.description, d.evidence_source, d.confidence, d.verification_status, d.metadata)
                    for d in self.config.dependencies), version_label="payflow-v2")
            engine2 = DependencyGraphEngine(store, changed)
            self.assertNotEqual(old_version, engine2.graph.graph_version)
            self.assertEqual(len(store.graph_history()), 2)
            self.assertIsNotNone(store.graph_snapshot(old_version))
            historical = DependencyGraphEngine(store, graph_version=old_version)
            self.assertEqual(historical.graph.graph_version, old_version)
            self.assertEqual(store.graph_snapshot()["graph_version"], engine2.graph.graph_version)

    def test_competing_rca_hypotheses_each_run_hypothetical_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, SQLiteDependencyGraphStore(Path(tmp)/"db.sqlite") as store:
            engine = DependencyGraphEngine(store, self.config)
            db=store.connection
            db.executescript("CREATE TABLE incidents(incident_id TEXT PRIMARY KEY,status TEXT,created_at TEXT,updated_at TEXT,severity TEXT,anchor_event_id TEXT,merged_into TEXT,summary TEXT); CREATE TABLE incident_members(event_id TEXT PRIMARY KEY,incident_id TEXT); CREATE TABLE processed_events(event_id TEXT PRIMARY KEY,payload TEXT); CREATE TABLE rca_investigations(investigation_id TEXT PRIMARY KEY,incident_id TEXT,fingerprint TEXT,created_at TEXT,report TEXT,UNIQUE(incident_id,fingerprint));")
            db.execute("INSERT INTO incidents VALUES('inc-1','active','t','t','ERROR','e1',NULL,'sample')")
            for eid, service in (("e1","database-service"),("e2","authentication-service")):
                event={"event_id":eid,"original_event":{"event_id":eid,"service":service,"severity":"ERROR","timestamp":"2025-01-01T00:00:00Z","event_type":"failure","message":"failed"}}
                db.execute("INSERT INTO processed_events VALUES(?,?)", (eid,json.dumps(event))); db.execute("INSERT INTO incident_members VALUES(?,'inc-1')", (eid,))
            report={"assessment_status":"competing_hypotheses","hypotheses":[
                {"candidate_event_id":"e1","candidate_service":"database-service"},
                {"candidate_event_id":"e2","candidate_service":"authentication-service"}],"leading_hypothesis":None}
            db.execute("INSERT INTO rca_investigations VALUES('rca-1','inc-1','f','2025',?)", (json.dumps(report),)); db.commit()
            result=engine.analyze_incident("inc-1")
            self.assertTrue(result["uncertainty_preserved"])
            self.assertEqual(len(result["scenario_analyses"]),2)
            self.assertEqual({x["scenario_label"] for x in result["scenario_analyses"]},{"hypothetical_rca_candidate"})
            self.assertTrue(all(not x["confirmed_root_cause"] for x in result["scenario_analyses"]))
            self.assertEqual({x["candidate_event_id"] for x in result["scenario_analyses"]},{"e1","e2"})
            report["assessment_status"]="inconclusive"
            db.execute("UPDATE rca_investigations SET report=? WHERE investigation_id='rca-1'", (json.dumps(report),)); db.commit()
            inconclusive=engine.analyze_incident("inc-1")
            self.assertTrue(inconclusive["uncertainty_preserved"])
            self.assertEqual(len(inconclusive["scenario_analyses"]),2)
            self.assertEqual({x["rca_assessment_status"] for x in inconclusive["scenario_analyses"]},{"inconclusive"})

    def test_incident_without_rca_returns_structured_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, SQLiteDependencyGraphStore(Path(tmp)/"db.sqlite") as store:
            engine=DependencyGraphEngine(store,self.config)
            store.connection.execute("CREATE TABLE incidents(incident_id TEXT PRIMARY KEY,status TEXT,created_at TEXT,updated_at TEXT,severity TEXT,anchor_event_id TEXT,merged_into TEXT,summary TEXT)")
            store.connection.execute("INSERT INTO incidents VALUES('i','active','t','t','ERROR','e',NULL,'x')"); store.connection.commit()
            self.assertEqual(engine.analyze_incident("i")["error"]["code"],"rca_unavailable")
            self.assertEqual(engine.analyze_incident("missing")["error"]["code"],"incident_not_found")

    def test_synthetic_evaluation_known_and_unknown_scenarios(self) -> None:
        result=run_evaluation()
        self.assertEqual(result["scenario_count"],9)
        self.assertEqual(result["direct_impact_scenario_accuracy"],1.0)
        self.assertEqual(result["indirect_impact_scenario_accuracy"],1.0)
        self.assertEqual(result["path_validity_scenario_rate"],1.0)
        self.assertTrue(result["uncertain_scenario_passed"])
        self.assertEqual(result["uncertain_scenario_count"],2)
        self.assertEqual(result["structural_behavior_scenarios"],2)
        self.assertTrue(result["structural_behavior_scenarios_passed"])

    def test_analysis_write_is_transactional_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, SQLiteDependencyGraphStore(Path(tmp)/"db.sqlite") as store:
            engine=DependencyGraphEngine(store,self.config)
            store.connection.execute("CREATE TRIGGER reject_analysis BEFORE INSERT ON blast_radius_analyses BEGIN SELECT RAISE(ABORT, 'forced'); END")
            store.connection.commit()
            with self.assertRaises(Exception): engine.analyze("database-service")
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM blast_radius_analyses").fetchone()[0],0)
            store.connection.execute("DROP TRIGGER reject_analysis"); store.connection.commit()
            self.assertTrue(engine.analyze("database-service")["analysis_id"])


if __name__ == "__main__": unittest.main()
