"""HTTP adapter contract tests against an isolated SQLite database."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from payflow_simulator.http_api.app import create_app
from payflow_simulator.dependency_graph.blast_radius import DependencyGraphEngine
from payflow_simulator.dependency_graph.graph_store import SQLiteDependencyGraphStore
from payflow_simulator.recommendations.storage import SQLiteRecommendationStore


class HTTPAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "api.sqlite"
        self.client = TestClient(create_app(str(self.db), allowed_origins=["http://localhost:3000"]))

    def tearDown(self): self.tmp.cleanup()

    def test_empty_database_has_explicit_empty_states(self):
        self.assertEqual(self.client.get("/api/v1/health").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/incidents").json()["total"], 0)
        self.assertEqual(self.client.get("/api/v1/services").json()["items"], [])
        self.assertFalse(self.client.get("/api/v1/overview").json()["service_health_available"])

    def test_pagination_validation_and_missing_record(self):
        self.assertEqual(self.client.get("/api/v1/incidents?page=0").status_code, 422)
        self.assertEqual(self.client.get("/api/v1/incidents?page_size=101").status_code, 422)
        self.assertEqual(self.client.get("/api/v1/incidents?start_time=not-a-time").status_code, 422)
        self.assertEqual(self.client.get("/api/v1/incidents/no-such-incident").status_code, 404)

    def test_graph_routes_use_persisted_registry(self):
        with SQLiteDependencyGraphStore(self.db) as store: DependencyGraphEngine(store)
        response = self.client.get("/api/v1/services")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["items"]), 5)
        detail = self.client.get("/api/v1/services/payment-service").json()
        self.assertEqual(detail["outgoing_dependencies"][0]["target_service_id"], "database-service")

    def test_cors_is_restricted(self):
        denied = self.client.options("/api/v1/health", headers={"Origin":"https://elsewhere.invalid","Access-Control-Request-Method":"GET"})
        self.assertNotEqual(denied.headers.get("access-control-allow-origin"), "https://elsewhere.invalid")
        allowed = self.client.options("/api/v1/health", headers={"Origin":"http://localhost:3000","Access-Control-Request-Method":"GET"})
        self.assertEqual(allowed.headers.get("access-control-allow-origin"), "http://localhost:3000")

    def test_recommendation_transition_and_feedback_validation(self):
        # Invalid identifiers are returned as consistent not-found responses.
        response = self.client.patch("/api/v1/recommendations/missing/status", json={"status":"acknowledged"})
        self.assertEqual(response.status_code, 404)
        response = self.client.post("/api/v1/recommendations/missing/feedback", json={"outcome_status":"successful"})
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__": unittest.main()
