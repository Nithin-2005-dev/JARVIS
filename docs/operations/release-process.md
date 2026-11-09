# Release Process

## Candidate gates

Run the documented backend tests, frontend tests/typecheck/lint/build, dependency audits, migration/bootstrap and isolated backup restore tests, browser E2E against a real seeded database, Compose validation/build/health checks, and the reproducible performance harness. Review the Stage 10 report and unresolved limitations before assigning a semantic version or tagging a release. A candidate is not created by this milestone unless all required gates pass.

## Release contents and rollback

Record application revision, Python lock, frontend lock, image digests, environment requirements, database backup, and release notes. Back up before deployment; validate liveness/readiness and a representative authenticated investigation. Roll back to the previous images and compatible data snapshot. There is no general downgrade migration, so never assume an older binary can safely use a newer schema. Do not commit secrets or database snapshots.
