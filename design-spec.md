# Webapp Design Specification

## 1. Purpose
Define the target UX and interaction behavior for the scheduler webapp, with emphasis on responsive behavior, schedule navigation, slot interaction, and admin/RBAC layout updates.

## 2. Source of Truth and Precedence
1. `ui-fixes.md` (highest priority)
2. This specification (`design-spec.md`)
3. Existing interface behavior and implementation notes

If an existing behavior conflicts with `ui-fixes.md`, implement the `ui-fixes.md` behavior.

## 3. Scope
In scope:
- Top navigation bar
- Homepage groups/devices list and filtering
- Device Schedule page
- RBAC page
- Admin Panel page

Out of scope:
- Auth/session model changes
- Scheduling rules/recurrence logic redesign
- Data model migrations unrelated to UI behavior

## 3.1 Current Schedule-Track Status (as of 2026-03-06)
- Phase D (`Schedule Header/Inspector/Modal Contract`): resolved for the current implementation scope.
- Phase E (`Lateral Navigation Engine Refactor`): resolved for the current implementation scope.
- Phase F (`Responsive Schedule Layout and Scroll Ownership`): resolved for the current implementation scope.

## 4. Roles and Permission Assumptions
- Read-only user: may inspect schedule data but cannot edit slots.
- Editor user: may inspect and edit slots in allowed devices/groups.
- Admin user (`admin` membership): may access RBAC/admin surfaces and audit tools.
- Admin-only capabilities:
  - create groups and devices
  - access/edit inactive-entity admin views
  - toggle active/inactive state on groups/devices
  - access RBAC/email audit feeds
- `PI` means a user designated as PI for a specific group.
- Each group has a single PI at a time (including `DEV`).
- `Group PI` means PI of a non-`DEV` group.
- `DEV PI` means PI of the `DEV` group (`Group PI of DEV` is the same role).
- Delegated PI/non-admin approvers may access RBAC using the RBAC model split:
  - Group PI of non-`DEV` group: managed-group scope only.
  - DEV PI: usual Group PI management access for `DEV`, plus management over all active devices (broad active-device scope; not limited by device-group links).
- DEV PI is not admin.
- Admin-only capabilities are granted only by `admin` membership and do not come from DEV PI status.
- Therefore DEV PI does not include group/device creation, active/inactive toggles, inactive-entity admin views, or RBAC/email audit feeds unless the user is also an admin.
- Delegated PI/non-admin approvers must not receive RBAC/email audit feed access and must not be shown audit tabs/panels.
- A DEV member who is not Group PI of `DEV` does not get delegated PI RBAC management capability.
- PI of another group does not imply DEV PI status.
- DEV group membership (approved, active) is normal group membership status and may enable DEV-member workflows (for example technologist workflow eligibility and DEV-user assignment flows).
- DEV group membership alone does not grant DEV PI privileges, admin privileges, or global active-device management capability.
- In general app UI, this role should be presented as Group PI of `DEV`; additional active-device management capability is behavior-level, not a separate user-facing role label.

Permission state must drive visible affordances and button labels.

## 5. Global UX Rules
- Interactions that change visible schedule range must not trigger full-page reload.
- Scroll, slot selection, and previous/next navigation must not cause page jump.
- URL query state (`start`, `days`) should remain reload/share safe and may be synchronized in place with visible window state.
- Lateral schedule movement (wheel/trackpad horizontal, left/right arrows, previous/next non-empty) must not create new browser history entries per micro-shift.
- Grid interaction must not trigger browser back/forward page navigation gestures while pointer/focus is within the schedule grid; outside-grid behavior must remain browser/app default.
- Transient interaction state (lateral scroll offset, snap state, selected slot, pending row hydration) remains in memory and must not be serialized into URL on every scroll.
- Keyboard and pointer interaction parity is required for primary controls.
- Narrow-display behavior must avoid horizontal page overflow.

## 6. Top Navigation Bar
### 6.1 Responsiveness
- Navigation must follow this exact responsive sequence with no abrupt lateral jump of button 4:
  1. Expanded state: labels visible, with a larger center gap between button 3 and button 4.
  2. Center-gap compression: while labels remain visible, the center gap shrinks substantially toward the left-group gap size, with button 4 still right-anchored.
  3. Icon-only right-anchor state: controls collapse to icon-only, button 4 stays right-anchored, and the center gap grows to absorb available space.
  4. Final icon compression: as width continues to shrink, the center gap compresses again until icon gaps are effectively equal and side spacing becomes symmetric.
- Button 4 must never cross to the left side of the first three controls in any state transition.
- Before icon-only mode (states 1-2), extra right-edge whitespace beyond normal container padding must not exist.
- Transition from labeled to icon-only state must occur only after center-gap compression has progressed far enough to exhaust comfortable labeled layout.
- No-wrap behavior is required; use an enforced minimum nav rail width in the tightest icon state rather than allowing controls to stack.

### 6.2 Homepage button icon
- Homepage button uses a minimalist black-and-white human MRI scanner icon.
- Icon should be created in-repo by engineering (inline SVG or vendored local asset).
- Runtime hotlinking to third-party icon URLs is not allowed under current CSP (`img-src 'self' data:`).
- Icon must remain recognizable at compact sizes.
- Icon-only variant must include accessible name (for example: `aria-label="Home"`).

## 7. Homepage
### 7.1 Search filter behavior
- Add groups and devices search filters that match RBAC filter interaction:
  - 200 ms debounced input
  - filtering starts at 1 character
  - matches on item name only

### 7.2 List truncation and expansion
- Default visible list size for groups/devices is 5 items.
- If list length is greater than 5, show a `Show more` control.
- Each `Show more` activation appends 10 additional items in-place without navigation.
- On each filter-input change:
  - visible-item count resets immediately to the default (5)
  - `Show more` control hides immediately during filter refresh
  - after a fixed 2 second delay, `Show more` reappears only if filtered results still exceed the current visible-item count

