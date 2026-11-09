# Security Model

## Authentication and sessions

The API uses usernames and Argon2id password hashes (`argon2-cffi`). Passwords are accepted only by login or the interactive user CLI and are never persisted or logged. A signed, timed `HttpOnly` session cookie expires according to `JARVIS_SESSION_TTL`; cookies use `SameSite=Strict`, and `Secure` is enabled in production. The serializer uses the configured secret and rejects expired or tampered sessions. Logout clears both session and CSRF cookies. Login and mutation requests require a CSRF cookie/header match; mutation requests also require an exact configured Origin.

Users are provisioned through `python -m payflow_simulator.http_api.auth_cli create-user`. There is no public registration or password-reset route. Admin API routes can create users and update role/active state. Use the CLI to provision the initial administrator.

## Roles

| Capability | admin | responder | viewer |
|---|---:|---:|---:|
| Read incidents, RCA, intelligence, recommendations | Yes | Yes | Yes |
| Update recommendation status / feedback | Yes | Yes | No |
| Manage user accounts | Yes | No | No |

RBAC is enforced in FastAPI middleware. The frontend only reflects the current role; it is not the security boundary. Denials and authentication events are written to the security audit table without credentials.

## API safeguards

- Configured exact-origin CORS allow-list with credentials.
- Login and recommendation writes have per-process rate limits.
- Request bodies have configured size limits, including chunked requests.
- Pydantic request schemas constrain fields and lengths.
- API errors return safe messages and request IDs; internal exception details remain server-side.
- Security headers, no-store, and production HSTS are added.
- OpenAPI docs are limited to development/testing.
- No arbitrary SQL, shell command, or request-controlled file path endpoint exists.

The limiter and metrics are in-memory and per process; do not horizontally scale this deployment and assume global enforcement.
