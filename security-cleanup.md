# Security Cleanup Plan

## Objective

Keep current frontend behavior while removing security-sensitive HTML sink patterns
(`innerHTML`/related) from scheduler UI flows.

## Constraints

- No auth/session/security default weakening.
- Preserve current user-visible behavior in dialogs/editor/grid.
- Prefer minimal diffs and incremental validation per step.

## Execution Checklist

- [x] Step 1: Remove dialog/log HTML string rendering sinks
  - Refactor `logDialog` + log formatter pipeline to render DOM nodes, not HTML strings.
  - Replace dialog body resets with node-safe clearing (`replaceChildren`).

- [x] Step 2: Remove editor/result dialog HTML string rendering sinks
  - Refactor `fmt_editor_diffs` and `fmt_save_results` to produce DOM nodes.
  - Update `editor_dialog` and `result_dialog` to consume node content safely.

- [x] Step 3: Remove schedule grid `slots[i].innerHTML = markup`
  - Parse schedule cell payload through strict element allowlisting
    (`entry-cell` only) and append imported nodes.
  - Preserve progressive row loading behavior and error handling.

- [x] Step 4: Tighten anti-regression allowlist
  - Update `scripts/check-no-unsafe-html-sinks.sh` to remove now-obsolete
    JavaScript sink allowlist entries.

- [x] Step 5: Validate changes and update guidance
  - Run:
    - `pixi run pre-commit`
    - `pixi run test-routes -q`
    - `pixi run test-unit -q`
    - `pixi run test-integration-ci`
  - Update this plan with completion status and residual risks.

## Completion Status (2026-03-02)

- Completed all five cleanup steps.
- Validation runs passed:
  - `pixi run pre-commit`
  - `pixi run test-routes -q`
  - `pixi run test-unit -q`
  - `pixi run test-integration-ci`

## Residual Risks / Follow-ups

- The formatter refactors are primarily covered by integration behavior and lint/sink checks; there are no dedicated unit tests for the new client-side DOM-construction helpers.
- Strict schedule-cell allowlisting now rejects non-`entry-cell` top-level payloads and surfaces loader errors, which is intended; unexpected backend payload shape changes will fail closed.