## 8. Device Schedule Page

### 8.1 Header copy
- Remove the dynamic summary text like `schedule for <scanner> from <start> to <end>`.

### 8.2 Date window defaults and anchoring
- Default schedule window is 7 days and Monday-first when there is enough horizontal space and no prior navigation state.
- On narrow displays, visible day count may shrink (down to one day) to preserve no-horizontal-overflow layout.
- When only one day is visible due to width constraints, default anchor should be current date rather than forcing Monday.
- Visible day count must be computed from current rendered width and applied as an integer column count.
- Fractional/partial day columns are non-compliant; only full columns may be rendered in the active viewport.

### 8.3 Column and label sizing
- Define column widths so the page itself does not require horizontal scrollbar at any supported viewport width.
- Compute maximum day-column width automatically from available viewport width and fixed non-day layout chrome.
- If a day-column width control exists, clamp user-selectable maximum width to this computed maximum.
- Recompute the maximum on resize/orientation changes and clamp active selection if it exceeds the new maximum.
- Use the computed width + viewport to derive full-column fit and render only that integer count; do not render half columns.
- Scheduler adjacent-day navigation must not rely on a horizontal scrollbar.
- Timeslot labels must use a fixed width to stabilize row alignment across days.

### 8.3.1 Row visibility density
- The schedule model remains a full 24-hour day (`00:00` through `23:00`) and all rows must remain reachable through normal page scroll.
- `empty row` means a timeslot row where every visible-day cell is open/unassigned, has no support requests, has no pending edits, and has no errors.
- Empty rows remain visible; no collapse/expand control is used.
- Empty slots use a faded visual treatment so non-empty rows remain easier to scan.
- Row-density behavior must not introduce a grid-owned vertical scrollbar; page-owned vertical scroll remains the only vertical scroll path.

### 8.4 Horizontal navigation model
- Horizontal wheel/trackpad movement over the schedule is continuous during gesture input and snaps to a day boundary on release.
- For input streams without explicit release events, treat 120 ms of horizontal-input idle time as release and then snap.
- Columns entering from one side displace/hide columns on the opposite side.
- Left/right arrow controls move one day per activation.
- Left/right movement must work regardless of whether current/adjacent cells are empty.
- Previous/next non-empty navigation must update dates in place with visual pressed/active feedback.
- Wheel/trackpad lateral scanning must not wait for full cell hydration before showing movement:
  - update visible day headers as a continuous lateral slide (header-rail translation), not discrete per-day hard refresh
  - keep symmetric pre-rendered header overscan during active movement (one full day column on each side of the visible window)
  - render neutral skeleton placeholders for visible rows while movement continues
  - commit hydrated cell content only after movement idle gate opens (no full-page refresh).
- Left/right day controls and keyboard edge-shift navigation use a cache-first immediate hydration path:
  - one-day shift per activation
  - no idle debounce wait before hydration for the target window
  - if target-window cache is available, render hydrated cells immediately with no skeleton phase
  - if target-window cache is missing, render static placeholders immediately and hydrate asynchronously.
- Wheel/trackpad skeleton placeholder contract:
  - Placeholders are rendered only for currently displayed rows in the active date window.
  - Placeholder appearance is static (no moving/animated gradient).
  - During active lateral movement, skeleton rows remain visually static and are not repeatedly redrawn/moved.
  - After a debounced input pause, placeholders are replaced with hydrated row content for the current window.
- Lateral movement sensitivity uses normalized horizontal delta scaling:
  - normalize `WheelEvent` horizontal input to CSS pixels first (respecting `deltaMode`)
  - apply header translation as `0.5 * normalizedHorizontalDeltaPx` during active movement
  - on settle, snap to nearest full column using `round(translationPx / columnWidthPx)`.
- Timeslot label (left row-header) width/background remains visually stable during active lateral movement; no width expansion/jump when scan starts.
- Skeleton behavior remains config-backed, but scheduler contract expects skeleton-on-lateral-shift to be enabled by default.

### 8.4.1 Idle-Gated Fetch and Render Contract
- A single 300 ms idle gate controls both schedule-row fetching and cell rendering for wheel/trackpad movement and jump-style navigation (`Jump-to`, previous/next non-empty).
- During active movement:
  - day/date headers move continuously via horizontal translation
  - header coverage must remain continuous across the visible day-track width on narrow displays (no partial-width blank/gap while sliding)
  - visible rows show neutral static skeleton placeholders
  - schedule cell payload fetch/render is deferred.
- Latest-window-only behavior:
  - windows traversed during continuous movement are not fetched
  - only the final settled target window is fetched/rendered after idle
  - stale in-flight responses for older windows must be canceled or ignored.
- On settle:
  - header rail snaps to nearest full-column day alignment
  - skeleton rows are replaced by hydrated row content for that settled window.
- Immediate arrow/day-control path:
  - left/right day controls and keyboard edge-shift day movement bypass idle debounce and hydration lock delays
  - target-window hydration starts immediately (cache-first) while preserving stale-response cancellation rules
  - edge-shift fetches are not counted toward wheel/trackpad fast-scan lock activation.
- Jump-to uses the same model:
  - header updates immediately to the target window
  - target fetch/render runs asynchronously after idle gate
  - implementation must not scroll/animate through intervening windows.
- Rendering correctness:
  - empty-slot fade status must be correct on first committed render of each cell
  - a second pass to fix fade state is non-compliant.
- Row commit may be row-by-row or full-window once idle fetch completes; skeleton placeholders remain until each committed row is ready.

### 8.5 Scroll ownership
- Required model: page owns vertical scrolling; schedule grid must not trap vertical scroll.
- Schedule grid captures horizontal intent only.
- Grid-level vertical scrollbars should not be shown in normal layout.
- Grid-level horizontal scrollbars should not be shown in normal layout.
- Vertical-intent wheel input over the grid must bubble to normal page scroll (no `preventDefault` for vertical intent).
- Horizontal-intent wheel input over the grid is handled by the grid and may use `preventDefault` to block browser back/forward swipe navigation.
- Full 24-hour content must remain visible through page scroll.

