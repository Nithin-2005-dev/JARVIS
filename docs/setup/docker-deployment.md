# Docker Deployment

## Demo

Create a private `.env` based on `.env.example`, set a strong random `JARVIS_SECRET_KEY`, and provision an admin with the auth CLI against the same mounted DB. Run `docker compose up --build -d`; check `docker compose ps` and `docker compose logs`. `compose.yaml` builds separate non-root API and Next standalone images, binds app ports to loopback, uses a named SQLite volume, health checks, an explicit bridge, restart policies, and resource limits.

## Production-oriented HTTPS

Set `JARVIS_DOMAIN` and production environment values, then run `docker compose -f compose.yaml -f compose.production.yaml up --build -d`. Caddy terminates TLS and proxies to app containers on the private network. The API and frontend remain loopback-bound on the host. Persist and back up the named SQLite volume.

Images do not embed secrets. Compose configuration validation is tested; image builds and live health checks are reported separately in the Stage 10 report. This is a single-machine deployment, not a multi-replica architecture.
