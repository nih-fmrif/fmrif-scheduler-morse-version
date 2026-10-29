# Testing Guide (Local + CI)

Use Pixi tasks for all local test runs:

```bash
pixi run test-unit
pixi run test-routes
pixi run test-integration-ci
```

## Local stack
- Start services for tests:
  - `bash run-compose.sh --no-app`
  - `bash run-compose.sh --no-app --resume` (reuse existing services/data)

## Notes
- `test-unit`, `test-routes`, and `test-integration*` run through `scripts/run-isolated-test-suite.sh`.
- The wrapper applies per-suite isolation for DB/Mailpit/runtime settings.
- Integration tasks start their own app server; no separate `pixi run serve` is required.

## Suite placement
Use [`testing-strategy.md`](testing-strategy.md) for suite boundaries and placement rules.

## Agent workflow
Agents should use [`agent-guidance-quickstart.md`](agent-guidance-quickstart.md).
