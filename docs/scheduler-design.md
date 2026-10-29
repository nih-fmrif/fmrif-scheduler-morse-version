# Scheduler Design

## Scope

This document describes the current design of:

- the device scheduler editor
- the template editor and template-application workflow
- the mock-auth strategy used by browser and route tests that exercise delegated scheduler behavior

It is intentionally implementation-oriented. If the code and this document drift, fix the document in the same change that updates the behavior.

## Device Scheduler Editor

### Grid model

- The device schedule is a sparse schedule, not a fully materialized dense table.
- Some visible cells correspond to real `ScheduleEntry` rows.
- Empty visible cells can still be edited. The client represents them with synthetic slot ids in the form `new-YYYY-MM-DD-HH`.
- The server normalizes those synthetic ids into real schedule rows during save and returns `id_map` so the client can remap placeholder ids to database ids.

### Why synthetic slots exist

- They let the UI edit empty cells without pre-creating schedule rows for every device/day/hour.
- They keep the database sparse.
- They let the client hold unsaved state for empty cells before a row exists.

Tradeoffs:

- Identity management becomes more complex on both client and server.
- Save failures can happen during normalization as well as during commit.

### Save flow

The device scheduler save path is:

1. The client builds one or more diffs.
2. The server normalizes synthetic ids into real schedule rows when needed.
3. The server validates the diffs against current schedule state and permission rules.
4. The server stages changes and support-request side effects.
5. The server commits the transaction.
6. The server returns:
   - `saved`
   - `notifications`
   - `id_map` for synthetic-slot remapping
   - per-slot errors when validation or database policy rejects the save

### Save batch semantics

The normal device scheduler UI is not a general spreadsheet-style multi-edit surface.

- The inspector modal can expand one edit across a contiguous duration, producing multiple diffs from one anchor slot.
- The server accepts multiple diffs because that duration-expansion flow is real product behavior.

The route contract is therefore:

- multiple diffs are valid for contiguous duration-driven updates
- the server should not assume arbitrary unrelated multi-cell edits are the main use case

### Client state invariants

The scheduler has several simultaneous views of the same draft state:

- the grid cells
- the inspector summary
- the inspector form controls
- the page-level `Review pending (N)` control

These surfaces must be treated as projections of one draft model, not independent UI state.

Operational invariants:

- closing the inspector must not discard unsaved slot or duration-expanded draft state
- duration expansion must mirror draft values into every targeted slot before save
- the grid, inspector pending summary, and review badge must agree on changed-slot counts
- invalid-slot counts and field-level validation details may differ, but they must do so intentionally:
  - the review badge reports invalid slots
  - the inspector error summary may report field-level validation errors across the targeted slots
- when duration mirroring is asynchronous relative to DOM updates, the inspector summary must refresh after mirrored target cells settle into their changed/invalid state

This is the main place where recent scheduler regressions clustered.

### Inspector editor contract

The inspector is not an isolated editor. It is a mounted view over the backing slot editor state.

That means:

- validation must be sourced from the underlying slot controls, even when the inspector renders cloned controls
- invalid group/member combinations must surface identically in the backing cell and the inspector
- stale validation from a previously valid draft must not survive a later group/member change
- support-request handler editability must be computed from canonical permission names, not local UI abbreviations

Current canonical support permission keys are:

- `tech`
- `medical`
- `training`

Any client-side aliasing such as `med` or `train` is presentation-only and must be mapped back onto those canonical keys before permission checks.

### Dialog action contract

The scheduler uses confirm/result dialogs in several flows:

- inspector save
- review pending submit
- template apply

These flows must bind submission to the affirmative action itself, not to generic dialog-hide events.

Design rule:

- `confirm` means "submit the action"
- `cancel` or close means "dismiss without submitting"
- dialog teardown events are not a reliable substitute for explicit user intent because different dialog implementations report different hide targets

Recent regressions showed that inferring confirmation from a hide event target is too fragile.

### Historical comparison and current direction

Compared with the older pre-inspector device scheduler:

