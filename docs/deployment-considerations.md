# Deployment Boundary

This document keeps the deployment-adjacent facts that matter to engineers
working on the codebase. It is not the operator runbook.

Operator procedures, host verification, and sensitive deployment detail belong
in the private `fmrif-scheduler-docs` submodule:

- `fmrif-scheduler-docs/README.md`
- `fmrif-scheduler-docs/deployment.md`
- `fmrif-scheduler-docs/host-verification-path.md`
- `fmrif-scheduler-docs/db-operations.md`

## Supported Target

- Debian 13 with system-installed services is the supported operator target.
- PostgreSQL 17 is the supported host baseline.
- Initial deployment may bootstrap from a `003`-contract legacy dump and then
  stamp Alembic.
- After the first Alembic stamp, live app-relevant schema changes must go
  through Alembic.
- Earlier Debian 12 proof work informed the tooling, but current support and
  documentation target Debian 13.

## What Stays In This Repo

- Pixi tasks and local validation flows needed to develop safely
- high-level serving, proxy, and CSP invariants
- schema ownership rules documented in
  [alembic-management-model.md](alembic-management-model.md)
- Debian runtime checks that catch packaging or proxy-path differences before
  host deployment

## What Stays In The Submodule

- host-specific install, redeploy, and maintenance commands
- service units, nginx wiring, filesystem paths, and verification scripts
- backup, restore-drill, credential-rotation, and host-proof runbooks
- details that would be noisy or sensitive in the main repository

## Local Validation Modes

- `pixi run serve`
  for fast host-mode development under Werkzeug
- `pixi run serve-gunicorn`
  for host-mode Gunicorn parity without the full proxy stack
- `bash run-compose.sh`
  for the closest repo-local nginx-backed path
- `pixi run test-debian-smoke`
  for Debian-packaged runtime smoke checks
- `pixi run test-debian-integration`
  for Debian-packaged runtime browser verification

`bash run-compose.sh` is the closest repo-local proxy path because requests flow
through nginx before reaching Gunicorn.

## Invariants Worth Remembering

- Treat `APP_PORT` as the user-facing application port in every mode.
- In full compose mode, `APP_PORT` belongs to nginx, not the app container.
- The local proxy mental model is:

  ```text
  host client -> localhost:APP_PORT -> nginx:80 -> app:5051
  ```

- The compose path trusts `X-Forwarded-For`, `X-Forwarded-Proto`, and
  `X-Forwarded-Host`. Do not assume `X-Forwarded-Port` is authoritative in
  Docker-published local proxy setups.
- `ENTRA__REDIRECT_URI` must end at `/auth/callback`.
- The final edge should have one CSP owner. Use
  `python3 scripts/check-edge-security-headers.py` to confirm the final served
  response headers rather than assuming direct-app checks are enough.

## Initial Deployment Contract

The supported high-level workflow is:

1. bootstrap an empty target database with `sql/000-init.sh`
2. import `003`-contract data and relationship hydration
3. verify the resulting schema and data state
4. stamp the Alembic baseline and verify ownership
5. start the app and run smoke checks
6. take the first post-deployment backup

For local validation of that contract, the repo provides:

```bash
pixi run rehearse-initial-deployment -- --json
```

That command is a local contract test against a scratch database. It is useful
for development and CI, but it is not a substitute for operator-side host
verification.
