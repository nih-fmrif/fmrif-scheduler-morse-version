# UI Overhaul Tasks

## 1. Scope-Locking Decisions
- Role terminology and semantics are fixed:
  - `PI` is always PI of a specific group.
  - `Group PI` means PI of a non-`DEV` group.
  - `Group PI of DEV` is the `DEV PI` role (same role; not a separate role type).
  - In general app UI, continue presenting this as Group PI of `DEV`; additional active-device capability is behavior-level authorization, not a separate user-facing role label.
- Delegated PI RBAC structure follows RBAC model split:
  - Group PI of non-`DEV` group (non-admin): managed groups only.
  - DEV PI (non-admin): managed groups plus all active devices (broad active-device scope; not constrained by `devicegroup` links).
  - A DEV member who is not Group PI of `DEV` does not get delegated PI management scope.
  - PI of another group does not imply DEV PI capability.
  - There is no DEV/non-DEV device class split in this model.
- DEV member semantics (RBAC model):
  - approved, active membership in group `DEV` is normal group membership status.
  - may enable DEV-member workflows and DEV-user assignment paths.
  - does not by itself grant DEV PI privileges, admin privileges, or global active-device management capability.
- Admin-only capabilities remain explicit and unchanged:
  - create groups/devices
  - access/edit inactive-entity admin views
  - toggle active/inactive state on groups/devices
  - access RBAC/email audit feeds
- Lateral schedule movement (wheel/trackpad horizontal, left/right arrows, previous/next non-empty) must not trigger browser back/forward page navigation while interaction is over the schedule grid.
- Outside the schedule grid, browser/app back-swipe behavior remains default.
- Jump-to/permalink actions remain explicit shareable navigation paths; in-place permalink synchronization may also occur when throttled.
- Skeleton placeholder rendering for degraded lateral performance is controlled by a config feature flag.
- Homepage icon is an in-repo engineering-created minimalist black-and-white MRI scanner icon.
- Homepage filter changes reset visible count to 5, hide `Show more` immediately, then re-check after 2 seconds before showing `Show more` again.
- ET date resolution uses database clock only (no backup source and no client clock fallback).
- Lateral hydration/render guardrail uses one idle gate (`300 ms`) for both fetch and render on wheel/trackpad and jump-style navigation (Jump-to and previous/next non-empty), with latest-window-only commit.
- During active lateral movement, the header rail slides continuously (not discrete date-refresh jumps), then snaps to nearest day alignment on settle.
- During active lateral movement, header rendering keeps one overscan day column on each side of the visible window so narrow viewports do not show partial-width blank header track.
- Lateral movement uses normalized horizontal input scaling:
  - convert `WheelEvent` delta to CSS px (`deltaMode` aware)
  - apply header translation as `0.5 * normalizedHorizontalDeltaPx`
  - snap on settle by nearest column with `round(translationPx / columnWidthPx)`.
- Visible day columns are width-derived whole-number columns only; partial columns and horizontal scheduler scrollbar are non-compliant.

## 1.1 Current Schedule-Track Status (as of 2026-03-06)
- Phase D (`Schedule Header/Inspector/Modal Contract`): resolved for current scope and validated with Playwright integration coverage.
- Phase E (`Lateral Navigation Engine Refactor`): resolved for current scope and validated with Playwright lateral-contract coverage.
- Phase F (`Responsive Schedule Layout and Scroll Ownership`): resolved for current scope and validated across responsive integration flows.

## 2. Delivery Phases

### Phase A: Baseline and Guardrail Tests
- Add/adjust route and Playwright coverage to encode the final behavior before refactors.
- Focus areas:
  - homepage filter/show-more timing and reset behavior
  - schedule lateral navigation permalink/safe-swipe invariants
  - schedule lateral contract split-path behavior:
    - wheel/trackpad scan path uses placeholders during movement and hydrates on settle
    - day-arrow and keyboard edge-shift paths hydrate immediately; placeholders appear only when target-window cache is missing
    - lateral movement keeps `window.history.length` and navigation-entry count stable
  - RBAC delegated PI scope split (Group PI of non-`DEV` group = groups-only; DEV PI = managed groups plus all active devices)
  - admin `Potential issues` collapsed-default assertions
  - ET DB-clock-only behavior
