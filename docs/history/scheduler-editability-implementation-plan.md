# Scheduler Editability Implementation Plan

> Historical design or review notes. This records earlier work and may not
> describe the current application. Start with [the documentation index](../README.md).

Status: pre-implementation plan as of 2026-03-12.

This document turns the draft policy in
[`docs/scheduler-editability-policy.md`](../scheduler-editability-policy.md)
into an implementation plan for the current worktree.

## Goal

Implement a permission model and set of UI cues that make three things clear:

- whether the user can edit the booking
- whether the user can fulfill support on that slot
- whether template access is governed independently from slot editing

## Agreed Policy Baseline

The implementation should follow these rules:

- `templates` controls template access for a device.
- `slot` controls broad slot-editing power for a device.
- Booking editing includes support-request creation and removal.
- Support fulfillment is a separate capability from booking editing.
- A support-only user may fulfill an existing support request on a future
  unlocked slot even when they cannot edit the booking.
- Locked slots remain read-only for everyone.
- Past-slot support fulfillment remains limited to `edit_any` users.
- Admin and DEV PI inherit template access, slot editability, and support
  fulfillment through elevated device access.
- The grid and selected-slot controls must show the same cues.
- The support cue should be generic and use a helping-hand direction, meaning:
  "you can help here".

## Current Worktree Gaps

These are the main gaps between the agreed policy and the current worktree:

- Support assignment data is only loaded when `perms.edit` is true in
  [`scheduler/routes/entity_routes.py`](../../scheduler/routes/entity_routes.py).
- Support handler editing is currently gated by booking editability in
  [`scheduler/static/js/scheduler-editor/index.js`](../../scheduler/static/js/scheduler-editor/index.js).
- The support fieldset is disabled based on request editability rather than
  support-fulfillment capability in
  [`scheduler/static/js/scheduler-editor/index.js`](../../scheduler/static/js/scheduler-editor/index.js).
- The backend validation path still assumes support changes arrive through the
  same editing path as booking changes in
  [`scheduler/logic/schedule_editor.py`](../../scheduler/logic/schedule_editor.py).
- There is no dedicated support-action cue in the grid or selected-slot UI.

## Ade3 Baseline

`ade3` is useful as a baseline, but it should not be copied mechanically.

What `ade3` already had:

- Support-role users could reach an editable support subsection on future
  unlocked slots even when the parent booking was not editable in
  the old `ade3` `scheduler/static/script.js`.
- Slot editability itself followed the same core future/past/locked logic that
  the current worktree still uses in
  the old `ade3` `scheduler/static/script.js`.

What `ade3` did not do cleanly:

- Template access was still effectively tied to `slot`, not `templates`, in
  the old `ade3` `scheduler/logic.py`.
- Support datalists were still only loaded for `perms.edit` users in
  the old `ade3` `scheduler/app.py`.
- The support-role override in the client was broader than the policy now calls
  for, because it made the whole support subsection editable rather than
  limiting non-booking editors to fulfillment of existing requests.
- There was no dedicated support-action cue for the scheduler grid.

The intended direction is therefore:

- keep the old idea that support response can be independent from slot editing
- narrow it so only fulfillment, not request creation/removal, is available to
  support-only users
- complete the missing backend and data-loading pieces so the behavior works
  end to end
- add explicit visible cues so users can predict what they can act on

## Workstreams

### 1. Backend Capability Exposure

Update scheduler-page data loading so support-only users receive the data needed
to fulfill support requests.

Scope:

- Load support-request datalists whenever the user can fulfill at least one
  support kind on the device, not only when `perms.edit` is true.
- Keep booking-edit dataloaders for groups and group-member assignment scoped to
  booking editors.
- Ensure the frontend receives enough permission metadata to distinguish:
  - booking editing
  - support fulfillment by kind

Target files:

- [`scheduler/routes/entity_routes.py`](../../scheduler/routes/entity_routes.py)

### 2. Frontend Capability Model

Refactor the scheduler editor so booking editability and support fulfillment are
handled as separate capability checks.

Scope:

- Keep booking request toggles under booking editability.
- Add a separate fulfillment path for existing support requests on future
  unlocked slots.
