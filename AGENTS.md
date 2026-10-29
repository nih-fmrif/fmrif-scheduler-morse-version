# AGENTS.md

Guidance for coding agents working in this repository.

## Scope
- Repository: `fmrif-scheduler-morse-version`
- Goal: make safe, minimal, testable changes and verify with the smallest relevant checks.
- Default focus: local development and testing workflows unless the user asks for deployment work.

## Required Agent Flow
1. Set a unique runtime scope for this agent session:
   `export FMRIF_RUNTIME_SCOPE=<unique-scope>`
   - Treat this as sticky for the full thread (including post-compaction continuation).
   - Do not change scope mid-thread unless explicitly starting a separate isolated run, and state why.
2. Use repo wrappers/tasks (do not bypass them):
   - `bash setup-dotenv.sh`
   - `bash run-compose.sh --no-app` (initial setup) or `bash run-compose.sh --no-app --resume` (explicit reuse)
   - `pixi run test-unit|test-routes|test-integration-ci`
3. Startup decision rules (must follow):
    - Initial setup in a new thread/scope:
      - Run `bash setup-dotenv.sh`, then `bash run-compose.sh --no-app`.
    - Iteration preference:
      - In the same thread/scope, treat the compose stack as stateful and prefer keeping it running between commands.
      - Avoid shutting it down or fully recreating during continuation unless you need it explicitly stopped/restarted.
      - Use `--resume` for refreshes in this case to avoid repeated bootstrap overhead.
    - Post-compaction continuation in the same thread/scope:
      - Do **not** restart compose by default.
      - First verify stack health (for example: quick command/test task succeeds, required ports respond, or the next Pixi task starts cleanly).
      - Reuse the existing running stack when healthy.
   - Restart/recreate the stack only when needed:
     - stack is down/unhealthy, scope changed, environment changed, or user explicitly requests restart.
   - `--resume` caveat:
     - `run-compose.sh --resume` is not free; with scope/project drift it can still trigger expensive bootstrap work.
     - Use `--resume` only after deciding a compose invocation is necessary.
4. Use Pixi tasks instead of ad-hoc commands whenever possible.

## Read First
- `README.md` (human/local quickstart)
- `docs/testing-guide.md` (test command map)
- `docs/agent-guidance-quickstart.md` (minimal agent workflow)

## Deep Agent Docs (Only When Needed)
- `docs/agent-guidance-isolation-validation.md` (isolation internals, lock/collision behavior, validation runbook)
- `docs/agent-guidance-playwright.md` (browser-test specifics)

## Testing Rules
- Add or update the narrowest relevant tests first, then expand only as needed.
- Keep tests deterministic and environment-aware.
- Follow suite boundaries from `docs/testing-strategy.md`:
  - `tests/unit/` for unit and route tests (`@pytest.mark.route` for route tests)
  - `tests/playwright/integration/` for CI-friendly mock-auth browser tests
  - `tests/playwright/auth-flow/` and `tests/playwright/live-incident/` only when external auth/live env behavior is required
- For route changes, keep `tests/unit/route_contract.py` and `tests/unit/test_route_contract.py` aligned.

## Completion Checklist
- Run relevant tests via Pixi.
- Run `pixi run pre-commit` when changes are ready.
- Report files changed, tests run/outcomes, and residual risks/follow-ups.
- If blocked, state exactly what is blocked and what was validated.

## Guardrails
- Do not weaken auth/session/security defaults unless explicitly requested.
- Prefer minimal diffs and avoid unrelated refactors.