- Primary files:
  - `tests/unit/test_home_navigation.py`
  - `tests/playwright/integration/device-ui-interactions.spec.ts`
  - `tests/playwright/integration/device-schedule-lateral-contract.spec.ts`
  - `tests/unit/rbac_page/test_rbac_page_part_01.py`
  - `tests/unit/rbac_page/test_rbac_page_part_08.py`

### Phase B: Top Nav Responsive + Home Icon
- Implement top-nav compression sequence:
  - equal-gap shrink first
  - compact button footprint second
  - icon-first presentation when necessary
- Add in-repo MRI home icon and keep compact/icon-only accessibility naming intact.
- Primary files:
  - `scheduler/templates/page.html`
  - `scheduler/templates/svg/icons.html`
  - `scheduler/static/css/admin.css`

### Phase C: Homepage Search + Show More Timing
- Add groups/devices search inputs with:
  - 200 ms debounce
  - 1-character threshold
  - name-only matching
- Implement list truncation:
  - default 5 visible
  - +10 per `Show more`
- Implement filter-triggered reset contract:
  - immediate reset to 5
  - immediate hide of `Show more`
  - delayed (2s) `Show more` visibility re-evaluation
- Primary files:
  - `scheduler/templates/index.html`
  - `scheduler/static/js/scheduler-editor/index.js`
  - `scheduler/static/css/admin.css`

### Phase D: Schedule Header/Inspector/Modal Contract
- Current implementation decisions for this pass:
  - Single-slot anchor inspector modal is authoritative for both view and edit; there will be no separate edit form modal.
  - Primary slot action remains `Details`; selected read-only slots surface an explicit lock cue while editable slots show no edit icon.
  - Modal must render identical slot field structure in both modes; read-only mode disables the same fields rather than replacing/removing form content.
  - Error details will use an expandable `Errors` section inside inspector status/modal (not a `?` icon/button), rendered as compact list items.
  - Save flow is fully modal-driven with explicit guard checks for `No changes` and `Outstanding errors`.
  - Save result behavior targets in-place updates first; full refresh is only acceptable when view/window/selection can be restored deterministically.
  - In modal read-only mode, slot content should remain the same structure but disabled/read-only.
  - After save success, restore the selected slot in view whenever possible.
  - Pre-existing selected-slot blocking errors are surfaced immediately from loaded data.
  - Empty slots are editable targets (permission permitting); no separate create modal.
  - Multi-slot duration apply is anchor-driven from modal (`+1 hour` and longer options) and submitted atomically.
  - No page-level save/apply button for device scheduler; modal apply only.
- Off-hour-specific expando control remains removed; row density is indicated by faded empty-slot styling.
- Remove dynamic range copy (`schedule for ... from ... to ...`).
- Update inspector default state to exactly `Select a time slot`.
- Keep selection model single-slot; ensure post-selection content includes selected slot, summary, selected-slot change count, selected-slot error count.
- Ensure error count has an expand/details affordance; if no existing expander is present, use an `Errors` expandable section that lists error source and message.
- Keep `View` and `Legend` visible before selection.
- Keep `View` read-only informational behavior available before selection.
- Update modal title to `Selection Details`.
- Use per-slot read-only cue behavior: keep the primary action label as `Details`, add a lock cue when the selected slot is read-only, and show no icon for editable slots.
- Consolidate edit/save flow in modal for editable users; add modal `Exit` button and `Esc` close behavior.
- Ensure keyboard parity: `Enter` on selected slot opens the same modal flow as clicking `Details`.
- Enforce modal save guards: `No changes` dialog blocks empty submits, `Outstanding errors` dialog blocks invalid submits (including pre-existing blocking errors), and no confirm-before-publish step.
- On save success, full page refresh is acceptable only if current viewed columns/window are restored.
- Surface pre-existing selected-slot errors in the same details view and include source/message attribution.
- On irreconcilable server save failures, show per-slot source/message errors and keep modal state retryable so users can choose a different multi-slot window.
- Move `Legend` action into slot status card position defined by spec.
- Keep scheduler grid available in windows with no pre-existing entries (no blocking/no-editor empty-state path).
- Keep all 24 rows visible in the current date window and use faded styling for empty slots to preserve scanability.
- Add modal duration actions:
  - `+1 hour` quick action
  - preset increment actions (`+2 hours`, `+3 hours`, `+4 hours`)
  - end-time selector in the same modal flow
