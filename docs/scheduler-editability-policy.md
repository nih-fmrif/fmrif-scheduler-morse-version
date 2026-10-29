# Scheduler Editability Policy (Draft)

This note captures the current intended policy for scheduler editability,
template access, support-request workflows, and the visible cues that go with
them.

Status: draft policy for discussion as of 2026-03-12.

## Purpose

This policy separates two different ideas that were previously conflated:

- booking editability
- support-request fulfillment

The goal is to let users understand:

- whether they can edit the booking itself
- whether they can fulfill support that has already been requested

## Capability Terms

### `can_edit_booking`

The user may edit the slot booking itself. This includes:

- group
- member
- institute
- other booking fields carried by the slot editor

### `can_fulfill_support(kind)`

The user may fulfill an existing support request of a given kind by assigning or
updating the handler. Kinds are:

- `tech`
- `medical`
- `training`

This is separate from booking editing.

## Permission Model

### Templates

- `templates` grants template editing and applying for the device.
- `slot` grants broad slot-editing power on that device.
- `slot` does not imply template access.
- admin and DEV PI inherit template capability through elevated device access.

### Booking

- unlocked future slots follow the existing slot edit rules
- locked slots are never booking-editable
- past slots are only booking-editable for `edit_any` users

Booking editability includes support-request creation/removal. If a user can edit
the booking, they can:

- toggle support requested on/off
- change the technologist support subtype (`cover` vs `support`)

In the current codebase, `edit_any` includes:

- admin
- DEV PI
- users with the device-level `slot` permission

### Support fulfillment

`tech`, `medical`, and `training` are response permissions, not booking-edit
permissions.

That means a user may be unable to edit the slot booking and still be allowed to
fulfill an existing support request on that slot.

admin and DEV PI inherit all three support-response permissions through the
current `DevicePerms` model.

## Policy Rules

### Rule 1: Template access

- Template pages and template mutations are controlled by the `templates`
  device permission.
- `slot` access alone is not enough.

### Rule 2: Booking editability

- `can_edit_booking` follows slot-edit rules.
- Locked slots are read-only for booking edits.
- Past slots are read-only for non-`edit_any` users.

### Rule 3: Fulfilling support

`can_fulfill_support(kind)` is true only when all of the following are true:

- the slot is not locked
- a support request of `kind` already exists on the slot
- the user has the matching effective support permission for `kind`

Additional past-slot rule:

- for past slots, only `edit_any` users may fulfill support

Support fulfillment allows only support-handling actions. It does not allow:

- editing the booking itself
- creating a new support request
- removing an existing support request

### Rule 4: Support-only users

A support-only user may fulfill an existing support request on a future unlocked
slot even when they cannot otherwise edit the slot booking.

This is intentional. Support response is independent from booking editability.

## User-Facing Cues

Booking read-only and support fulfillability are orthogonal and should be shown
as separate cues.

### Read-only cue

- A lock cue indicates that the slot is not booking-editable in the current
  view.

### Support-fulfillment cue

- A distinct support cue indicates that the slot contains at least one support
  request the current user can fulfill.
- This cue should appear even if the slot is not otherwise booking-editable.
- The cue is generic. It means "you can help here" rather than naming the
  support kind in the grid cell itself.

### Combined state

If both of these are true:

- the slot is read-only for booking edits
- the current user can fulfill support on it

then both cues should be visible.

### Icon semantics

The support cue must mean:

- support has been requested
- you can take action on that request

It must not read only as:

- people are needed
- this slot has support metadata

The selected direction is a helping-hand icon.

The icon should read as:

- help is needed here
- you can take action on it

The grid cue should stay generic. Users can inspect the selected slot for the
exact support type and available action.

### Selection/inspector parity

The selected-slot controls must reflect the same state as the grid cell:

- read-only booking cue
- support-fulfillment cue

## Current Worktree Status

### Aligned with this policy

- template access is controlled by the `templates` permission
- booking read-only state is surfaced with a lock cue

### Not yet aligned with this policy

- support fulfillment is still tied too closely to booking-edit mode in the
  current scheduler editor logic
- there is not yet a distinct user-facing support-fulfillment cue

## Validation Direction

Route-contract tests should remain coarse and role-based.

Device-specific permission behavior should be validated through a dedicated,
data-driven permission matrix.

### Suggested actor scenarios

- admin
- DEV PI
- group writer
- templates-only override
- slot-only override
- tech-only override
- medical-only override
- training-only override
- read-only member

### Suggested slot states

- future unlocked
- past unlocked
- locked

### Suggested capability columns

- template access
- edit booking
- fulfill technologist support
- fulfill medical support
- fulfill training support

This matrix should test capability semantics directly, rather than trying to
encode all device-permission overrides into the role-only route contract.

## Implementation Note: "Roster"

In this context, "roster" means the list of valid people who can be assigned for
that support kind on that device in the current view.

This is an implementation detail, not a separate policy capability. In practice,
if a request is actionable in the UI, the UI must have at least one valid
assignable option for that support kind.

## Open Questions

- Should the grid show one combined support-action cue or multiple per-kind
  cues when more than one support request is fulfillable?