### 8.6 Navigation side effects
- No full reload for previous/next non-empty, arrow movement, jump actions, or wheel/trackpad horizontal navigation.
- Lateral movement may synchronize URL/permalink state in place when throttled and race-safe.
- Lateral movement must not create new browser history entries per shift.
- Lateral movement must not trigger browser back/forward page navigation while interaction is inside the schedule grid.
- Lateral movement must use in-place state + async fetch updates (not `window.location.assign`, not `location.reload`).
- Lateral movement should be race-safe (coalesce/cancel stale requests and commit only the latest navigation intent).

### 8.7 Slot status card defaults
- Default slot status text must be exactly: `Select a time slot`.
- Before selection, no extra helper text is shown.
- `View` and `Legend` actions remain visible before selection.
- After selection, show:
  - selected slot
  - summary
  - change count for the currently selected slot
  - error count for the currently selected slot
- Selection applies to both slot states:
  - `empty` slots (no previously populated schedule payload for that day/hour)
  - `filled` slots (pre-existing populated schedule payload)
- Empty slots are first-class editable targets when permissions allow; they are not view-only placeholders.
- If a date window has no pre-existing entries, the scheduler still renders the grid and editable empty slots.
- The old blocking/no-editor `no entries scheduled for ...` path is removed from schedule-page UX.
- Error count must expose a details affordance (expandable `Errors` section or equivalent); if no existing expand control is present, provide an `Errors` section adjacent to the count.
- Error details must list each error with source and message.
- Phase D selection scope is single-slot only.

### 8.8 Slot status actions
- Slot status card includes `View` and `Legend` buttons.
- With a selected slot, `View` label changes to `View/Edit` only when that selected slot is editable (applies equally to `empty` and `filled` slots).
- For read-only users, button label remains `View`; the slot modal keeps the same field structure in a disabled/read-only state and fields remain visible.
- When no slot is selected, `View` opens a read-only informational modal template.
- `View` vs `View/Edit` label must update deterministically on every selection/focus change and after save/error state transitions for the active slot.

Conflict check against this implementation pass:
- No additional conflicts identified.
- The `Errors` section must always be expandable (compact compact rows) rather than a tooltip-only affordance.

### 8.9 Modal and edit flow consolidation
- The former edit form must be integrated into the View/View-Edit modal for editable users.
- Modal title text must be exactly `Selection Details`.
- Add an explicit `Exit` button to the modal.
- `Esc` closes the modal.
- Save action is moved into the modal.
- Device schedule save/apply is modal-only; there is no page-level save/apply button.
- Empty-slot and filled-slot modal bodies must use the same field structure.
- For empty slots, save creates/populates that slot through the same modal flow (no separate create modal).
- Pre-existing selected-slot errors loaded from server state must be surfaced in the same error-details view and included in selected-slot error count.
- The modal form surface should preserve the existing slot entry layout for all modes, with edit mode unlocking controls and read-only mode disabling them.
- Save flow for editable users:
  - If no modal change-set exists, show a `No changes` error dialog and do not submit.
  - If modal validation errors exist (including pre-existing blocking errors), show an `Outstanding errors` dialog and block submit.
  - If valid modal change-set exists, submit immediately with no confirm-before-publish step.
- Successful save may use full-page refresh only if the currently viewed schedule columns/window are restored after refresh.
- Server-side irreconcilable save failures must show per-slot errors with source/message and keep modal changes retryable for a different selected duration/window.
- Legend action moves to the slot status card position currently occupied by Save.
- For multi-slot operations, draft changes are held inside modal session state and are not rendered as persistent unsaved edits across grid cells before submit.

### 8.9.2 Duration expansion and multi-slot booking flow
- Selection remains a single anchor slot, but modal edit may apply one atomic change-set across multiple consecutive slots.
- Modal must provide a fast duration action:
  - `+30 min` action that expands the anchor booking into the next eligible slot.
- Modal must also provide both of the following longer-duration controls without leaving the modal:
  - preset increments (`+60 min`, `+90 min`, `+120 min`)
  - explicit end-time selection
- Duration expansion has no maximum cap in the UI contract; users may target any consecutive 30-minute slot window.
- While the selected anchor slot is editable, duration controls remain interactive:
  - end-time selector must stay enabled
  - increment buttons must remain enabled and accumulate duration up to available in-window bounds.
- Modal must show affected-slot preview before submit:
  - start slot (anchor)
  - end slot/time
  - count of impacted slots
- Submit applies the full affected-slot set atomically.
- Partial writes are not allowed for a single modal apply:
  - if any targeted slot is invalid/non-editable/conflicting, block submit and show per-slot source/message errors.
- If server-side irreconcilable conflict occurs after submit:
  - the full apply is rejected (no partial commit)
  - conflict details are shown in modal
  - user adjusts duration/window and retries
- On success, all affected slots update in place and the selected anchor slot remains/restores focus.
- No cross-slot unsaved state should remain visible in the grid after modal close unless apply succeeded.

### 8.9.1 Canonical scheduler slot schema
- This specification defines a single canonical frontend/backend contract for schedule slots.
- Frontend and backend must use this schema directly.
- Canonical slot granularity is 30 minutes.
- `slotKey` includes `date`, `hour`, and `minute` where `minute` is `0` or `30`.
- Schedule grid rows and keyboard row traversal follow the same 30-minute slot granularity.

