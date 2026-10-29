# AGENTS.md

Guidance for coding agents working in this repository.

## Scope
- Repository: `fmrif-scheduler-morse-version`
- Goal: make safe, minimal, testable changes and verify with the smallest relevant checks.
- Default focus: local development and testing workflows unless the user asks for deployment work.

## Read First
- `README.md` for setup and local workflow
- `docs/testing-guide.md` for quick test commands
- `docs/testing-strategy.md` for test boundaries and placement rules
- `docs/configuration-guide.md` for environment and config behavior
- `docs/security.md` for security constraints already implemented

## Workflow (Pixi First)
- Use Pixi tasks instead of ad-hoc commands whenever possible.
- If a repeated workflow is missing from Pixi, add a task and document it.

## Testing Rules
- Add or update the narrowest relevant tests first, then expand only as needed.
- Keep tests deterministic and environment-aware (skip or gate when required dependencies are absent).
- Follow suite boundaries from `docs/testing-strategy.md`:
  - `tests/unit/` for unit and route tests (`@pytest.mark.route` for route tests)
  - `tests/playwright/integration/` for CI-friendly mock-auth browser tests
  - `tests/playwright/auth-flow/` and `tests/playwright/live-incident/` only when external auth/live env behavior is required
- For route changes, keep `tests/unit/route_contract.py` and `tests/unit/test_route_contract.py` aligned.

## Completion Checklist
- Run relevant tests via Pixi.
- Run `pixi run pre-commit` when changes are ready.
- Report:
  - files changed
  - tests run and outcomes
  - residual risks or follow-ups
- If blocked, state exactly what is blocked and what was validated anyway.

## Guardrails
- Do not weaken auth/session/security defaults unless explicitly requested.
- Prefer minimal diffs and avoid unrelated refactors.

## Knowledge Capture
- When you discover a reusable debugging/development insight, add it to this file if it meets all of these:
  - likely to recur
  - not obvious from code or existing docs
  - materially reduces future diagnosis or implementation time
- Keep additions short, general, and tool-agnostic; avoid incident-specific details.

## High-Value Repo Tips
- DB seed tip: after `sql/000-init.sh`, `membership` is a read-only view. Seed via `groupmembers` and `primarygroupmember`, plus active user/group rows.
- Mock auth tip: `AUTH_TEST__SEED_GROUPS` accepts comma-separated values (for example `DEV,JOINTEST`); invalid values are ignored and `DEV` is always included.
- Playwright proxy tip: browser traffic uses `socks5://...`; readiness probes may need `socks5h://...` to avoid local DNS `ENOTFOUND`.
- Support seed tip: `support.filed_by` and `support.chg_by` must reference existing active users or FK checks fail.
- RBAC contract tip: sample paths in route contracts should use SQL-seeded fixtures (for example `TEST` device and `DEV` group) so failures reflect auth behavior, not missing data.
- Mutating RBAC tip: keep straightforward write-route gate checks in `RBAC_MUTATING_EXPECTATIONS`; use `RBAC_MUTATING_EXEMPTIONS` only for fixture-heavy flows.
- Compose DB bootstrap tip: keep Postgres healthcheck `start_period` long enough for full init SQL to finish (for example `180s`) or compose may report `dependency failed to start` while migrations are still running.
- Jinja tip: `{% import "macros.html" as macros %}` does not carry request context by default; use a template-global helper or import macros `with context` when request-scoped values are needed.
- Seed-shape tip: keep `tests/unit/test_seed_shape_contract.py` aligned with changes in `sql/003-import-data.sql` and additive CSV mappings.
- SQLAlchemy isolation tip: tests that call `session.commit()` should use a dedicated connection with outer rollback + nested savepoint restart (`after_transaction_end`) to keep commits local.
