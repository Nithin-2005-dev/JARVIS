# Browser End-to-End Testing

Playwright tests in `frontend/e2e/` run against a live FastAPI and production-built Next server, with a seeded isolated demo database and a provisioned test responder. Set `E2E_BASE_URL`, `E2E_API_URL`, `E2E_USERNAME`, and `E2E_PASSWORD`, then run `npm run test:e2e` from `frontend/`. The suite exercises sign-in, overview, real incident navigation, recommendation lifecycle and feedback, sign-out/protected API behavior, viewport resizing, API failure handling, and competing blast-radius UI when the fixture provides it.

The Stage 10 local run seeded the real demo backend and provisioned a test responder; all four Playwright tests passed, including the competing-hypothesis scenario. A cached compatible Chromium executable was used because downloading the Playwright-pinned browser was constrained by this host. CI installs the pinned browser through Playwright. This is browser workflow coverage, not a complete cross-browser or security audit.
