# Scheduler app

## Documentation
- [Project Documentation](docs/README.md)
- [Deployment Considerations](docs/deployment-considerations.md)

## Human Quickstart
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
   - full route suite: `pixi run test-routes`
   - targeted route run: `pixi run test-routes -- tests/unit/test_some_route_file.py -q`
   - `pixi run test-integration-ci`
   - heavier scheduler contention runs: `pixi run test-integration-heavy`
   - moderate mixed-traffic load run (default runs both scheduler-only and notification-inclusive passes under Gunicorn): `pixi run test-load-moderate`
   - scheduler-only pass: `pixi run test-load-moderate-scheduler`
   - notification-inclusive pass: `pixi run test-load-moderate-notify`

## Notes
- Use `run-compose.sh` for containerized startup; direct `docker compose` is not supported in this workflow.
- In the full compose stack, `APP_PORT` is served by nginx and proxied to the internal Gunicorn app container.
- The full compose stack defaults to `linux/amd64` for deployment parity, and the app image derives its Python environment from the shared repository `pixi.toml` while narrowing the in-image solve to `linux-64` instead of relying on a lockfile-frozen install.
- Host mode defaults to Werkzeug for fast iteration; use `pixi run serve-gunicorn` when you want host-side serving closer to deployment behavior.
- `pixi run serve` and `pixi run serve-gunicorn` now wait for local readiness and then run `scripts/check-edge-security-headers.py`; in production that probe derives its target from `ENTRA__REDIRECT_URI` by stripping `/auth/callback`.
- Higher-level browser tooling now uses `TEST_BASE_URL`; root-only `/auth/callback` deployment is the supported model.
- App/bootstrap DB settings come from `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`.
- Interface policy: if a task accepts explicit selectors, explicit selectors win over default roots; task interfaces must not silently widen a narrowed request.
- For setup details, see [docs/containerized-postgres.md](docs/containerized-postgres.md) and [docs/testing-guide.md](docs/testing-guide.md).
