# Agent guidance: Playwright

Use the Playwright path that matches the job. In this repo the main failure mode is choosing the wrong tool for the phase of work: exploratory debugging, scripted reproduction, and regression validation are different jobs.

## Prerequisites
- `export FMRIF_RUNTIME_SCOPE=<unique-scope>`
- `bash setup-dotenv.sh`
- `bash run-compose.sh --no-app` for the first setup in a new scope
- `bash run-compose.sh --no-app --resume` only when you are reusing the same healthy scope and actually need a compose refresh

## Tool choice by context

### 1. MCP browser: preferred for interactive debugging
Use MCP first when you need to:
- reproduce a UI bug interactively
- inspect DOM state, console output, dialogs, and network requests
- step through a complex scheduler flow quickly

Why this is preferred here:
- the live scoped stack is usually already running
- the scheduler flows are stateful and easier to inspect live than to encode immediately as a spec
- MCP gives the fastest loop for reproducing, observing, and narrowing the bug

This is a repo-specific preference for interactive debugging. It is not a general claim that MCP is always better than terminal Playwright.

Rules:
- start with one browser session and one tab
- if MCP launches into an old session or Chrome reports `Opening in existing browser session.`, reset it immediately:
  - `bash scripts/reset-mcp-browser.sh`
- retry MCP once after the reset
- if the lock returns, or you need parallel browser work, stop fighting MCP and switch to the repo Playwright path below

## 2. Headless Playwright test path: preferred for regression validation
Use this when you need:
- a repeatable reproduction after the bug is understood
- a narrow regression check
- CI-friendly validation

Default command:
- `pixi run test-integration-ci`

Useful narrowed examples:
- `pixi run test-integration-ci tests/playwright/integration/device-ui-editing.spec.ts --grep 'multi-slot'`
- `pixi run test-integration-ci tests/playwright/integration/device-subroutes.spec.ts --grep 'template' --project=chromium`

Notes:
- prefer a targeted spec plus `--grep` over the full suite
- use this path for verification and regression coverage, not as the first tool while you are still discovering the bug

## 3. Headed Playwright: only when the visual layer matters
Use `pixi run test-integration-headed` when headless is hiding the problem, especially for:
- layout or positioning issues
- focus and keyboard behavior
- hover, drag/drop, or animation timing
- modal layering or visual confirmation problems

Headless remains the default. Switch to headed deliberately.

## 4. Terminal Playwright automation: useful fallback and good default in many non-interactive agent workflows
Use terminal Playwright or a small one-off script when:
- MCP still fails after one reset
- you need a scripted ad hoc run without adding a spec yet
- you want quick headless automation from the shell
- the task is terminal-driven rather than interactive debugging

For many general agent workflows, CLI-based Playwright remains the better default. The repo-specific guidance here is only that MCP is usually the fastest first choice for interactive scheduler debugging when healthy.

If the flow matters long term, turn it into a regression spec under `tests/playwright/integration/`.

## Auth by workflow

### MCP browser on the local scoped app
Default assumption:
- you are dealing with normal app auth unless you have explicitly enabled test auth for that app process

Use MCP auth this way:
- if you already have an authenticated app shell, reuse it
- if you need normal real login behavior, go through `/auth/login`
- if you need deterministic admin or role switching for debugging, prefer the integration test path instead of hand-driving real login

Important:
- do not assume `/auth/test/session` is always available in a manually started app
- `/auth/test/session` is the mock-auth mechanism used by the Playwright integration harness when `PLAYWRIGHT_AUTH_MODE=mock` and `AUTH_TEST__ENABLED=true`
- if you choose to use mock auth manually, copy the contract from `tests/playwright/support/auth-session.ts` instead of inventing your own payload

Practical rule:
- for scheduler bug hunting where role control matters more than login UX, use MCP for interaction only when auth is already settled or trivial
- otherwise use the integration Playwright path first, because it establishes the right role deterministically

### Integration Playwright specs: mock auth by default
This is the default path for browser tests under `tests/playwright/integration/`.

Auth contract:
- `PLAYWRIGHT_AUTH_MODE=mock`
- `AUTH_TEST__ENABLED=true`
- auth session is created through `POST /auth/test/session`
- `AUTH_TEST__SHARED_SECRET` must be set
- `session_key` is required and isolates mock users across parallel workers

Role selection:
- authenticated integration tests use `tests/playwright/support/auth-fixture.ts`
- `authProfile` defaults to `admin`
- override explicitly when needed, for example `test.use({ authProfile: 'member' })`

Practical rule:
- if you need to log in as admin for scheduler or RBAC debugging, this path is usually the fastest and most deterministic
- do not spend time hand-solving admin auth in the browser when the integration fixture already does it

### Auth-flow Playwright specs: real Entra only
Use `tests/playwright/auth-flow/` only when you are testing real authentication behavior.

This path is for:
- real Entra login behavior
- NIH VPN or staging-capable environments
- storage-state generation and reuse

Commands:
- `pixi run test-auth-flow-credentials`
- `pixi run test-auth-flow-storage-state`
- `pixi run generate-auth-storage-state`

Rules:
- `PLAYWRIGHT_AUTH_MODE=entra`
- use credentials or `PLAYWRIGHT_STORAGE_STATE`
- non-admin profile switching is not supported in real-auth mode
- do not use this path for normal scheduler UX debugging unless the bug depends on real auth

### Live-incident Playwright specs
Use `tests/playwright/live-incident/` only for behaviors that cannot be reproduced locally or with stable fixtures.

Do not default to this path for scheduler work.

## MCP recovery
If the MCP browser fails with Chrome opening an existing session, free the shared MCP Chrome profile before retrying:

```bash
bash scripts/reset-mcp-browser.sh
```

The script only kills Chrome processes using `~/Library/Caches/ms-playwright/mcp-chrome`.
Run it once, retry MCP once, then fall back to another Playwright path if the problem returns.

## Available repo commands
- `pixi run install-js`
- `pixi run install-playwright`
- `pixi run test-integration`
- `pixi run test-integration-headed`
- `pixi run test-integration-ci`
- `pixi run test-auth-flow-credentials`
- `pixi run test-auth-flow-storage-state`
- `pixi run generate-auth-storage-state`
- `pixi run test-live-incident`

## Recommended debugging sequence for this repo
1. Bring up or reuse the scoped stack.
2. Decide whether the job is interactive debugging, deterministic reproduction, or regression validation.
3. For interactive scheduler debugging, try MCP first.
4. If MCP is stale, run `bash scripts/reset-mcp-browser.sh` and retry once.
5. If the issue requires deterministic admin auth or role switching, switch to the integration Playwright path instead of hand-solving login.
6. If MCP is still unhealthy, switch to terminal Playwright or a narrow test run instead of spending more time on session recovery.
7. Once the bug is understood, validate it with the narrowest relevant Playwright spec.
8. Add or update a regression test when the fix closes a meaningful coverage gap.

## Avoid
- using the full browser suite for initial exploration
- keeping multiple stale MCP sessions around
- defaulting to headed runs when headless would do
- using real Entra auth for normal local scheduler debugging
- assuming mock-auth endpoints are available outside the harness
- adding wide browser tests when a narrow spec or route test is enough

## Fast failure triage for terminal Playwright
- If terminal Playwright fails with `Cannot find module '@playwright/test'`, install JS dependencies first: `pixi run install-js`
- If terminal Playwright fails because Chromium/browser binaries are missing, install browsers with: `pixi run install-playwright`
- If you only need Chromium, use: `pixi run install-browsers`
