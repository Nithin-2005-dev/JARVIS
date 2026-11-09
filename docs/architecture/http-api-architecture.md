# HTTP API architecture

`payflow_simulator.http_api` provides a versioned FastAPI boundary. `DashboardService` is an adapter over existing `SQLiteCorrelationStore`, `SQLiteRCAStore`, `SQLiteDependencyGraphStore`, `SQLiteIntelligenceStore`, and `SQLiteRecommendationStore` APIs. It opens and closes short-lived connections per request. There is no frontend access to SQLite and no SQL predicate is derived from client input.

Writes are limited to Stage 8 recommendation status and feedback operations; the store retains authority over valid transitions, dismissal reasons, and feedback persistence. CORS is allow-list based. Query page size/limit is bounded. Validation errors use FastAPI 422 responses; missing records use 404; invalid lifecycle transitions use 409; unexpected errors are logged server-side and returned without stack traces.

OpenAPI is available locally at `/api/docs`. Database selection uses `JARVIS_DATABASE` (default `data/events.sqlite`). CORS origins use comma-separated `JARVIS_CORS_ORIGINS` (default `http://localhost:3000`). The demo API has no authentication and should remain loopback-only.
