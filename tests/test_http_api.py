"""HTTP adapter contract tests against an isolated SQLite database."""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from time import time as current_time
from unittest.mock import patch
from pathlib import Path

from fastapi.testclient import TestClient

from payflow_simulator.http_api.app import create_app
from payflow_simulator.dependency_graph.blast_radius import DependencyGraphEngine
from payflow_simulator.dependency_graph.graph_store import SQLiteDependencyGraphStore
from payflow_simulator.http_api.security import AuthStore


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

    def test_auth_session_roles_csrf_and_expiry_surface(self):
        secure_client = TestClient(create_app(str(self.db), allowed_origins=["http://localhost:3000"], auth_enabled=True))
        users = AuthStore(self.db)
        users.create_user("viewer-one", "correct horse battery staple", "viewer")
        users.create_user("admin-one", "another correct password", "admin")
        unauthorized = secure_client.get("/api/v1/incidents", headers={"Origin":"http://localhost:3000"})
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(unauthorized.headers.get("access-control-allow-origin"), "http://localhost:3000")
        token = secure_client.get("/api/v1/auth/csrf").json()["csrf_token"]
        login = secure_client.post("/api/v1/auth/login", headers={"Origin":"http://localhost:3000","X-CSRF-Token":token}, json={"username":"viewer-one","password":"correct horse battery staple"})
        self.assertEqual(login.status_code, 200)
        self.assertIn("HttpOnly", login.headers.get("set-cookie", ""))
        self.assertEqual(secure_client.get("/api/v1/auth/me").json()["user"]["role"], "viewer")
        self.assertEqual(secure_client.get("/api/v1/admin/users").status_code, 403)
        self.assertEqual(secure_client.patch("/api/v1/recommendations/missing/status", headers={"Origin":"http://localhost:3000","X-CSRF-Token":token}, json={"status":"acknowledged"}).status_code, 403)
        self.assertEqual(secure_client.post("/api/v1/auth/logout", headers={"Origin":"http://localhost:3000","X-CSRF-Token":token}).status_code, 200)
        self.assertEqual(secure_client.get("/api/v1/incidents").status_code, 401)

    def test_admin_can_manage_users_and_responder_can_write(self):
        secure_client = TestClient(create_app(str(self.db), allowed_origins=["http://localhost:3000"], auth_enabled=True))
        AuthStore(self.db).create_user("admin-user", "a very long test password", "admin")
        token = secure_client.get("/api/v1/auth/csrf").json()["csrf_token"]
        response = secure_client.post("/api/v1/auth/login", headers={"Origin":"http://localhost:3000","X-CSRF-Token":token}, json={"username":"admin-user","password":"a very long test password"})
        self.assertEqual(response.status_code, 200)
        created = secure_client.post("/api/v1/admin/users", headers={"Origin":"http://localhost:3000","X-CSRF-Token":token}, json={"username":"responder-user","password":"responder password long","role":"responder"})
        self.assertEqual(created.status_code, 201)
        self.assertNotIn("password_hash", created.json())
        self.assertIn("X-Request-ID", created.headers)
        self.assertEqual(created.headers.get("x-frame-options"), "DENY")

    def test_settings_reject_insecure_production_defaults(self):
        from payflow_simulator.http_api.config import load_settings
        with self.assertRaisesRegex(ValueError, "SECRET_KEY"):
            load_settings(environ={"JARVIS_ENV":"production"})
        with self.assertRaisesRegex(ValueError, "disabled"):
            load_settings(environ={"JARVIS_ENV":"production","JARVIS_SECRET_KEY":"x"*40,"JARVIS_AUTH_ENABLED":"false"})
        response = self.client.post("/api/v1/recommendations/missing/feedback", json={"outcome_status":"successful"})
        self.assertEqual(response.status_code, 404)

    def test_oversized_request_body_is_rejected(self):
        from payflow_simulator.http_api.config import load_settings
        settings = replace(load_settings(environ={"JARVIS_ENV":"testing"}), max_request_bytes=1024)
        limited = TestClient(create_app(str(self.db), settings=settings))
        response = limited.post("/api/v1/auth/login", content=b"x" * 2048,
                                headers={"Content-Type":"application/json"})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], "request_too_large")

    def test_session_cookie_expires_at_configured_ttl(self):
        from payflow_simulator.http_api.config import load_settings
        settings = replace(load_settings(environ={"JARVIS_ENV":"testing"}), session_ttl_seconds=60)
        AuthStore(self.db).create_user("expiry-viewer", "a valid long test password", "viewer")
        secure_client = TestClient(create_app(str(self.db), allowed_origins=["http://localhost:3000"],
                                              auth_enabled=True, settings=settings))
        csrf = secure_client.get("/api/v1/auth/csrf").json()["csrf_token"]
        login = secure_client.post("/api/v1/auth/login", headers={"Origin":"http://localhost:3000","X-CSRF-Token":csrf},
                                   json={"username":"expiry-viewer","password":"a valid long test password"})
        self.assertEqual(login.status_code, 200)
        with patch("itsdangerous.timed.time.time", return_value=current_time() + 61):
            expired = secure_client.get("/api/v1/incidents")
        self.assertEqual(expired.status_code, 401)


if __name__ == "__main__": unittest.main()