Scheduler window read model (`GET /json/device/<device_id>/schedule-window?start=YYYY-MM-DD&days=1..31`):
```json
{
  "window": {
    "start": "2026-03-05",
    "days": 7,
    "timezone": "America/New_York"
  },
  "slots": [
    {
      "slotKey": { "date": "2026-03-05", "hour": 9, "minute": 0 },
      "baseline": "opaque-slot-version-token",
      "state": "empty",
      "editable": true,
      "entry": {
        "group": "",
        "member": "",
        "support": {
          "tech": { "requested": false, "handler": "", "subkind": "cover" },
          "train": { "requested": false, "handler": "" },
          "med": { "requested": false, "handler": "" }
        }
      },
      "summary": {
        "primary": "open",
        "secondary": "unassigned",
        "tertiary": "no support requests"
      },
      "errors": []
    }
  ]
}
```

Slot save contract (`POST /json/device/<device_id>/schedule-slots`):
```json
{
  "changes": [
    {
      "slotKey": { "date": "2026-03-05", "hour": 9, "minute": 0 },
      "baseline": "opaque-slot-version-token",
      "entry": {
        "group": "grp-a",
        "member": "user-123",
        "support": {
          "tech": { "requested": true, "handler": "tech-007", "subkind": "support" },
          "train": { "requested": false, "handler": "" },
          "med": { "requested": false, "handler": "" }
        }
      },
      "notify": true
    }
  ]
}
```

Save response contract:
```json
{
  "saved": [
    {
      "slotKey": { "date": "2026-03-05", "hour": 9, "minute": 0 },
      "baseline": "new-opaque-slot-version-token",
      "state": "filled",
      "summary": {
        "primary": "grp-a",
        "secondary": "user-123",
        "tertiary": "support: tech"
      },
      "errors": []
    }
  ],
  "failed": [
    {
      "slotKey": { "date": "2026-03-06", "hour": 10, "minute": 30 },
      "retryable": true,
      "errors": [
        {
          "source": "member",
          "code": "conflict",
          "message": "selected duration overlaps a conflicting booking",
          "blocking": true,
          "origin": "server"
        }
      ]
    }
  ]
}
```

Error object requirements (single schema for UI + API):
- `source`: stable field identifier shown in inspector/modal error rows.
- `code`: machine-stable error code.
- `message`: user-facing text.
- `blocking`: boolean gate for save submission.
- `origin`: `client` or `server`.

### 8.9.3 Save robustness and DB compatibility
- Empty-slot creation and multi-slot apply must be compatible with current `tblsched` constraints.
- `tblsched.scheddow` persisted values must use the database weekday encoding:
  - `0 = Sunday`, `1 = Monday`, ..., `6 = Saturday`.
- Backend save normalization for synthetic/new slots must derive `scheddow` from selected date using that encoding before persistence.
- Save flow must stage and validate the full modal change-set before persisting new rows; partial/incomplete placeholder rows must not be flushed.
- User-correctable save failures (validation/conflict/integrity issues) must return structured slot errors in canonical `source/code/message/blocking/origin` shape and keep the modal retryable.
- HTTP 500 is non-compliant for user-correctable slot save failures.

### 8.9.4 Input focus and typing stability
- Group/member/support handler inputs in the modal must retain focus and caret position across typing.
- Keystrokes must not trigger replacement/re-mount of the focused input element.
- Per-keystroke validation may update status affordances, but must not rewrite input value or force cursor jump.
- Canonicalization/ID normalization may occur on explicit option pick, blur, or submit preparation; invalid values must surface inline errors without destroying typed input.
- Keyboard editing behavior (`Backspace`, `Delete`, arrow keys, `Home`, `End`) must remain native.

### 8.9.5 Support request editing surface
- Modal must expose a complete support-request section using the same slot form contract for empty and filled slots.
- Required controls:
  - technologist: `requested`, `kind` (`cover`/`support`), `handler`
  - training: `requested`, `handler`
  - medical coverage: `requested`, `handler`
- Read-only mode keeps the same support controls visible but disabled.
- Editable mode enables controls for eligible support kinds even when no existing support request row exists yet.
- Request filing and assignment behavior:
  - slot editors must be able to file requests (`requested`) across visible support categories for the device.
  - handler assignment remains permission/roster constrained, but lack of handler-assignment permission must not block filing a request.
- Support request edits are part of the same atomic duration apply payload as group/member edits.
- Slot summary/support badges and error rows must reflect support-request changes and failures in place.

### 8.10 Slot selection behavior
- Selection model is single-slot.
- Single-slot model means one active anchor cell in the grid; multi-slot duration apply is launched from that anchor inside modal flow.
- Selecting different slots must not reposition schedule viewport.
- Selected cell should be highlighted and slot status content updated in place.
- `Enter` on the selected slot triggers the same modal-open behavior as clicking `View`/`View/Edit`.
- Double-click on a slot triggers the same modal-open behavior as `Enter` and `View`/`View/Edit`.
- Keyboard arrow navigation must move exactly one adjacent visible cell per key press in the indicated direction (no unintended skipping).
- When keyboard left/right is invoked at the current window edge, the visible date window should shift by one day in that direction while preserving row focus.

### 8.11 Sticky elements during vertical scroll
- Schedule-local sticky behavior includes:
  - the grid day/date header rail
  - left/right day arrow controls.
- Jump controls and slot status/inspector remain non-sticky across breakpoints.
- Day/date header format: `<Day> (<Mon-Abbrev>-<DD>)` (example: `Mon (Jan-05)`).
- Sticky behavior must remain stable while rows hydrate and empty-slot fade styling is re-synced.
- Mobile sticky rule:
  - keep the grid day/date header sticky
  - keep left/right day arrows sticky and anchored directly below the sticky header
  - keep jump controls and slot status/inspector non-sticky.
- Sticky header bar must reserve/expand its own height so content above does not shift during stick/unstick transitions.
- Sticky arrows must render above grid body content with sufficient z-index so the left arrow is never obscured.

### 8.12 Jump-to control
- Default date in Jump-to input is current ET date.
- Jump-to is an explicit navigation action and updates URL query state (`start`, `days`) to keep shareable/reload-safe permalinks.
- In JS-enabled mode, Jump-to should update content in place and sync permalink state without full reload.
- In no-JS mode, Jump-to may fallback to standard GET navigation with the same query params.

