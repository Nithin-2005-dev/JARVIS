# Stage 10 Initial Architecture and Release Readiness Audit

**Audit date:** 2026-11-09  
**Repository revision:** `d2ef3f1` (`feat(command-center): implement incident investigation dashboard`)  
**Scope:** Stages 1–9 code, configuration, tests, documentation, and Git state. No runtime code was changed before this audit was written.

## Repository state and architecture

The committed history contains the Stage 1–9 milestone commits. The only pre-existing worktree item is an unrelated untracked file named `do`; it is not part of the application and is left untouched. Stage 1–8 processing engines are Python modules using SQLite-backed stores. Stage 9 adds a FastAPI composition adapter and a Next.js frontend. The adapter reuses existing stores, while stores open their own SQLite connections. The frontend calls the API directly using `NEXT_PUBLIC_API_BASE_URL`.

The demo pipeline composes existing Python APIs and can delete the database selected by its `--reset` option. That destructive behavior is scoped to an explicit local demo command and must not be reused for recovery testing.

## Findings before Stage 10 changes

| Area | Finding | Release risk |
|---|---|---|
| Authentication and authorization | No login/session or role checks exist. All API routes, including recommendation writes, are unauthenticated. | High for any network-exposed deployment. |
| Browser request security | API calls do not establish a login or CSRF flow. CORS defaults to localhost and credentials are disabled, but this is not authorization. | High if origin settings are loosened. |
| API surface | `/api/docs` is enabled in the app. There is no explicit body-size limit, rate limit, standard request ID, or security-header middleware. Unexpected errors are masked from clients, but logger traceback context is local only. | Medium. |
| Configuration | Database and CORS settings are read directly in multiple modules. There is no single validated environment model or `.env.example`. No production secret validation exists. | High; unsafe deployment configuration is easy. |
| SQLite and migrations | Existing stores use SQLite transactions and bound SQL parameters; some enable WAL, busy timeout, and foreign keys, but not uniformly. Tables are created by store constructors, with ad hoc column checks. No central schema version or migration runner exists. | Medium for a local/single-instance database; unsuitable for multi-writer scale without further work. |
| Backups | No supported SQLite backup/restore utility or tested recovery procedure exists. | High for persistent incident history. |
| Deployment | No Dockerfiles, Compose deployment, or CI workflows exist. | High for reproducibility. |
| Logging and health | A JSON formatter exists for processing logs, but API request/auth lifecycle logging, correlation IDs, readiness/database checks, and metrics are absent. Existing health is a public constant response rather than a dependency-aware readiness check. | Medium. |
| Performance | Stage-specific synthetic evaluation exists, but there is no shared repeatable capacity harness for 1k/10k/100k events or API percentiles/memory. | Unknown capacity; must measure rather than infer. |
| End-to-end testing | Backend and frontend unit tests exist. There are no browser automation tests or authenticated flows. | Major user-journey gap. |
| Dependency management | Frontend has a lockfile; backend has only a broad Stage 9 requirements file (`fastapi>=0.110,<1`, etc.) and no root pinned lock. | Reproducibility/security gap. |
| Existing functionality | Stages 1–9 expose deterministic simulation, ingestion, processing, correlation, RCA, dependency graph, intelligence, recommendation lifecycle, dashboard reads, and recommendation writes. These semantics and historical snapshots must remain unchanged. | Regression constraint. |

## Data access and injection review

Store SQL observed in the audit uses SQLite APIs; data values are generally passed as bound parameters. Dynamic SQL in the incident status query is limited to a fixed internal branch. No arbitrary SQL interface or API command execution was found. Database paths are accepted as local configuration; deployment must provide a fixed configured database URL/path and must not derive it from request values.

## Deployment suitability

SQLite remains appropriate for development, deterministic demos, and a single application instance with modest write concurrency. WAL and busy timeout help local concurrency, but SQLite is a single-writer database; multiple replicas or high write contention are unsupported. This stage will keep SQLite as the supported backend unless evidence justifies introducing a second database. No claim of PostgreSQL portability will be made.

## Audit limitations

This is a code/configuration audit, not a penetration test, formal threat model certification, or high-volume production capacity study. Dependency vulnerability status must be checked with current scanners during this milestone. Docker daemon availability and browser installation will be verified before reporting test results.

## Audit disposition

Proceed with a bounded hardening change: validated settings; authenticated and role-gated API; cookie/CSRF protections; request controls and safer operational endpoints; schema versioning; backup/restore tooling; container/CI support; and reproducible operational tests. Do not alter correlation, RCA, intelligence, dependency, or recommendation scoring semantics.