- the old device page let the user accumulate changes across multiple unrelated cells and submit them with one page-level `save`
- the old device page showed a pre-submit summary dialog and, when relevant, let the user choose whether to send notifications
- the current device page is centered on one selected slot plus optional contiguous duration expansion

Current product direction:

- keep the current inspector-first editing model because it lowers cognitive load and raises issues in a narrower context
- restore support for discontinuous multi-slot editing through an explicit draft queue, not by returning to the old implicit page-wide edit surface
- restore pre-submit review as an explicit review/apply workflow
- restore notification choice as part of that review/apply workflow
- keep the device scheduler route multi-diff for now; the current UI now uses that contract explicitly for draft review and apply

Implemented device workflow:

1. The inspector remains the main place where a slot is edited.
2. Closing the inspector does not discard draft edits for that slot.
3. Draft edits can accumulate across discontinuous slots.
4. The page exposes an explicit `Review pending (N)` action that reflects pending and invalid counts.
5. That review surface shows a slot-by-slot diff summary before submit.
6. That review surface includes the `send notifications` toggle.
7. The user can either:
   - review and apply the currently selected slot or duration-expanded set from the inspector, or
   - review and apply the full pending draft set from the page-level review surface

Implementation notes:

- this did not require a large route redesign because the device save route already accepts `diffs[]`
- synthetic-slot normalization and `id_map` remapping already support mixed saved/unsaved empty-slot edits
- most of the work is client-side state and UX around explicit draft management

### Scheduler navigation and summary chrome

Current direction:

- merge the jump navigation and slot-summary card into one scheduler control card
- keep that merged card sticky above the floating grid header so date navigation and slot actions remain available during vertical scroll
- keep the responsive column-count behavior and remove the explicit `days` control from the jump UI
- remove the old schedule caption treatment from the jump UI, including the horizontal divide and the schedule text/icon block
- keep only the three slot actions from the summary card:
  - `View` or `View/Edit` depending on permissions
  - `Review pending (N)`
  - `Legend`
- collapse previous/next non-empty into compact rewind/fast-forward arrow buttons with hover text that explains the action
- keep previous/next non-empty navigation in-place without URL mutation, reload, or scroll jumps

This keeps the primary scheduler controls in one place and reduces duplicated sticky chrome above the grid.

Future contract tightening:

- now that the draft queue exists, the device route can later be narrowed to the explicit client-supported batch shapes if that proves useful
- if the draft queue is not implemented, tightening the route would prematurely remove a real user need for discontinuous edits

## Save Error Policy

### Explicit mapping policy

Scheduler save failures follow an explicit mapping policy:

- known constraint failures map to stable, user-actionable messages
- unknown database failures fall back to bounded detail instead of raw unbounded diagnostics
- unmapped paths are logged for admin follow-up

This is deliberately more open than a pure opaque-code model, but it avoids dumping full driver diagnostics directly to the client.

### Attribution model

Late transaction failures do not always identify the exact client diff that caused the problem.

The current mitigation is server-side attribution metadata:

- each normalized diff gets an internal server reference
- the server records slot date/hour and changed group/member/institute values for that reference
- if commit fails, the server tries to map the database diagnostic back to the most likely client ids

Attribution is best-effort, not perfect:

- slot/date/hour matches are strong
- foreign-key value matches are useful
- changed-field heuristics are weaker
- opaque failures still fall back to all candidate diffs in the save batch

### Client handling contract for save failures

The client must preserve actionable draft state when a save batch is only partially successful or is rejected.

Required behavior:

- mixed success/failure batches keep failed slots pending
- successful slots are reconciled immediately
- pure overwrite conflicts rebase the client baseline onto the server-reported expected state while preserving the user's current draft
- retry from the same draft must remain possible without a full page refresh

Error payload handling rules:

- object-shaped `errors` payloads are treated as per-slot failure maps
- array-shaped error payloads are treated as general save failures, not slot maps
- the result dialog must surface real backend messages rather than inventing fake slot references such as `entry 0`

