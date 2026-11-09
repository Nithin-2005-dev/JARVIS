# Frontend testing

The frontend uses Vitest, jsdom, and Testing Library. `npm test` covers overview, incident explorer/detail, service list/detail, intelligence, recommendation rendering/lifecycle action, loading/empty/error states, dependency direction, node selection, and graph zoom controls. Route tests mock API responses; separate backend TestClient tests validate the real HTTP adapter. `npm run typecheck` runs TypeScript validation; `npm run lint` uses Next.js core web vitals rules; `npm run build` creates the production bundle. Stage 9 completed these checks successfully (12 frontend tests passed).

API integration tests use FastAPI TestClient with temporary SQLite files and cover empty states, pagination validation, missing records, graph registry retrieval, CORS allow-listing, and recommendation write errors. The full Python regression suite remains under `tests/`.
