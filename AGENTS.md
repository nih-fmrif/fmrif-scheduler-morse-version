# AGENTS.md

Guidance for coding agents working in this repository.

## Scope
- Repository: `fmrif-scheduler-morse-version`
- Goal: make safe, minimal, testable changes and verify with the smallest relevant checks

## Read First
- `README.md` for setup and local workflow
- `docs/testing-strategy.md` for test boundaries and placement rules
- `docs/testing-guide.md` for quick test commands
- `docs/configuration-guide.md` for environment and config behavior
- `docs/security-review.md` for security constraints already implemented

## Workflow (Pixi First)
- Use Pixi tasks instead of ad-hoc commands when possible.
- If a needed workflow is repeated but missing from Pixi, add a clear Pixi task.

## Testing Rules
- Add or update the narrowest relevant tests first, then expand only as needed.
- Keep tests deterministic and environment-aware (skip or gate when required dependencies are absent).

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

- Route/integration setup tip: when DB is initialized via `sql/000-init.sh`, `membership` is a read-only view. Seed membership by writing `groupmembers`/`primarygroupmember` (and active group/user rows), not by inserting into `membership`.
- Mock-auth tip: `AUTH_TEST__SEED_GROUPS` accepts a comma-separated list (e.g., `DEV,JOINTEST`); invalid tokens are ignored and `DEV` is always ensured for deterministic `/join` coverage.
- Playwright proxy tip: with SSH SOCKS tunnels, browser traffic works with `socks5://...`, but request-context probes may require `socks5h://...` to avoid local-DNS `ENOTFOUND` during readiness checks.
- Support seeding tip: rows in `support` must use existing active user ids for both `filed_by` and `chg_by`; synthetic values fail FK checks during `sql/000-init.sh`.
- RBAC route-contract tip: contract sample paths should target SQL-seeded fixtures (for example `TEST` device / `DEV` group); for template-edit routes, seed one deterministic template id so role checks fail on auth issues instead of incidental `404`s.
- Mutating RBAC contract tip: use `RBAC_MUTATING_EXEMPTIONS` only for fixture-heavy write routes (for example signed-token PI flows); keep straightforward auth gates in `RBAC_MUTATING_EXPECTATIONS` so new route methods fail fast until role outcomes are declared.
- Jinja macro tip: `{% import "macros.html" as macros %}` does not carry request context by default; macros that need request-scoped values (like CSP nonce) should use a template-global helper or be imported `with context`.
