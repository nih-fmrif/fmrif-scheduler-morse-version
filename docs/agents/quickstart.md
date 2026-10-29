# Agent Guidance: Quickstart

## Mandatory
Set a unique scope for this agent session before running stack/tests:

```bash
export FMRIF_RUNTIME_SCOPE=<unique-scope>
```

Keep that scope stable for the full thread (including post-compaction continuation). Do not rotate scope mid-thread unless intentionally creating a separate isolated run.

## Canonical flow
```bash
bash setup-dotenv.sh --profile compose
bash run-compose.sh --no-app
pixi run test-unit
pixi run test-routes
pixi run test-integration-ci
```

That canonical agent flow is compose-backed on purpose. Plain
`bash setup-dotenv.sh` now defaults to host-local PostgreSQL and is only the
right choice when you are intentionally avoiding `run-compose.sh`.

Targeted pytest runs still go through Pixi tasks:

```bash
pixi run test-unit -- tests/unit/test_some_file.py -q
pixi run test-unit-xdist -- tests/unit/test_some_file.py -q
pixi run test-routes -- tests/unit/test_some_route_file.py -q
pixi run test-routes-xdist -- tests/unit/test_some_route_file.py -q
```

When explicit test selectors are supplied, the task drops its default collection
root instead of widening scope.
`test-unit-xdist` and `test-routes-xdist` use `--dist loadgroup` so Mailpit
tests sharing one inbox stay on a single worker while the rest of the suite can
parallelize. Prefer `test-routes-xdist` for the fast full route pass and keep
`test-routes` as the serial fallback when debugging worker-specific behavior.

Reuse existing services/data when iterating:

```bash
bash run-compose.sh --no-app --resume
```

`--resume` is not free: if scope/project changes, bootstrap can be re-run and become expensive. Re-run compose only when needed (stack down, env changed, or explicit restart request).

## Rules
- Always use Pixi tasks for tests.
- Do not run ad-hoc test commands that bypass wrappers unless explicitly debugging isolation internals.
- Prefer `pixi run <suite> -- <selector ...>` for narrowed pytest runs.
- If scope is already in use, pick a different `FMRIF_RUNTIME_SCOPE`.

## Deep dive
For isolation internals and troubleshooting, see [runtime isolation guide](isolation-validation.md).