### 8.13 Resilience and failure handling
- Fetch failures for newly requested dates must be non-blocking.
- Users must retain navigation controls and retry path after transient errors.
- Error messaging should be visible but should not reset current selection/navigation state.
- User-correctable slot save failures must surface as structured modal errors and must not crash into an unhandled server 500 response.

### 8.14 Time zone standard
- Scheduler UI date defaults, day headers, and jump-to behavior always use ET (`America/New_York`), regardless of browser locale.
- Database clock is the canonical and only server source for `current date` resolution in the UI.
- Backup server clocks and client-side clock fallback are out of scope for this spec revision.
- ET date/time resolution must follow DST transitions in `America/New_York`.

## 9. RBAC Page
- RBAC page is accessible to admins and delegated PI users.
- Delegated PI/non-admin users follow the RBAC model split:
  - Group PI of non-`DEV` groups: managed-group scope only.
  - DEV PI: managed `DEV` group scope plus all active devices (not constrained by `devicegroup` links).
- RBAC and email audit feeds remain admin-only, and delegated PI/non-admin users must not see audit tabs/panels rendered in RBAC UI.
- RBAC audit log module should exist on RBAC page (replacing the existing bottom RBAC Audit section).
- RBAC audit log must be removed from Admin Panel page.

### 9.1 Technologist Join Workflow
- `/join/tech` submissions from eligible DEV users are auto-approved (no PI review queue).
- Auto-approval must immediately set technologist-approved state.
- Auto-approval still writes RBAC/email audit records and should notify the requester of approved outcome.
- Eligibility guardrails for accessing `/join/tech` remain unchanged.

## 10. Admin Panel Page
- All content must fit narrow displays without horizontal page scrolling.
- `Potential issues` sections are collapsed by default.
- After detection scan runs, `Potential issues` sections remain collapsed until user explicitly expands.

## 11. Accessibility Requirements
- Icon-only and compact controls require accessible names.
- All primary actions (`View`, `View/Edit`, `Legend`, previous/next, arrows, show more) must be keyboard reachable.
- Focus indicator must remain visible in compact and icon-only layouts.
- Respect `prefers-reduced-motion`: disable smooth scrolling/animated snap transitions when reduced motion is requested.

## 12. Performance Requirements
- Horizontal navigation should remain smooth under repeated wheel events.
- Avoid expensive synchronous layout recalculation in scroll handlers.
- Responsive transitions (button collapse, day-count adaptation) should not trigger visible layout thrash.
- Use request cancellation/coalescing so rapid lateral input does not commit stale window responses.
- Avoid flooding permalink synchronization during high-frequency input.
- If `history.replaceState` is used for in-place permalink synchronization, its cadence must be independently throttled from hydration/fetch timers so browser security limits are not exceeded during rapid interaction.

