# Phase D Progress

Last updated: 2026-03-05

## Scope
- Phase D: Schedule Header/Inspector/Modal Contract

## Work tracker
- [x] Create tracking doc (`phase-d-progress.md`)
- [x] Enforce exact default inspector prompt (`Select a time slot`) with no extra inline helper text before selection
- [x] Keep single-slot details hidden until a slot is selected; preserve `View` and `Legend` action visibility
- [x] Fix selected-slot count drift caused by background row hydration
- [x] Surface pre-existing slot errors from loaded data when server payload provides per-slot errors
- [x] Keep irreconcilable save-failure lock state synced into inspector action label/mode immediately
- [x] Improve irreconcilable error messaging fallback for unsupported server error types
- [x] Validate behavior with headed Playwright walkthrough
- [x] Capture Phase D design conflicts/risks after validation

## Notes
- Tests are intentionally not used for acceptance in this pass per request.
- Headed Playwright validation covered:
  - default inspector text is exactly `Select a time slot` before slot selection
  - `View` and `Legend` remain visible before selection
  - selecting a slot updates inspector details in place
  - `Selection Details` modal opens from `View` and closes with `Esc`
  - `Enter` on selected slot opens the same modal flow
  - selecting slots did not move horizontal viewport in the verified path
- Remaining live-data limitation:
  - available seeded device windows in this scope had no rendered `entry-cell` entries, so editable-slot paths (`View/Edit`, save guards, irreconcilable server-lock flow with real entry payloads) could not be exercised end-to-end via UI.

## Potential design conflicts to resolve
- Auto-selection behavior is ambiguous: Phase D expects a strict pre-selection state, but grid hydration/keyboard defaults can easily re-introduce implicit selection unless kept explicitly user-driven.
- Error-source contract is not strongly typed across backend/frontend payloads (`errors`, `serverErrors`, field-level validation); this should be standardized to one schema to avoid display drift.
- If seeded/local environments often have empty windows, acceptance of Phase D edit behavior becomes difficult to validate; a deterministic fixture route/date with at least one editable and one locked/error slot would reduce ambiguity.

## Follow-up updates (2026-03-05)
- [x] Aligned `ui-overhaul-tasks.md` terminology with canonical schema wording (removed migration framing).
- [x] Compared current scheduler implementation against older iteration in `~/.codex/worktrees/ade3/fmrif-scheduler-morse-version`.
- [x] Documented concrete missing/regressed functionality for product review.
- [x] Updated `design-spec.md` with agreed direction:
  - no off-hour expando UX
  - editable empty-slot windows (no blocking/no-editor empty-state mode)
  - modal-only save/apply path for device scheduler
  - anchor-based multi-slot duration expansion (`+1 hour` and longer) with atomic apply semantics
- [x] Finalized duration/conflict details in spec/tasks:
  - both preset increments and end-time controls
  - no duration cap
  - conflict reporting with retryable modal state (no lock-based conflict handling)
