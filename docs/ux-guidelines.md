# UX Guidelines (Responsive-First)

These guardrails are intentionally short so they stay practical in daily PRs.

## Scope

- Prioritize responsive behavior across viewport and window size changes.
- Mobile support is important, but baseline quality at wider desktop widths is equally important.
- Apply these rules to new UI work and to touched surfaces during maintenance.

## Viewport Targets

Design and verify at these breakpoints:

- Small: `<= 48em` (mobile and narrow windows)
- Medium: `> 48em` and `<= 80em` (tablet and common laptop)
- Wide: `> 80em` (large desktop/external monitor)

At each breakpoint, confirm:

- no horizontal overflow
- one clear primary action per panel
- filters remain scannable and logically grouped

## Layout Guardrails

- Keep primary content constrained (`--layout-max-width`) so wide screens do not become sparse or hard to scan.
- Use full-bleed layout only for dense editor/table surfaces that need horizontal space.
- Center single-column forms and filter groups with a tighter max width (`--layout-form-max-width`).
- Use responsive grids (`repeat(..., minmax(...))`) instead of fixed rows for control bars.

## Form And Filter Rules

- Keep labels visible and adjacent to their controls.
- Group related toggles/checklists in one logical block (prefer `fieldset` + `legend`).
- Keep search as a distinct row with paired “search text” and “search field” controls.
- Avoid stretched controls that exceed readable line length at wide widths.

## Content And States

- Empty states should include one clear next action.
- Preserve visual hierarchy with consistent section spacing and heading order.

## Stateful Editor Rules

- If one draft is visible in multiple surfaces, those surfaces must derive from one source of truth.
- Counts shown in badges, summaries, and inspectors must update together or with a deliberate documented difference.
- Mirror hidden/backing validation into visible cloned controls; do not let the visible editor appear valid when the real field is invalid.
- Preserve unsaved draft state across view transitions unless the user explicitly discards it.

For scheduler-style editors, treat these as required behavior:

- pending-count chrome and in-editor pending summaries must agree
- invalid-slot counts and field-error counts must use distinct labels if they measure different things
- batch result dialogs must distinguish:
  - save success
  - partial save failure
  - notification success/failure
  - data issues such as missing recipients

## Dialog Rules

- Confirmation dialogs must submit from the explicit confirm action, not from generic hide/close events.
- Cancel and close actions must be side-effect free.
- Result dialogs should preserve enough context for the user to retry or understand what needs correction.

## PR Checklist

- Verified at small, medium, and wide viewport sizes.
- No horizontal overflow on updated pages.
- Updated forms/filters are grouped and scannable.
- Primary action is obvious in each changed panel.
- Empty-state messaging still communicates the next action.
- Multi-surface draft state stays in sync when the changed UI includes an editor, badge, dialog, or review surface.
