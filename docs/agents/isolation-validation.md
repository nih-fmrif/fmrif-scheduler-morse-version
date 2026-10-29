# Agent Guidance: Isolation Validation

This document is for agents (or humans debugging agent collisions).

## Isolation model (short)
- `FMRIF_RUNTIME_SCOPE` selects an isolated runtime block.
- `run-compose.sh` maps that scope to:
  - compose project name
  - Postgres host port
  - app port
  - Mailpit app/unit/routes/integration ports
- `scripts/run-isolated-test-suite.sh` derives suite-scoped DB/runtime settings from that scope.
- Same-suite + same-scope concurrency is blocked by an advisory lock.

## What can still collide
- Same scope reused concurrently.
- Manually bypassing wrappers.
- Host processes already bound to required scoped ports.
- Shared artifacts outside DB/ports (for example coverage files) unless explicitly scoped.

## Periodic validation runbook
Use this periodically to verify isolation still holds.

1. Start two scope-isolated stacks in parallel.

```bash
FMRIF_RUNTIME_SCOPE=sim-a-<ts> bash run-compose.sh --no-app
FMRIF_RUNTIME_SCOPE=sim-b-<ts> bash run-compose.sh --no-app
```

2. Verify both compose projects exist and ports differ.

```bash
docker ps --format 'table {{.Names}}\t{{.Ports}}' | rg 'sim-a|sim-b'
```

3. Confirm same-scope startup fails fast.

```bash
FMRIF_RUNTIME_SCOPE=sim-a-<ts> bash run-compose.sh --no-app
```

Expected: runtime scope already in use.

4. Confirm same-suite same-scope lock fails fast.
- Hold one suite run in scope A.
- Start the same suite again in scope A.

Expected: suite lock already held.

5. Confirm cross-scope parallel suite runs succeed.

```bash
FMRIF_RUNTIME_SCOPE=sim-a-<ts> pixi run test-unit -q
FMRIF_RUNTIME_SCOPE=sim-b-<ts> pixi run test-unit -q
```

Expected: both pass; no DB/Mailpit collisions.

6. Confirm integration wrapper isolation values differ across scopes.

```bash
FMRIF_RUNTIME_SCOPE=sim-a-<ts> bash scripts/run-isolated-test-suite.sh integration bash -lc 'echo A'
FMRIF_RUNTIME_SCOPE=sim-b-<ts> bash scripts/run-isolated-test-suite.sh integration bash -lc 'echo B'
```

Expected: different `PGDATABASE`, `APP_PORT`, Mailpit ports.

7. Cleanup: stop both compose runs.

## PTY/persistent-command caveat (important in agent tooling)
When validating concurrent stacks from an agent runtime, background commands launched from a non-interactive shell (`nohup ... &`) may be reaped when the parent command exits.

Practical guidance:
- Prefer persistent PTY sessions for long-running `run-compose.sh --no-app` commands.
- Poll those sessions until services are up.
- Use separate sessions per simulated agent.
- Send Ctrl+C to each session for cleanup.

This avoids false negatives where a stack appears to "start" but exits immediately due to session lifecycle.

## Known unexpected collision that was fixed
Parallel scoped test runs can still clash on shared tooling artifacts if not explicitly scoped.
- Example fixed: parallel `pytest-cov` runs colliding on a shared `.coverage` file.
- Mitigation: wrapper now sets scope+suite-specific `COVERAGE_FILE` by default.
