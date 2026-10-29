# Testing Guide (Local + CI)

Use Pixi tasks for all local test runs:

```bash
pixi run test-unit
pixi run test-unit -- tests/unit/test_some_file.py -q
pixi run test-unit-xdist
pixi run test-routes
pixi run test-routes -- tests/unit/test_some_route_file.py -q
pixi run test-integration
pixi run test-integration-ci
pixi run test-debian-smoke
pixi run test-debian-integration
pixi run test-integration-heavy
pixi run test-load-moderate
pixi run test-load-moderate-scheduler
pixi run test-load-moderate-notify
```

## Local stack
- Start services for tests:
  - `bash run-compose.sh --no-app`
  - `bash run-compose.sh --no-app --resume` (reuse existing services/data)

## Deployment-adjacent runtime checks
- `pixi run test-debian-smoke` and `pixi run test-debian-integration` exercise
  the Debian-packaged runtime on the supported Debian 13 baseline.
- Use `test-debian-smoke` when changing dependency pins, runtime packaging,
  startup/config loading, SQL bootstrap or Alembic behavior, DB runtime code,
  or nginx/proxy/header handling.
- Use `test-debian-integration` when those changes can also affect auth/session
  behavior, callback routing, CSP/static asset delivery, or any browser-visible
  flow that depends on the packaged runtime path.
- For ordinary Python logic changes already covered by unit/route/Pixi browser
  suites, the Debian tasks are usually optional.
- Treat failures there as deployment-relevant even when the Pixi-managed path is
  green.
- These tasks improve repo-local and CI confidence, but they do not replace the
  host verification runbooks in `fmrif-scheduler-docs/`.

## Notes
- `test-unit` and `test-routes` use `scripts/run-target-aware-pytest-suite.py`, which forwards into `scripts/run-isolated-test-suite.sh`.
- `test-unit-xdist` is an opt-in unit-only variant that adds `-n auto` on top of the same wrapper.
- `test-integration*` runs directly through `scripts/run-isolated-test-suite.sh`.
- `test-integration` is the local-default browser run; `test-integration-ci` uses a CI-friendly reporter.
- The wrapper applies per-suite isolation for DB/Mailpit/runtime settings.
- Interface policy: when explicit test selectors are supplied, they replace the default collection root for that task. Tasks must not silently widen a narrowed request.
- Keep `test-routes` on the default serial task unless worker-specific route isolation is added deliberately.
- Integration tasks start their own app server; no separate `pixi run serve` is required.
- The default integration tasks exclude Playwright tests tagged `@heavy`; run those explicitly with `pixi run test-integration-heavy`.
- When a browser smoke pass is sufficient, skip the full browser matrix and target Chromium directly:

```bash
pixi run test-integration-ci --project=chromium
```

- The main CSP/runtime browser smokes live in `tests/playwright/integration/security-headers.spec.ts`,
  `tests/playwright/integration/device-grid-errors.spec.ts`, and
  `tests/playwright/integration/csp-page-smoke.spec.ts`.
- The page-smoke spec covers the auth callback, template editor, and RBAC views without requiring live Entra access.

- To verify the final served response headers at the current edge (local, compose, or deployed), run:

```bash
python3 scripts/check-edge-security-headers.py
```

- By default, the script probes `http://localhost:${APP_PORT}` outside production.
- In production, it derives the target from `ENTRA__REDIRECT_URI` by stripping `/auth/callback`.
- Override `--base-url` only when you intentionally want to probe a different edge.
- The edge checker now expects the stricter default CSP, including the substituted script nonce, `strict-dynamic`, `report-to csp-endpoint`, and `Reporting-Endpoints: csp-endpoint="/csp-report"`.

- `test-load-moderate` runs two headless Locust passes back to back against the isolated integration app: a scheduler-only pass with mail suppressed, then a notification-inclusive pass with mail enabled.
- The load tasks boot the app under Gunicorn by default so request handling is closer to production than the single-process Flask dev server.
- `test-load-moderate-scheduler` runs only the scheduler-only baseline pass.
- `test-load-moderate-notify` runs only the notification-inclusive pass.
- The load tasks default to 10 users, spawn rate 2, and run time 5 minutes per pass.
- The combined task writes separate reports under `test-results/locust-moderate-scheduler*` and `test-results/locust-moderate-notify*`.
- Override load parameters with `LOAD_USERS`, `LOAD_SPAWN_RATE`, `LOAD_RUN_TIME`, or `LOAD_DEVICE` when you need a shorter smoke run or a different target.
- Override server behavior with `LOAD_APP_SERVER=flask` for debugging or `LOAD_GUNICORN_WORKERS`, `LOAD_GUNICORN_WORKER_CLASS`, `LOAD_GUNICORN_THREADS`, and `LOAD_GUNICORN_TIMEOUT` for Gunicorn tuning.
- Old-bootstrap compatibility is verified separately from the normal fast suites.
  - Use [`sql-bootstrap-compatibility.md`](sql-bootstrap-compatibility.md).
  - The opt-in regression check is:

```bash
OLD_BOOTSTRAP_COMPAT_RUN=true pytest tests/unit/test_old_bootstrap_compat.py -q
```

- Convenience wrapper for the SQL compatibility verifier:

```bash
pixi run test-old-bootstrap-compat
```

  - Set `OLD_BOOTSTRAP_SKIP_REBUILD=true` to reuse an already-bootstrapped old compatibility DB and skip the slower source rebuild step.

## Suite placement
Use [`testing-strategy.md`](testing-strategy.md) for suite boundaries and placement rules.

## Agent workflow
Agents should use [`agent-guidance-quickstart.md`](agent-guidance-quickstart.md).