## 13. Acceptance Criteria
1. Top nav follows the four-state responsive sequence in 6.1, with no button-4 cross-over, no pre-icon extra right-edge whitespace, and icon-only transition only after center-gap compression has advanced sufficiently.
2. Homepage groups/devices support 200 ms debounced name-only search from a single character.
3. Homepage lists default to 5 items, `Show more` appends 10 items per activation, and filter changes reset visible count + hide `Show more` until the 2 second re-enable check completes.
4. Device Schedule no longer shows dynamic `schedule for...from...to...` header text.
5. Default wide-layout schedule starts Monday and spans 7 days.
6. Narrow layouts reduce visible days (up to one day) with no horizontal page scrollbar, no grid horizontal scrollbar, and no partial day columns.
7. Computed maximum day-column width updates with viewport changes and bounds any user-selectable width control.
8. Sticky behavior keeps the schedule day/date header pinned with no layout shift in content above it, and left/right arrows remain visible/sticky directly below that header rail.
9. Horizontal wheel/trackpad movement drives continuous header sliding using normalized-delta scaling (`translationPx = 0.5 * normalizedHorizontalDeltaPx`) and snaps to day boundaries on release (or 120 ms idle fallback).
10. Arrow controls move exactly one day per activation and remain visible above grid cells at all scroll positions.
11. Vertical-intent wheel input over the schedule scrolls the page, while horizontal-intent wheel input is captured by the grid for lateral navigation.
12. Slot status defaults to `Select a time slot`, keeps actions visible before selection, and on single-slot selection shows selected slot, summary, and selected-slot change/error counts; error count includes an `Errors` details affordance listing error source/message.
13. Slot status card exposes `View`/`Legend`; with a selected slot, `View/Edit` appears only when that slot is editable; `Enter` opens the same modal action and `Esc` closes the modal.
14. Modal title is `Selection Details`; save runs inside modal with `No changes` and `Outstanding errors` blocking guards (including pre-existing blocking errors), no confirm-before-publish step, and full-refresh success only when viewed columns/window are restored; multi-slot duration applies are atomic and irreconcilable save failures return conflict details for retry.
15. Jump-to defaults to current ET date and updates permalink query state (`start`, `days`) as an explicit navigation action.
16. RBAC audit log appears on RBAC page and is absent from Admin page.
17. Admin page has no horizontal overflow on narrow displays and keeps `Potential issues` collapsed by default, including post-scan.
18. If continuous rendering is degraded, currently displayed rows may show static (non-animated) skeleton placeholders that remain fixed during movement while the header rail slides; placeholders are replaced only after settle hydration, and this behavior is controlled by a config feature flag.
19. Scheduler date defaults and day headers remain ET (`America/New_York`) regardless of browser locale.
20. ET current-date resolution for scheduler UI uses database clock only (no backup server clock and no client fallback).
21. Delegated PI/non-admin users follow the RBAC model split: Group PI of non-`DEV` groups is managed-groups-only; DEV PI includes managed `DEV` group controls plus all active-device scope; RBAC/email audit tabs/panels are not rendered for non-admin delegated users and audit feeds remain inaccessible.
22. Lateral navigation inside the schedule grid never triggers browser back/forward page navigation and does not create new history entries per micro-shift; outside-grid gesture behavior remains default, and in-place permalink sync remains throttled.
23. JS-enabled Jump-to updates scheduler state and URL without full reload; no-JS fallback GET remains functional.
24. Eligible `/join/tech` submissions auto-approve technologist status immediately and emit requester outcome notification/audit events.
25. Empty and filled slots both open the same modal contract; editable empty slots can be created/populated in-place without a separate create flow.
26. Scheduler frontend/backend communication uses the canonical slot schema with unified `source/code/message/blocking/origin` error objects.
27. Windows with no pre-existing entries still render editable empty slots (permission permitting) and do not switch to a blocking/no-editor empty-state note.
28. Modal supports anchor-based duration expansion with both preset increments and explicit end-time selection (including `+30 min`), allows uncapped consecutive-slot windows, and applies booking changes atomically without persistent pre-submit unsaved grid state.
29. Schedule rows and row-level keyboard traversal operate at 30-minute resolution consistent with canonical `slotKey` granularity.
30. Saving edits that create/populate new slots (including Sundays) persists `scheddow` in database `0..6` encoding (`0=Sunday`) and does not trigger `tblsched_scheddow` check-constraint failures.
31. User-correctable save failures are returned as structured slot-level errors in modal context and keep edits retryable; no HTTP 500 path is exposed for those failures.
32. Typing in modal `group`, `member`, and support `handler` fields preserves focus/caret and does not blur or reset the cursor on each keystroke.
33. Modal exposes support-request controls (technologist/training/medical) for eligible slots, and support edits participate in the same atomic apply semantics as other slot fields.
34. Schedule grid does not own a vertical scrollbar; full 24-hour row content remains reachable via page scroll.
35. Empty rows remain visible in the current visible date window, and empty slots are visually faded to preserve scanability without collapse controls.
36. Left/right day navigation controls shift the visible window by exactly one day per activation with immediate target-window hydration (cache-first); skeleton placeholders are shown only when target-window cache is missing.
37. Double-clicking a slot opens the same modal flow as `Enter` and `View`/`View/Edit`.
38. Keyboard arrow navigation moves exactly one adjacent visible cell in the indicated direction without unintended skipping.
39. `View` vs `View/Edit` state updates reliably with selection/editability changes and after save/error transitions.
40. When the anchor slot is editable, duration increment controls and end-time selector remain enabled until bounded only by available in-window slots.
41. Support-request UI allows filing requests across visible categories; handler assignment remains permission/roster constrained without blocking request filing.
42. Scheduler hydration/render guardrails use a single 300 ms idle gate for both fetch and render on wheel/trackpad and jump-style navigation while movement feedback stays header-first with skeleton rows.
43. Wheel/trackpad movement updates headers immediately but defers schedule-row fetch/render until 300 ms idle; traversed/intermediate windows are not fetched.
44. Jump-to updates target header/window state without scrolling through intervening dates, and fetch/render occurs asynchronously under the same idle-gated contract.
45. Empty-slot fade state is correct on first committed cell render and does not require a second reconciliation pass.
46. During active lateral movement, header feedback is delivered as smooth translation rather than discrete date-jump refresh; on settle, alignment snaps to full-day columns.
47. Visible day columns are computed from viewport width and rendered as a whole-number count only; partial columns and horizontal grid scrollbars are non-compliant.

## 14. Traceability Matrix (`ui-fixes.md` -> This Spec)
| UI Fix Request | Spec Section |
| --- | --- |
| Top nav responsive shrink and equal spacing behavior | 6.1 |
| Homepage button MRI icon (black/white) | 6.2 |
| Homepage groups/devices search parity with RBAC filter | 7.1 |
| Homepage show more beyond 5 items (+10 per click) | 7.2 |
| Remove dynamic schedule range text | 8.1 |
| Previous/next non-empty no reload/no jump/visual feedback | 8.4, 8.6 |
| Rename modal title to Selection Details | 8.9 |
| Slot status default text and selected-state content | 8.7 |
| Slot status View + Legend buttons, per-slot permission-aware label | 8.8 |
| Jump-to default current date | 8.12 |
| 7-day Monday-first default on unconstrained layout | 8.2 |
| No horizontal scrollbar; adapt to narrow displays | 8.2, 8.3 |
| Auto-compute max column width and cap user selectable width | 8.3 |
| Fixed-width timeslot labels | 8.3 |
| Smooth lateral movement and one-day arrows without URL/reload | 8.4, 8.6 |
| Continuous wheel movement + snap-on-release (120 ms idle fallback) + skeleton fallback | 8.4 |
| Vertical scroll owned by page, not trapped by grid | 8.5 |
| URL query state stays shareable/reload-safe and is synchronized in place without in-grid back-swipe regressions | 5, 8.6, 8.12 |
| Integrate edit form into modal, move Save/Legend placement | 8.9 |
| Create/populate schedule entries from empty slots using same modal flow | 8.7, 8.9, 8.9.1 |
| Expand booking by duration from modal (`+30 min` and longer) with atomic multi-slot apply | 8.9.2 |
| `scheddow` compatibility and structured save-failure handling for synthetic/empty-slot saves | 8.9.3, 8.13 |
| Typing/caret stability in modal entry inputs | 8.9.4 |
| Support request controls and atomic support edits inside modal flow | 8.9.5 |
| Keep all rows visible while fading empty slots for scanability | 8.3.1 |
| Skeleton-backed wheel/trackpad lateral scanning with one-day arrow/day-control immediate hydration | 8.4, 8.4.1 |
| Double-click slot opens same modal flow as Enter/View/Edit | 8.10 |
| Keyboard arrows move one adjacent visible cell without skipping | 8.10 |
| Slot selection should not move schedule viewport | 8.10 |
| Sticky day/date header with non-sticky top nav, mobile header+day-arrows stickiness, and no layout shift above sticky rail | 8.11 |
| ET timezone standard regardless of browser locale | 8.12, 8.14 |
| RBAC audit log placement change | 9 |
| Delegated PI scoped RBAC access with no audit tabs/panels for non-admin | 4, 9 |
| Admin narrow-display fit | 10 |
| Potential issues collapsed by default even post-scan | 10 |
| Reduced-motion and navigation/permalink hygiene best-practice alignment | 11, 12, 13 |
| Technologist join form auto-approval restoration | 9.1 |

