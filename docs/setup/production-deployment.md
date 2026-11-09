# Production-Oriented Single-Host Deployment

This configuration is a hardened single-host starting point, not a high-availability service. Provide a valid DNS name, allow inbound 80/443 for Caddy certificate issuance, set a unique >=32-character secret, HTTPS frontend origin, persistent storage, and an admin account. Keep the `.env` file outside source control and restrict its filesystem permissions. Verify `/api/v1/health/live` and `/api/v1/health/ready` through the deployment, test sign-in and role boundaries, and make an off-host verified database backup before upgrades.

Rollback means returning to the prior image pair and restoring the matching pre-upgrade backup only to an isolated/new database path unless an operator explicitly performs a separate recovery procedure. No automated schema downgrade exists. The deployment has no MFA/SSO, centralized secrets, multi-host failover, distributed rate limiting, or PostgreSQL support.