- Leave locked slots fully read-only.
- Limit past-slot fulfillment override to `edit_any` users.
- Preserve admin and DEV PI behavior through their effective permissions rather
  than special frontend role checks.

Target files:

- [`scheduler/static/js/scheduler-editor/index.js`](../../scheduler/static/js/scheduler-editor/index.js)

### 3. Visible Cues

Add a generic support-action cue that is separate from the booking read-only
cue.

Scope:

- Keep the existing lock cue for booking read-only state.
- Add a helping-hand support cue when the slot contains at least one support
  request the current user can fulfill.
- Show both cues when both states are true.
- Mirror the same state in the selected-slot controls or inspector.
- Avoid per-kind grid icon variants; the grid cue stays generic.
- Add the helping-hand glyph to the icon set if there is no suitable existing
  icon.

Target files:

- [`scheduler/templates/macros.html`](../../scheduler/templates/macros.html)
- [`scheduler/templates/svg/icons.html`](../../scheduler/templates/svg/icons.html)
- [`scheduler/static/js/scheduler-editor/index.js`](../../scheduler/static/js/scheduler-editor/index.js)
- relevant scheduler CSS if spacing or layout adjustments are needed

### 4. Backend Mutation Validation

Bring server-side validation in line with the agreed policy so the server, not
only the UI, enforces the new support-fulfillment rules.

Scope:

- Allow support-handler changes by support-capable users on future unlocked
  slots even when they are not booking editors.
- Continue to reject support-request creation or removal from users who cannot
  edit the booking.
- Continue to reject all support changes on locked slots.
- Continue to restrict past-slot support fulfillment to `edit_any` users.
- Validate support handlers against the appropriate support staff lists.

Target files:

- [`scheduler/logic/schedule_editor.py`](../../scheduler/logic/schedule_editor.py)
- any route-level helpers that package permissions for scheduler saves

### 5. Test Coverage

Add capability-based tests instead of expanding the coarse role-only route
contract.

### Unit and route tests

- Keep [`tests/unit/route_contract.py`](../../tests/unit/route_contract.py)
  coarse and role-based.
- Add a dedicated, data-driven device-permission matrix test file.
- Cover actor scenarios:
  - admin
  - DEV PI
  - group writer
  - templates-only override
  - slot-only override
  - tech-only override
  - medical-only override
  - training-only override
  - read-only member
- Cover slot states:
  - future unlocked
  - past unlocked
  - locked
- Cover capability outcomes:
  - template access
  - booking editability
  - fulfill tech support
  - fulfill medical support
  - fulfill training support

### Integration tests

- Add or update Playwright coverage for:
  - lock cue on booking read-only slots
  - generic helping-hand cue on support-actionable slots
  - combined lock + support cue state
  - selected-slot UI parity with grid cues
  - support-only user being able to fulfill, but not create/remove, support
    requests

### 6. Documentation Follow-Through

After the implementation is stable:

- Update the draft policy note to remove draft-only language.
- Add a short policy summary or link from existing scheduler design docs if
  needed.
- Document the permission matrix test as the canonical place for device-specific
  capability semantics.

## Recommended Sequence

1. Adjust backend capability exposure for support-only users.
2. Refactor frontend support capability checks.
3. Update backend mutation validation to match.
4. Add the helping-hand cue and selection-state parity.
5. Add the permission-matrix tests.
6. Add or update Playwright cue coverage.
7. Run targeted tests, then `pixi run pre-commit`.

## Acceptance Criteria

The change is complete when all of the following are true:

- `templates` and `slot` remain independent.
- A support-only user can fulfill an existing support request on a future
  unlocked slot they cannot otherwise edit.
- That same support-only user cannot create or remove support requests on that
  slot.
- Locked slots remain fully read-only.
- Past-slot support fulfillment still requires `edit_any`.
- Admin and DEV PI continue to work through effective permissions.
- The grid shows a generic helping-hand cue for actionable support.
- The selected-slot UI reflects the same support-action state as the grid.
- Capability-based tests, not route-contract tables, cover the device-specific
  behavior.
