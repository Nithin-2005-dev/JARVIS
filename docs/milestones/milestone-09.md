# Milestone 09 — Command Center

## Scope and architecture

Added a Next.js Command Center and FastAPI adapter over the existing Stage 3–8 stores. Existing analysis remains in Python engines; the frontend only renders persisted report values. Recommendation lifecycle writes delegate to Stage 8 storage validation. The UI treats RCA outputs as hypotheses, anomaly scores as detector outputs, and blast radius as potential structural impact.

## Features

- Overview counts and actual stored incident severity distribution, with explicit unknown service health.
- Incident search/filter/sort, investigation timeline, correlation evidence, RCA evidence sections, separate stored blast-radius scenarios, findings, and recommendation state actions.
- Service registry/detail with dependency direction, related records, and findings/recommendations.
- Intelligence and recommendation explorers with empty, loading, and error states.
- FastAPI v1 endpoints for those persisted records plus bounded collection queries, CORS allow-list, status update, and feedback.
- Deterministic demo workflow using existing Stage 1–8 APIs.

## Verification (actual)

- Backend and Stage 1–8 regression suite: **109 tests passed**, including 5 Stage 9 API tests; final run took about 10 seconds.
- Frontend component and route suite: **12 tests passed** across overview, incident explorer/detail, services, intelligence, recommendations, loading/empty/error states, and graph controls.
- `npm run typecheck`, `npm run lint`, and `npm run build` passed. Next.js generated all seven application routes plus the not-found route.
- Live local API smoke test on `127.0.0.1:8765`: health, overview, incidents, services, and recommendations returned HTTP 200. TestClient integration retrieved incident events, RCA, blast radius, intelligence, recommendation detail, service dependencies, and history. Recommendation acknowledgement returned 200; feedback returned 201.
- End-to-end PayFlow run: 63 events generated/received/processed, 9 incidents, and 11 Stage 7 findings. 40 Stage 8 recommendation records were available.
- Repeated run without reset: 63 generated/received, 0 newly processed, 9 incidents, and 11 findings. This verifies deterministic fixture replay with existing stage idempotency behavior.
- One local request per API route group against this SQLite demo DB (FastAPI TestClient, no concurrency): overview 464 ms, incident list 240 ms, service list 307 ms, findings 128 ms, recommendation list 305 ms, incident detail with 7 events 193 ms. These are environment observations, not performance guarantees.

Commands: `PYTHONPATH=. /tmp/jarvis-stage9-venv/bin/python -m unittest discover -s tests -v`; from `frontend/`, `npm test`, `npm run typecheck`, `npm run lint`, and `npm run build`. Node.js 24.21.0 was used in this environment.

## Limitations

No authentication, live health state, streaming, or automatic remediation. Demo performance is local and not a production capacity claim. The SVG graph is intentionally small and suited to the current five-service PayFlow graph; larger graphs need a dedicated layout/virtualization strategy.