## 15. Clarification Status
- Resolved clarifications captured in this revision:
  - Delegated PI scope follows RBAC model split: Group PI of non-`DEV` groups remains managed-group-only; DEV PI has broad active-device scope in delegated/non-admin mode.
  - Lateral schedule navigation inside the grid must not trigger browser back/forward page navigation; outside-grid gesture behavior remains default.
  - Skeleton placeholder fallback is config-flag controlled.
  - Homepage icon will be an engineering-created in-repo MRI scanner icon.
  - Homepage filter updates reset visible count and delay `Show more` re-enable by 2 seconds.
  - ET date source uses database clock only.
  - Off-hour-specific expando control remains removed; row density is conveyed via always-visible rows with faded empty slots.
  - Current `tblsched` weekday encoding is `0=Sunday..6=Saturday` and must be preserved in synthetic/new-slot save flows.
  - Modal text-entry UX must preserve focus/caret during typing.
  - Support request editing controls are required in the modal contract for eligible slots.
  - Double-click slot activation must match `Enter` and `View`/`View/Edit` modal-open behavior.
  - Hydration/render contract uses a single 300 ms idle gate for both fetch and render, latest-window-only fetching, first-pass-correct empty-slot fading, and header-only smooth lateral translation with settle snap.
  - Left/right day controls and keyboard edge-shift day movement bypass idle debounce/hydration lock and hydrate target windows immediately (cache-first), with placeholders only on cache miss.
- No open clarifications blocking implementation.

## 16. Implementation Test Matrix
- Contract test artifact (2026-03-06):
  - `tests/playwright/integration/device-schedule-lateral-contract.spec.ts` pins the Phase D/E lateral contract:
    - wheel/trackpad lateral scan enters placeholder mode during movement and hydrates on settle
    - day-arrow and keyboard edge-shift navigation hydrate immediately; placeholders appear only when target-window cache is missing
    - lateral movement keeps `window.history.length` and navigation-entry count stable (no per-shift history churn or reload)
- Top nav compression sequence:
  - Verify four ordered states: expanded -> center-gap compression with labels -> icon-only right-anchor with expanded center gap -> final equal-gap icon compression with symmetric side spacing.
  - Verify button 4 never crosses left of the first three controls during any transition.
  - Verify pre-icon states keep right-edge whitespace to container padding only.
  - Verify icon-only transition is driven by measured 3/4 center-gap pressure (not viewport-width constants).
- URL/permalink and navigation safety:
  - Lateral scroll/arrow/prev-next must not reload and must not trigger browser back/forward page navigation while interaction is over the grid.
  - Permalink `start/days` state remains shareable/reload-safe and may be synchronized in place with throttled updates.
  - Jump-to must update `start/days` permalink state and support back/forward.
- Mixed-axis input:
  - Vertical-intent wheel over grid scrolls page.
  - Horizontal-intent wheel is captured by grid and never triggers browser back/forward swipe navigation.
- Snap and rendering:
  - Snap on release (or 120 ms idle fallback).
  - Wheel/trackpad lateral movement renders static skeleton placeholders immediately for currently displayed rows while day headers advance via continuous horizontal translation.
  - During wheel/trackpad movement on narrow layouts, header track coverage remains continuous (no half-width blank header while incoming dates slide).
  - Header movement uses normalized-delta scaling (`translationPx = 0.5 * normalizedHorizontalDeltaPx`) and settles to nearest day-column alignment via `round(translationPx / columnWidthPx)`.
  - Schedule cell payload is not fetched/rendered during active wheel/trackpad movement; after ~300 ms idle, only the latest target window fetches/renders.
  - Left/right day controls and keyboard edge-shift day movement hydrate target windows immediately; placeholders are used only when target-window cache is missing.
  - Skeleton behavior follows config feature flag and defaults to enabled for lateral day scanning.
- Idle-gated fetch/render behavior:
  - During continuous lateral movement, no intermediate window fetches are issued.
  - After idle gate opens, fetches/renders apply only to the latest target window.
  - Jump-to does not animate/scroll through intervening windows.
- Row visibility density:
  - Empty rows remain visible for the current visible date window.
  - Empty slots are rendered in a faded state on first commit (no second pass needed).
  - Grid itself never acquires a vertical scrollbar; page scroll owns vertical movement across full 24-hour content.
- Responsive column fit:
  - Visible day count is recomputed from current width and rendered as full columns only (no partial day column).
  - No horizontal page/grid scrollbar is used for adjacent-day access; adjacent dates are accessed via lateral input + controls.
- Homepage filters and expansion:
  - Filter change resets visible-item count to 5 and immediately hides `Show more`.
  - `Show more` reappears only after ~2 seconds and only when filtered result count remains above visible-item count.
- Time source behavior:
  - DB clock ET path for date defaults/day headers/jump-to default.
  - DB clock unavailability path surfaces visible error while preserving current selection/navigation state.
