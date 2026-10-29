# Scheduler app

## Documentation
- [Project Documentation](docs/README.md)
- [Configuration Guide](docs/configuration-guide.md)
- [Testing Guide](docs/testing-guide.md)
- [Alembic Management Model](docs/alembic-management-model.md)
- [Deployment Boundary](docs/deployment-considerations.md)

## Human Quickstart
`pixi >= 0.66.0` is required for this workspace.

1. Generate local `.env`:
   `bash setup-dotenv.sh`
2. Start local services:
   - light dev stack (postgres + Mailpit): `bash run-compose.sh --no-app`
   - light dev stack reuse: `bash run-compose.sh --no-app --resume`
   - proxy-aware full stack (nginx + app + postgres + Mailpit): `bash run-compose.sh`
   - proxy-aware full stack reuse: `bash run-compose.sh --resume`
3. Run the app (optional):
   - fast host-mode dev server (Werkzeug + automatic edge-header gate): `pixi run serve`
   - host-mode Gunicorn parity check (same startup gate): `pixi run serve-gunicorn`
4. Run tests:
   - full unit suite: `pixi run test-unit`
   - targeted unit run: `pixi run test-unit -- tests/unit/test_some_file.py -q`
   - optional parallel unit run: `pixi run test-unit-xdist`
   - full route suite: `pixi run test-routes`
   - targeted route run: `pixi run test-routes -- tests/unit/test_some_route_file.py -q`
   - browser integration suite: `pixi run test-integration`
   - `pixi run test-integration-ci`
   - Debian runtime smoke: `pixi run test-debian-smoke`
   - Debian runtime browser integration: `pixi run test-debian-integration`
   - heavier scheduler contention runs: `pixi run test-integration-heavy`
   - moderate mixed-traffic load run (default runs both scheduler-only and notification-inclusive passes under Gunicorn): `pixi run test-load-moderate`
   - scheduler-only pass: `pixi run test-load-moderate-scheduler`
   - notification-inclusive pass: `pixi run test-load-moderate-notify`
5. Operational helpers:
   - DB reachability: `pixi run check-db-health -- --json`
   - DB backup/disk/restore-drill posture: `pixi run check-db-posture -- --json`
   - initial-deployment rehearsal (runs against a scratch DB derived from `PGDATABASE`): `pixi run rehearse-initial-deployment -- --json`

## Notes
- Use `run-compose.sh` for containerized startup; direct `docker compose` is not supported in this workflow.
- The supported deployment target is Debian 13 with system-installed services. Operator runbooks, host verification, and sensitive deployment detail live in `fmrif-scheduler-docs/`.
- The supported production posture is hybrid with one hard boundary: a one-time initial deployment may bootstrap from a `003`-contract dump, but every live app-relevant schema change after that point must go through Alembic.
- In the full compose stack, `APP_PORT` is served by nginx and proxied to the internal Gunicorn app container.
- Host mode defaults to Werkzeug for fast iteration; use `pixi run serve-gunicorn` when you want host-side serving closer to deployment behavior.
- The shared Pixi default environment now carries only production/runtime Python dependencies; the `dev` feature layers test and lint tooling on top without depending on an editable local package build.
- `pixi run serve` and `pixi run serve-gunicorn` now wait for local readiness and then run `scripts/check-edge-security-headers.py`; in production that probe derives its target from `ENTRA__REDIRECT_URI` by stripping `/auth/callback`.
- Higher-level browser tooling now uses `TEST_BASE_URL`; root-only `/auth/callback` deployment is the supported model.
- App/bootstrap DB settings come from `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`.
- Interface policy: if a task accepts explicit selectors, explicit selectors win over default roots; task interfaces must not silently widen a narrowed request.
- `pixi run test-unit-xdist` is an opt-in unit-only variant; keep `test-routes` on the default serial task unless route-worker isolation is designed explicitly.
- Run `pixi run test-debian-smoke` when changing dependency/runtime packaging, startup/config loading, bootstrap or Alembic flows, DB driver/runtime behavior, or proxy/header wiring. Run `pixi run test-debian-integration` when those changes can also affect auth/session flows, callback routing, CSP/static assets, or browser-visible behavior on the packaged runtime. For ordinary logic changes already covered by the Pixi suites, the Debian tasks are usually optional.
- For setup details, see [docs/containerized-postgres.md](docs/containerized-postgres.md) and [docs/testing-guide.md](docs/testing-guide.md).
