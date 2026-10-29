# Testing Strategy

## Suite Taxonomy

1. Unit tests (`pytest`, fast)
- Location: `tests/unit/`
- Scope: Python-only logic, helpers, auth internals
- Network/browser: none
- CI: yes

2. Route tests (`pytest`, no browser)
- Location: `tests/unit/` (marked with `@pytest.mark.route`)
- Scope: Flask route/HTTP behavior (status codes, redirects, CSRF, auth/session behavior)
- Network/browser: none
- CI: yes
- Database bootstrap: `tests/unit/conftest.py` initializes `fmrif_scheduler_test` via `sql/000-init.sh` so route tests use production-like SQL objects.
- Contract enforcement: `tests/unit/route_contract.py` and `tests/unit/test_route_contract.py`
  - Every registered Flask route rule and method must be declared in `ROUTE_EXPECTATIONS`.
  - Every protected `GET` route must declare per-role expected status in `RBAC_GET_EXPECTATIONS` for mock roles (`admin`, `member`, `dev`, `tech`, `inactive`).
  - Every protected mutating route method must define gate expectations in `RBAC_MUTATING_EXPECTATIONS` or explicit exemptions.
  - Mutating routes must either be in `BEHAVIOR_TEST_REQUIREMENTS` (with a `@pytest.mark.covers_route(rule, method)` test) or `BEHAVIOR_TEST_EXEMPTIONS`.

3. Integration tests (`Playwright`, CI-friendly)
- Location: `tests/playwright/integration/`
- Scope: end-to-end workflows using test-only mock auth sessions
- Auth mode: `PLAYWRIGHT_AUTH_MODE=mock`, `AUTH_TEST__ENABLED=true`
- CI: yes

4. Auth-flow tests (`Playwright`, real Entra)
- Location: `tests/playwright/auth-flow/`
- Scope: real Entra login behavior
- Auth mode: `PLAYWRIGHT_AUTH_MODE=entra`
- CI: no (requires NIH VPN / staging-capable environment)

5. Live-incident tests (`Playwright`, manually gated)
- Location: `tests/playwright/live-incident/`
- Scope: issues reproducible only against live environments or evolving production-like data
- CI: no

6. Old-bootstrap compatibility verification (`pytest`, opt-in)
- Location: `tests/unit/test_old_bootstrap_compat.py`
- Scope: verifies the current SQL chain still accepts rooted data derived from the old repository in both `pre-018` and `post-018` researcher-code stages
- Runtime: requires reachable Postgres and access to the old repo checkout used by `scripts/bootstrap-old-compat-db.sh`
- CI: optional/manual by default

## Shared Test Infrastructure

- Authenticated Playwright integration tests share `tests/playwright/support/auth-fixture.ts`.
- Mode behavior:
  - `PLAYWRIGHT_AUTH_MODE=mock`: creates a test session via `POST /auth/test/session` with `AUTH_TEST__SHARED_SECRET`.
    - `session_key` is required.
    - mock usernames/emails are scoped by `session_key`.
    - this isolates mock-auth/profile state across parallel workers on one shared database.
  - `PLAYWRIGHT_AUTH_MODE=entra`: uses saved storage state or interactive credentials path.
- This enables identical integration specs across mock CI and real-auth workflows.

## New Test Placement Guide

1. If it validates pure Python logic without browser interaction, add it to `tests/unit/`.
2. If it validates Flask route/HTTP behavior without browser interaction, add it to `tests/unit/` with `@pytest.mark.route` (run via `pixi run test-routes`) and update RBAC route contracts as needed.
3. If it validates UI workflows and can run without external NIH VPN/staging access, add it to `tests/playwright/integration/`.
4. If it requires live Entra/NIH VPN/staging access, add it to `tests/playwright/auth-flow/`.
5. If only reproducible against live environments/data, use `tests/playwright/live-incident/` and include a migration plan.
6. If it verifies compatibility of the current SQL bootstrap against old rooted data, use the opt-in old-bootstrap compatibility test path instead of the fast suites.

## Commands (Pixi-first)

Prerequisites:
- `pixi` installed
- `.env` created (`bash setup-dotenv.sh`)

Unit tests:
```bash
pixi run test-unit
```

Route tests:
```bash
pixi run test-routes
```

Integration tests (CI mode, mock auth):
```bash
pixi run test-integration
```

The `test-unit`, `test-routes`, and `test-integration*` tasks are wrapped by
`scripts/run-isolated-test-suite.sh`, which assigns suite-scoped test DB names
and Mailpit ports so those suites can run in parallel without sharing test mail
or route-template DB resources.
The wrapper auto-derives a test scope namespace and fails fast when the same
suite starts concurrently with the same scope.

For integration tasks, the wrapper also sets a suite-scoped runtime
`PGDATABASE` and refreshes it from a suite template DB. The template is rebuilt
from `sql/000-init.sh` only when SQL inputs change (or when forced), which
keeps mock-auth/profile state deterministic between runs with lower startup
overhead than reseeding every run. You can bypass the runtime reset with
`FMRIF_INTEGRATION_DB_RESET=false` for intentional stateful debugging.
Use `FMRIF_INTEGRATION_DB_REBUILD_TEMPLATE=true` to force template refresh or
`FMRIF_INTEGRATION_DB_TEMPLATE_NAME` to override template naming.

Parallel caveat:

- The isolated integration database removes cross-suite interference.
- `session_key` removes same-user mock-auth collisions inside one shared test database.
- Neither mechanism prevents two tests from intentionally mutating the same business rows at the same time.

Auth-flow tests (credentials mode):
```bash
pixi run test-auth-flow-credentials
```
Requires `OAUTH_TEST_USERNAME` and `OAUTH_TEST_PASSWORD` in `.env`.

Auth-flow tests (storage-state mode):
```bash
pixi run test-auth-flow-storage-state
```
`PLAYWRIGHT_STORAGE_STATE` is optional and defaults to `./playwright-auth.${FMRIF_RUNTIME_SCOPE:-default}.json`.

Generate storage state (headed):
```bash
pixi run generate-auth-storage-state
```
Requires `OAUTH_TEST_USERNAME` and `OAUTH_TEST_PASSWORD` in `.env`.
`PLAYWRIGHT_STORAGE_STATE` is optional and defaults to `./playwright-auth.${FMRIF_RUNTIME_SCOPE:-default}.json`.

Live-incident tests (manual/gated):
```bash
pixi run test-live-incident
```

Run pre-commit hooks:
```bash
pixi run pre-commit-install
pixi run pre-commit
```

## Live-Incident Test Lifecycle

- Add an incident header with date/reason.
- Keep assertions robust to data drift.
- Keep scope minimal to one behavior.
- Review periodically:
  - If the behavior becomes reproducible in local fixtures, migrate to `tests/playwright/integration/`.
  - If business logic only, migrate to `tests/unit/`.
  - Remove the live-incident variant after migration.