- Do not enforce a maximum duration cap in the modal UI contract.
- Keep duration increments/end-time selector enabled while anchor slot is editable (bounded only by available in-window slots).
- Canonical booking expansion granularity is one hour.
- Scheduler row model and row keyboard traversal must match hourly granularity.
- Require modal affected-slot preview (start/end/count) before apply.
- Require atomic apply semantics for multi-slot duration operations; block submit when any targeted slot is invalid/conflicting/non-editable.
- On submit conflicts, keep modal state retryable and report conflicts so user can choose a different multi-slot window; do not auto-lock slots due to conflict.
- Double-click on a slot must open the same modal flow as `Enter` and `Details`.
- Keyboard arrows must move one adjacent visible cell in the indicated direction without skipping.
- Keyboard left/right at the grid edge should shift the date window by one day and keep the current row anchored.
- Left/right day controls must shift view by exactly one day per activation.
- Wheel/trackpad day scanning should show immediate header-rail slide movement with static skeleton slot placeholders while cells hydrate.
- Left/right day controls and keyboard edge-shift navigation should shift one day with cache-first immediate hydration, no idle debounce wait, and placeholder fallback only on cache miss.
- Skeleton scope/perf contract:
  - show placeholders only on currently displayed rows in the active date window
  - use static placeholder styling (no animated gradient movement)
  - keep placeholders visually fixed during movement (no repeated redraw/motion)
  - on debounced pause, fully replace placeholders with hydrated row content and re-sync empty-slot faded styling

Critical contract corrections from QA feedback (2026-03-05):
- Save-path integrity and compatibility:
  - Empty-slot/synthetic-slot saves must persist the database weekday encoding (`scheddow`: `0=Sunday..6=Saturday`) and never emit invalid `7`.
  - Synthetic/new-slot normalization must not flush partial placeholder rows before full validation.
  - User-correctable save failures must return structured slot errors in modal context; no HTTP 500 crash path.
- Modal typing stability:
  - Typing into `group`, `member`, and support `handler` fields must not lose caret/focus on each keystroke.
  - Per-keystroke validation must avoid replacing the focused input node.
- Support-request editing parity:
  - Modal must include actionable support controls (`technologist`, `training`, `medical`) in editable mode, with read-only-disabled equivalents in view mode.
  - Support-request changes must be included in the same atomic duration-apply payload and error reporting as group/member edits.

Usability corrections from in-app review (2026-03-05):
- Row density + scanning:
  - Keep all rows visible in the current window and fade empty slots instead of collapsing.
  - Grid never owns vertical scrollbars; page scroll owns vertical movement across full 24-hour content.
  - Skeleton-backed lateral scanning is expected behavior for wheel/trackpad movement; left/right day controls and keyboard edge-shifts should hydrate immediately with skeletons only when target-window cache is missing.
- Interaction parity:
  - Double-click cell open behavior must match `Enter` and `Details`.
  - Arrow-key navigation must move to adjacent visible cells only, without intermittent skips.
- Sticky behavior:
  - mobile keeps the grid day/date header sticky
  - mobile keeps left/right day arrows sticky directly below the header rail
  - do not make jump controls or slot summary/inspector sticky on mobile
  - sticky header rail/background should reserve its own height so elements above do not shift during scroll
  - sticky arrows must remain visible above grid cells (left arrow must never be obscured)
- Action-label and duration reliability:
  - The read-only lock cue on `Details` must update deterministically as selection/editability changes.
  - Duration increment buttons and end-time selector remain enabled while editing is allowed.

Implementation notes:
- Errors are surfaced through the slot modal `Errors` expander using compact source/message rows.
- `Legend` belongs to the status card action area and replaces the previous save-button slot.
- Slot-level permissions drive the read-only lock cues on slots and the primary `Details` action while modal edit controls remain field-structure preserving in read-only mode.
- Empty and filled slots both use the same modal flow and field structure; editable empty slots can be populated in place.
- Scheduler slot data and error handling use one canonical schema across frontend/backend.
- Anchor-slot selection remains singular in the grid, while modal apply may target multiple consecutive slots as one transaction.
- Playwright behavior checks are the primary validation signal for Phase D UX contract; existing tests may lag this interface.

