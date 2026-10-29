# Agent Guidance: Quickstart

## Mandatory
Set a unique scope for this agent session before running stack/tests:

```bash
export FMRIF_RUNTIME_SCOPE=<unique-scope>
```

Keep that scope stable for the full thread (including post-compaction continuation). Do not rotate scope mid-thread unless intentionally creating a separate isolated run.

## Canonical flow
```bash
bash setup-dotenv.sh
bash run-compose.sh --no-app
pixi run test-unit
pixi run test-routes
pixi run test-integration-ci
```

Reuse existing services/data when iterating:

```bash
bash run-compose.sh --no-app --resume
```

`--resume` is not free: if scope/project changes, bootstrap can be re-run and become expensive. Re-run compose only when needed (stack down, env changed, or explicit restart request).

## Rules
- Always use Pixi tasks for tests.
- Do not run ad-hoc test commands that bypass wrappers unless explicitly debugging isolation internals.
- If scope is already in use, pick a different `FMRIF_RUNTIME_SCOPE`.

## Deep dive
For isolation internals and troubleshooting, see [`agent-guidance-isolation-validation.md`](agent-guidance-isolation-validation.md).