Notification result handling:

- result dialogs should report stream-specific notification outcomes
- missing recipient addresses are data issues and should be surfaced as such
- successful notification sends should be reported separately from schedule-save success so operators can distinguish commit success from follow-on messaging success

This policy matters because scheduler saves can fail after synthetic-slot normalization, during validation, or late in commit/notification-adjacent work.

## Row Hydration And Lateral Scrolling

### Row hydration

- Scheduler rows can be hydrated lazily as the user interacts with the grid.
- Empty cells render stub entry markup instead of disappearing entirely, so editing and error display stay structurally stable.

### Lateral scrolling placeholders

- Lateral scrolling uses preview placeholders to keep the grid responsive while content is being loaded.
- Placeholder skeletons are now delayed until lateral preview displacement reaches half a visible day-column width.
- Before that threshold, the currently rendered cells remain in place.

This avoids premature flicker on small horizontal movements while still allowing responsive preview behavior during real sideways navigation.

### Header and status copy

- remove transient load-progress copy such as `all 24 rows ready` from the visible scheduler UI
- keep the day-column header format centered on weekday plus month/day
- include the year only once, on the first visible column header at the left edge, so the header still communicates the range metadata without repeating it in every column

### Compact row behavior

- the older device page hid unused off-hour rows behind an expando control
- the current device page renders the full day grid and does not surface that compact-row control in the template

Current direction:

- keep the current fixed grid geometry as the default behavior
- do not reintroduce row-count changes as the first iteration, because that previously complicated scrolling and grid behavior
- use background banding and gradient cues to distinguish off-hours while preserving the stable 24-row layout
- only consider a future compact mode if it can preserve the logical full-grid navigation and scrolling model

This deliberately favors interaction stability over aggressive row hiding.

## Template Workflows

Templates are separate from day-view schedule editing.

### What templates are

- A template is a reusable weekly schedule for one device.
- Creating a template seeds a full `7 x 24` weekly grid, either blank or cloned from another template.
- Applying templates copies one or more template weeks into future real schedule dates for the device.

### Why template editing accepts broad multi-diff saves

- Template editing is a weekly-grid authoring workflow.
- The user may edit many cells across the week before saving.
- That editor therefore supports collecting many changed cells and sending them as one save batch.

This is different from the device day-view inspector workflow, where multi-diff saves mainly come from duration expansion.

### Template-apply confirmation contract

Template application follows the same dialog rule as scheduler review/apply:

- pressing the explicit confirm action must submit
- closing the dialog must not submit

This sounds trivial, but it is important enough to state because the same failure mode previously affected both template apply and review-pending submission.

## Mock Auth For Scheduler And RBAC Tests

### Current contract

- `POST /auth/test/session` is test-only.
- `session_key` is required for mock session creation.
- The resolved mock username and email are scoped by that `session_key`.
- This prevents parallel tests from sharing the same mock user rows.

### Group PI behavior in tests

For non-`DEV` PI cases:

- tests prefer distinct scoped groups where practical

For `DEV` PI cases:

- the app has explicit `DEV` authorization branches
- replacing `DEV` with a fake group would not exercise the real code path
- scoped mock sessions therefore keep real `DEV` membership while storing PI authority in session-local test state

This is a test-only mechanism used to preserve real `DEV` semantics under parallel execution.

### Limitations

- This isolates mock-auth/profile state, not every kind of mutable application data.
- If two parallel tests edit the same schedule rows, they can still conflict.
- The session-local PI overlay is test scaffolding and should not leak into non-test auth design.

## Design Boundaries

The current design intentionally keeps these distinctions:

- real authorization remains database-backed in production code paths
- test-only auth may use scoped session overlays to avoid parallel test collisions
- template editing is a broad weekly-grid save surface
- device schedule editing is primarily an anchor-slot plus duration-expansion workflow

If those boundaries change, update this document and the related operational docs in `docs/testing-strategy.md` and `docs/RBAC.md`.