Resolved implementation checklist (completed by 2026-03-06):
- database `scheddow` mapping in synthetic/new-slot save path with structured retryable error surfacing for user-correctable failures.
- modal typing stability for group/member/support handler text inputs (caret/focus preserved).
- support-request editing controls restored for technologist/training/medical and included in atomic apply + error handling.
- Playwright scenario coverage for save-path and interaction corrections.
- always-visible 24 rows with empty-slot faded-state rendering.
- deterministic one-day left/right controls and adjacent-cell arrow navigation behavior.
- double-click parity with `Enter` and `Details`.
- duration controls remain enabled while editable; idle-gated skeleton-to-cell replacement behavior validated in Playwright.
### Phase E: Lateral Navigation Engine Refactor
- Replace reload/navigation-based lateral movement with in-place state transitions.
- Ensure wheel/arrow/prev-next behavior:
  - no `window.location.assign`
  - no `location.reload`
  - no `history.pushState` for per-shift lateral movement
  - throttled `history.replaceState` permitted for in-place permalink synchronization
  - back/forward swipe suppression applies only to horizontal-intent interaction over the schedule grid; outside-grid gesture behavior remains default
- Keep race-safe request handling:
  - cancel/coalesce stale requests
  - commit latest intent only
- Implement snap behavior (release or 120 ms idle fallback).
- Header-first movement feedback contract:
  - update day/date headers via continuous horizontal slide during lateral movement
  - keep header-track coverage continuous while sliding (no blank half-header on narrow two-column displays)
  - keep left timeslot-label column visually stable while sliding (no background/width expansion at movement start)
  - normalize wheel input to CSS px (`deltaMode` aware) and apply `translationPx = 0.5 * normalizedHorizontalDeltaPx`
  - show neutral static skeleton placeholders for visible rows while movement continues.
- Idle-gated fetch/render contract:
  - use a single `300 ms` idle debounce for both schedule-row fetch and cell rendering on wheel/trackpad and jump-style navigation (Jump-to + previous/next non-empty)
  - do not fetch intermediate windows traversed during continuous movement
  - on idle, fetch/render only the latest target window
  - on idle, snap header rail to nearest full-day column alignment
  - stale in-flight responses must be canceled or ignored.
- Arrow/day-control immediate contract:
  - left/right day controls and keyboard edge-shift day movement bypass idle debounce/hydration lock delays and hydrate immediately from cache/network for the target window
  - if target-window cache is missing, static placeholders are shown immediately while hydration completes
  - stale-response cancellation/latest-window commit remains required
  - edge-shift fetches do not contribute to wheel/trackpad fast-scan lock activation.
- Jump-to contract alignment:
  - Jump-to uses the same idle-gated fetch/render pipeline
  - no scrolling/animation through intervening windows to reach target date.
- Cell correctness contract:
  - empty-slot fade state must be correct on first committed cell render
  - no second-pass fade reconciliation.
- History-state guardrail:
  - when explicit state sync uses `history.replaceState`, throttle independently from hydration/fetch timers to avoid browser frequency-limit warnings.
- Validation additions (Playwright-first):
  - during continuous lateral movement, schedule-row fetch calls are not issued for intermediate windows
  - header rail movement is smooth/continuous (not per-day hard refresh) and uses normalized-delta translation scaling with settle snap by column-width rounding
  - on narrow displays (e.g., 2-day visible window), active wheel movement maintains continuous header-track coverage without partial-width blank gaps
  - active wheel movement keeps at least two overscan headers (one each side of visible window) and preserves timeslot-label column width
  - skeleton placeholders remain visually static during movement
  - after `300 ms` idle, only latest-target window fetch/render is committed
  - left/right day controls and keyboard edge-shift day movement render/hydrate immediately; skeleton placeholders are used only on target-window cache miss
  - Jump-to resolves directly to target window (no intervening-window traversal)
  - empty-slot cells render with correct faded state on first commit.
  - dedicated contract spec (`tests/playwright/integration/device-schedule-lateral-contract.spec.ts`) must enforce wheel-path placeholder behavior versus immediate arrow/keyboard hydration behavior.
