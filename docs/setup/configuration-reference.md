# Configuration Reference

The backend reads validated settings through `payflow_simulator.http_api.config`. `.env.example` contains placeholders only; never copy a placeholder secret into a deployed environment.

| Variable | Purpose | Production requirement |
|---|---|---|
| `JARVIS_ENV` | `development`, `testing`, `demo`, `production` | Explicitly set |
| `JARVIS_DATABASE_URL` | SQLite database URL | Persistent writable path |
| `JARVIS_SECRET_KEY` | Session signing key | At least 32 non-placeholder characters |
| `JARVIS_FRONTEND_ORIGINS` | Comma-separated exact origins | HTTPS origin(s), nonempty |
| `JARVIS_LOG_LEVEL` | Python logging threshold | Optional, defaults to INFO |
| `JARVIS_AUTH_ENABLED` | Auth toggle | Must remain enabled |
| `JARVIS_SESSION_TTL` | Session lifetime in seconds | Validated positive duration |
| `JARVIS_RATE_LIMIT` | Sensitive requests per minute per client/route | Explicitly validated |
| `JARVIS_MAX_REQUEST_BYTES` | Maximum request body | Explicitly validated |

Production startup fails closed for missing/insecure secret, disabled auth, or insecure frontend origins. `NEXT_PUBLIC_API_BASE_URL` is public client configuration, not a secret. Database URLs currently support SQLite only; PostgreSQL portability is unsupported.