- Slot status and modal flow:
  - Before selection, slot status shows exactly `Select a time slot` with visible `View`/`Legend`.
  - After selection, slot status shows selected slot + summary + selected-slot change/error counts.
  - Error count exposes details via existing expander or `?`, and detail rows include source + message.
  - `View/Edit` label is per-slot capability-based; read-only path remains informational.
  - `View`/`View/Edit` label updates consistently with selection/editability state changes.
  - `Enter` opens modal from selected slot, `Esc` and `Exit` close modal.
  - Double-click on selected cell opens the same modal flow as `Enter`.
  - Save in modal blocks on `No changes` and `Outstanding errors` (including pre-existing blocking errors), submits without confirm dialog when valid.
  - Post-save success may refresh only if viewed column window is preserved.
- Keyboard navigation:
  - Arrow keys move one adjacent visible cell per press without skipping.
- Save robustness and DB compatibility:
  - Creating/populating empty slots on all weekdays (including Sunday) persists `scheddow` in database `0..6` format and does not trigger check-constraint errors.
  - User-correctable save failures return structured slot errors and keep modal draft data retryable.
- Input stability:
  - While typing in modal `group`, `member`, and support `handler` fields, caret position remains stable and focused element is not replaced.
- Support-request editing:
  - Modal includes technologist/training/medical request controls (requested, handler, tech kind) for eligible slots.
  - Request filing is available across visible support categories; handler assignment stays permission/roster constrained.
  - Support-request edits are included in atomic duration apply payloads and reflected in slot summaries/error rows.
- Duration controls:
  - Editable anchor keeps duration increment buttons and end-time selector enabled until bounded only by available in-window slots.
- Irreconcilable failures surface per-slot source/message errors and keep modal change-set retryable so users can choose a different duration/window.
- RBAC visibility:
  - Admin can view RBAC + audit.
  - Delegated Group PI (non-`DEV`) sees managed groups only; delegated DEV PI sees managed `DEV` groups plus active devices.
  - Delegated/non-admin PI users have no audit tabs/panels in RBAC UI and cannot access RBAC/email audit feeds.
- Technologist join:
  - Eligible DEV user `/join/tech` POST sets approved status immediately.
  - Requester outcome notification and audit records are emitted.

## 17. ET Time-Source Error UX Copy
- DB clock unavailable:
  - `Database time unavailable. Unable to refresh ET date right now.`

## Template Compatibility Baseline
- Template compatibility is defined by the fully bootstrapped old dataset, not by raw `003-import-data.sql` alone and not by ad hoc synthetic template artifacts.
- Default local and route-test template fixtures must preserve only rooted patterns from that old compatibility baseline.
- Sparse templates are out of scope unless rooted historical data demonstrates them.
- Legacy empty-group sentinel values normalized by the old bootstrap (`'(none)'`) must render as the ordinary open/unassigned state in current template UI.
- Legacy researcher ids suffixed with `"[OLD]"` must remain visible for repair but block both template save and template apply until resolved.
- The normal template list, edit, and clone flows serve as the migration path; no separate legacy template interface is introduced.
- Saving a repaired template must preserve canonical full-grid template shape (`168` cells).

## 2026-03-10 rooted old-bootstrap findings

- A full bootstrap of the old worktree now succeeds against a standalone Postgres 15 container via [bootstrap-old-compat-db.sh](/Users/johnlee/.codex/worktrees/be6d/fmrif-scheduler-morse-version/scripts/bootstrap-old-compat-db.sh), with only in-flight compatibility normalization for legacy `plpgsql` and `default_with_oids` syntax.
- Concrete template-shape findings from the bootstrapped old database:
  - `138` templates total
  - every template is exactly `168` rows
  - `7,344` template cells reference `"[OLD]"` researchers after bootstrap
  - `8,288` template cells use `'(none)'` as the open-slot group sentinel
  - `114` templates are hidden
- The old bootstrap confirms that `"[OLD]"` template references are produced by the migration chain, not intended as pre-`018` import literals. For current-seed generation, rooted template researchers must therefore be emitted in pre-`018` form and allowed to cascade to `"[OLD]"` during `018-invalidate-old-researchercodes.sql`.
- A deterministic extractor now exists at [generate-rooted-template-seed.py](/Users/johnlee/.codex/worktrees/be6d/fmrif-scheduler-morse-version/scripts/generate-rooted-template-seed.py). It reads the bootstrapped old database and emits a rooted subset in pre-`018` seed form. The first checked-in derived artifact is [generated-rooted-template-subset.sql](/Users/johnlee/.codex/worktrees/be6d/fmrif-scheduler-morse-version/sql/generated-rooted-template-subset.sql).
- Current rooted subset target:
  - `d/a` hidden legacy-heavy template
  - `d/i` visible template
  - `d/j` visible template
  - `test/t` all-open template
- Device/group data confirmed from the old bootstrap:
  - `devicegroup` and `groupmembers` are the post-migration RBAC tables
  - `device d` has real linked groups and visible templates suitable for scheduler/template compatibility work

### Next implementation step

- Replace the hand-authored template portion of [003-import-data.sql](/Users/johnlee/.codex/worktrees/be6d/fmrif-scheduler-morse-version/sql/003-import-data.sql) with a generated rooted subset derived from the old bootstrap, then re-run the current migration chain until it survives `015`, `018`, and `900` cleanly.

### 2026-03-10 current-chain validation note

- The rooted generated subset is now validated against the current SQL chain on standalone Postgres through `900-import-new-data.sql`.
- `003-import-data.sql` should remain a thin wrapper around generated rooted legacy data plus a minimal current-dated schedule stub, rather than re-encoding template grids by hand.
- The generated subset must emit explicit `tbltemplates` and `tbltemplate` rows in data-dump shape. The current bootstrap loads `003-import-data.sql` under `session_replication_role = replica`, which disables the old `template_fill` rule; relying on default-fill plus updates leaves `tbltemplates` populated but `tbltemplate` empty.
- The current chain now intentionally supports both pre-`018` and post-`018` rooted researcher-code stages. `018-invalidate-old-researchercodes.sql` is idempotent, so clients can choose whether a fresh rooted dump is normalized before import or imported in already-suffixed form.