- Primary files:
  - `scheduler/static/js/scheduler-editor/index.js`
  - `scheduler/routes/entity_routes.py`
  - `tests/playwright/integration/device-schedule-lateral-contract.spec.ts`

### Phase F: Responsive Schedule Layout and Scroll Ownership
- Enforce no horizontal page overflow across supported widths.
- Implement day-column max-width computation and resize/orientation clamping.
- Compute visible day count from current width and render whole columns only.
- Do not render partial columns.
- Preserve fixed timeslot label width.
- Enforce page-owned vertical scroll and horizontal-intent capture in grid.
- Do not use a horizontal scheduler scrollbar for adjacent-day access.
- Implement sticky contract:
  - sticky schedule day/date header after scroll-past
  - sticky left/right day arrows anchored directly below sticky header
  - mobile keeps day/date header + left/right arrows sticky (no additional sticky controls/status panels)
  - sticky header rail/background reserves height to avoid layout shift above it
- Primary files:
  - `scheduler/static/css/admin.css`
  - `scheduler/static/js/scheduler-editor/index.js`
  - `scheduler/templates/device.html`

### Phase G: Jump-to Explicit Navigation Contract
- Keep Jump-to as explicit action for URL/permalink updates.
- JS-enabled path:
  - in-place scheduler update
  - URL/permalink sync for `start`/`days`
  - no full reload
- No-JS path:
  - GET fallback with same query contract
- Primary files:
  - `scheduler/static/js/scheduler-editor/index.js`
  - `scheduler/templates/device.html`
  - `scheduler/routes/entity_routes.py`

### Phase H: ET DB-Clock-Only Time Source
- Standardize scheduler date defaults/day headers/jump-to defaults to ET from DB clock.
- Remove backup and client fallback paths from implementation.
- Add visible non-blocking error handling for DB clock unavailability while preserving current schedule state.
- Primary files:
  - `scheduler/logic/schedule_editor.py`
  - `scheduler/routes/entity_routes.py`
  - `scheduler/templates/device.html`

### Phase I: Feature Flag for Skeleton Fallback
- Add config-backed feature flag for skeleton-on-degraded-render behavior.
- Wire scheduler rendering path to respect flag on/off.
- Include flag documentation and default value.
- Primary files:
  - `scheduler/config.py`
  - `scheduler/static/js/scheduler-editor/index.js`
  - `README.md` (or config docs location used by repo)

### Phase J: RBAC/Admin Layout and Visibility
- Keep RBAC audit module on RBAC page only.
- Remove RBAC audit module from Admin page.
- Ensure delegated PI/non-admin UI and feed access constraints remain enforced:
  - no audit tabs/panels rendered
  - RBAC/email audit feeds remain inaccessible
  - Group PI of non-`DEV` group/non-admin scope remains managed groups only
  - DEV PI/non-admin scope includes managed groups and all active devices (broad active-device scope; not link-constrained)
  - Group-membership/PI workflows remain group-scoped; device-management workflows remain DEV PI/admin scoped
  - DEV PI remains presented as Group PI of `DEV` in general app interface terminology
  - admin-only capabilities (create group/device, inactive-entity admin access/edit, active/inactive toggles) remain restricted to admin
- Primary files:
  - `scheduler/templates/rbac.html`
  - `scheduler/templates/rbac_audit.html`
  - `scheduler/routes/_rbac_explorer_core.py`
  - `scheduler/routes/rbac_routes.py`

### Phase K: Admin Potential-Issues Collapse Behavior
- Ensure all `Potential issues` sections are collapsed by default.
- Preserve collapsed state after detection scan until explicit user expansion.
- Remove/adjust urgent-open auto-expansion behavior.
- Primary files:
  - `scheduler/templates/rbac_audit.html`
  - `scheduler/routes/rbac_issues.py`
  - `tests/unit/rbac_page/test_rbac_page_part_08.py`

### Phase L: Final Validation and Cleanup
- Execute relevant suites:
  - `pixi run test-unit`
  - `pixi run test-routes`
  - `pixi run test-integration-ci`
- Run hooks:
  - `pixi run pre-commit`
- Summarize:
  - changed files
  - test outcomes
  - residual risks (if any)

## 3. Open Implementation Questions
- None currently blocking implementation.
