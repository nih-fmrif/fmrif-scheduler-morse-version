# Scheduler debugging plan

## Scope

- Runtime scope: `codex-scheduler-20260309-1`
- Local app URL: `http://127.0.0.1:27173`
- Auth mode for browser exploration: mock admin session via `/auth/test/session`

## Goals

- Methodically reproduce scheduler UX bugs in the live scoped app.
- Capture backend errors and tie each user-facing failure to a concrete server-side cause when possible.
- Fix the smallest safe surface first.
- Add narrow Playwright integration coverage for confirmed regressions.

## Primary flows to inspect

1. Admin links devices to groups and verifies eligible members appear in scheduler assignment controls.
2. Single-slot booking from the inspector.
3. Multi-slot booking from the inspector, including review, cancel, reopen, and commit.
4. Review-pending flow with multiple unsaved edits across different dates/times.
5. Save failures and conflict handling, including retryability and user-visible error messages.

## Known reproduction target

1. Multi-slot edit state does not persist additional slots in the interface when the user sets up the edit but does not save.

## Working hypotheses

- Client draft state for multi-slot edits is being discarded when the inspector closes unless a save/review path commits cell state.
- Pending-review state and rendered grid state may be updated by different code paths, so the queue and the visible grid can diverge.
- Some server errors may currently surface as generic failures without preserving retryable client state.

## Execution plan

1. Reproduce baseline behavior with targeted Playwright scheduler flows against the scoped app.
2. Reproduce the known multi-slot persistence bug manually in Playwright terms and record the exact state transition that drops the extra slots.
3. Inspect app logs immediately after each failure to capture server exceptions, warnings, or malformed payload handling.
4. Read only the relevant scheduler editor and route code for the failing path.
5. Apply minimal fixes for the confirmed failure modes.
6. Add or extend Playwright integration coverage for the reproduced bugs.
7. Run the narrowest relevant Pixi tests, then `pixi run pre-commit` once changes are ready.

## Tracking

### Findings

- Confirmed: multi-slot duration edits only updated the anchor cell's local draft state. Extra targeted slots were computed for direct-save submission but were not mirrored into the pending-review/grid draft state, so closing the inspector left the interface showing only the anchor edit.
- Confirmed: inspector assignment inputs can diverge from their backing cell validation state. Invalid group/member values mark the hidden source cell as invalid, but the visible inspector clone can remain constraint-valid unless validation messages are mirrored back onto the clone.
- Confirmed: changing a valid schedulable group to a different schedulable group can leave the old member value constraint-valid on the client even when the backend rejects it as no longer valid for that group.
- Confirmed: review-pending confirm can dismiss the dialog without submitting any save request. The dialog hide event is fired on the container, not the confirm button, so the continuation callback can be skipped even when the user pressed confirm.
- Confirmed: multi-slot preview can show the expanded duration while the live pending-review state still tracks only the anchor slot. The previous mirroring guard depended on `aria-hidden="false"`, but the inspector dialog does not reliably expose that state while open.
- Confirmed: after saving a multi-slot edit, opening a different untouched slot can inherit the previous slot-count selection instead of defaulting back to a single slot. This leaves the inspector primed to overwrite multiple fresh slots accidentally.
- Confirmed: the review-pending confirm action can still collapse without submitting when multiple unsaved edits are queued together. In the live UI the dialog closes, the pending count remains unchanged, and no POST is issued.
- Confirmed: array-style server error payloads are misclassified as per-slot save errors. The result dialog then invents a fake `entry 0` failure instead of surfacing the backend message, which makes retries and log correlation misleading.
- Confirmed: partial multi-slot save responses are mishandled client-side. If the backend reports `saved > 0` and per-slot errors for the rest, the UI reports only success, clears all pending edits, and can close the inspector even though failed slots still need attention.
- Confirmed: after a partial multi-slot save leaves one failed slot pending, the badge can still report only `Review pending (1)` instead of `Review pending (1, 1 error)`. The failed slot's server-error state is being wiped by a no-op duration-sync refresh before the badge summary is recomputed.
- Confirmed: template-apply confirmation closes without submitting the form. The generic auto-confirm helper resolves confirmation state from the dialog hide event target, so pressing `apply templates` dismisses the dialog but never re-submits the POST.
- Confirmed: the seeded `TEST/A` template content in the live scoped app is malformed for current validation rules. The template has only three populated rows and includes stale group/member values (`TEST`, `DEV`, `testuser[OLD]`, `devpi[OLD]`), so the backend rejects application even after the confirm-submit bug is fixed.
- Tooling note: a direct non-Pixi integration launch failed with an environment mismatch (`flask_sqlalchemy` importing against an incompatible `sqlalchemy`). This was a harness issue, not an application bug.

### Fixes

- Implemented draft mirroring for duration-targeted slots in `scheduler/static/js/scheduler-editor/index.js`.
- Added finalization on inspector close so the currently mirrored multi-slot draft remains visible/pending after the dialog is dismissed.
- Added a Playwright regression to `tests/playwright/integration/device-ui-interactions.spec.ts` for the unsaved multi-slot close flow.
- Mirrored source control validation messages back into the inspector clone so the visible editor and the backing cell report the same invalid assignment state.
- Forced member revalidation whenever the group swap changes the backing datalist so stale roster members are marked invalid before review/submit.
- Latched review-dialog confirm intent on button click instead of the dialog hide event target, so review-confirm reliably submits pending save requests.
- Switched multi-slot draft mirroring to detect the live mounted inspector editor instead of relying on the dialog container's `aria-hidden` attribute.
- Bound `input[list]` validation handlers when scheduler cells are hydrated so dynamic schedule rows clear and recompute datalist validity the same way as initial page markup.
- Reset the inspector duration selection when the user opens a different slot, so stale multi-slot counts do not carry forward into unrelated edits after a save.
- Latched save-dialog confirm intent on pointer-down as well as click so real review-confirm interactions cannot lose the submit callback before the dialog hide event fires.
- Narrowed server-failure parsing so only object-shaped `errors` payloads are treated as per-slot save maps; array-style backend errors now render as plain result-dialog failure messages.
- Fixed partial-save reconciliation so result dialogs show both successes and failures, only successful slots are committed, and the inspector stays open whenever any targeted slot still failed.
- Preserved server-side slot errors across no-op duration resyncs so failed pending cells stay invalid and the review badge reports pending error counts accurately after partial saves.
- Latched generic confirm-dialog intent on button click instead of the dialog hide event target, so template application and any future auto-confirmed POST forms reliably submit after confirmation.

### Tests to add or update

- Updated `tests/playwright/integration/device-ui-interactions.spec.ts` for multi-slot draft persistence after closing the inspector.
- Added a Playwright regression covering clearing an already-saved assignment back to `open / unassigned` without leaving a stale member validation error.
- Added a Playwright regression covering stale multi-slot duration carryover after saving and reopening a different slot.
- Added a Playwright regression covering multi-entry review-pending confirm submission.
- Added a Playwright regression covering array-style server save failures so the dialog shows the backend message instead of a fake `entry 0` slot error.
- Added a Playwright regression covering partial multi-slot save failures so unsuccessful slots remain pending and visible after mixed save results.
- Tightened the partial multi-slot save Playwright regression so the review badge must include the failed-slot error count (`Review pending (1, 1 error)`).
- Added a Playwright regression in `tests/playwright/integration/device-subroutes.spec.ts` covering template application submission after the confirm dialog.
- Added a positive route test covering valid template application so `/device/<the_device>/templates` now has both rejection and success-path coverage.
- Add a narrower unit or route test only if the bug is rooted in server payload validation or save error policy.

## Follow-up issues requiring data cleanup or product clarification

- Seeded template data for `/device/TEST/templates` is not currently runnable in the scoped environment even though the UI offers it as available. This looks like legacy or fixture data drift rather than a client bug. Options:
  - repair or replace malformed seeded templates so at least one real template is applicable end-to-end
  - hide or badge malformed templates on the apply page instead of offering them as normal choices
  - clarify whether sparse templates are meant to be supported; if yes, relax `validate_templates_before_application()` accordingly

## Residual checks before wrapping

- Review-pending count matches visible unsaved edits after cancel/reopen flows.
- Multi-slot draft cells remain visible and editable before final commit.
- Failed saves keep actionable slot errors attached to the right cells and do not silently clear pending edits.

## 2026-03-10 stale-write retry follow-up
- Reproduced a true stale-write conflict in the current worktree scope with two live scheduler editors on the same blank future slot.
- Confirmed a client bug after the initial conflict response: the draft stayed pending, but the next `Save` never issued another POST because the overwrite conflict was persisted as a blocking validation error.
- Root cause: the client kept the stale `cell.orig` baseline after `type: "overwrote"` save failures, so the retry path hit the `outstanding errors` guard before submit instead of rebasing onto the server's expected value.
- Fix: pure overwrite save failures now rebase the affected slot's original values to the server-reported expected values while keeping the user's current draft intact.
- Regression coverage: added a Playwright save-flow test that returns an overwrite error on the first POST and asserts the second save posts rebased diffs and succeeds without refreshing the page.

## 2026-03-10 support handler follow-up
- Found a separate scheduler bug while trying to exercise support-request handler conflicts: medical and training handler inputs stayed disabled even when the current user had the matching device permission and the device had a non-empty support roster.
- Root cause: support-request subforms keyed permissions by `tech` / `train` / `med`, but the scheduler permission payload uses `tech` / `training` / `medical`.
- Fix: map support handler permission checks onto the correct scheduler permission keys before deciding whether handler inputs are editable.
- Current scoped runtime note: device `d` did not initially expose any support handlers because its support rosters were empty; I added a real medical permission for `user0049` on `d` in the current runtime to exercise the flow.
- Regression coverage: added Playwright coverage for medical handler enablement and for a medical-handler overwrite conflict that rebases and resubmits from the same draft.

## 2026-03-10 multi-slot inspector count follow-up
- Found another scheduler UI desync during live MCP exploration on `/device/d?start=2035-02-16&days=2`: after expanding a draft from one slot to three slots, the grid and review badge updated to `Review pending (3)` but the inspector summary still said `pending 0 changes`.
- Root cause: `update_inspector_counts()` only counted the anchor cell, and duration-draft mirroring did not refresh the inspector summary after copying values into the additional targeted slots.
- Fix: aggregate inspector pending/error state across all currently targeted duration slots and refresh the inspector counts after duration-draft mirroring.
- Follow-up correction: the final bug was also timing-sensitive. Mirrored target cells were flipping to `changed` after the anchor-cell refresh path had already run, so the working fix now schedules a second inspector recount on the next animation frame after duration mirroring settles.
- Regression coverage: extended the existing Playwright unsaved multi-slot draft test so the open inspector must show `2 changes` as soon as the duration is expanded.

## 2026-03-10 support-request clear regression
- Reproduced on `/device/d?start=2035-02-16&days=2` after granting `medical` support permission for `user0049`.
- Bug: unchecking `medical requested` disabled the handler input but left the stale handler value in place. Saving from that state appeared to clear the request in the live client, but a hard reload restored `support: medical` from persisted state.
- Root cause: the client treated handler values as meaningful even when the request checkbox was off, so the save diff could carry a stale handler without a corresponding `requested: false` transition.
- Fix direction: normalize support handlers to `""` whenever the request is inactive in UI state, draft snapshots, diff building, and committed client state.
- Regression coverage needed: save support request with handler, uncheck request, save, reload, confirm unchecked request with empty disabled handler.

## 2026-03-10 rooted template compatibility baseline
- Corrected an earlier inference: sparse template rows are not a rooted compatibility target based on the old SQL bootstrap reviewed in `~/.codex/worktrees/ade3/fmrif-scheduler-morse-version`.
- Confirmed rooted legacy template patterns from the old migration chain include:
  - full `168`-cell template grids
  - `researchercode` values suffixed with `"[OLD]"`
  - legacy empty-group rows normalized to `'(none)'`
- Updated the current seed/template baseline to remove sparse synthetic template shapes and replace them with canonical full-grid templates plus rooted legacy compatibility markers.
- Current template compatibility policy:
  - `'(none)'` renders as open/unassigned
  - `"[OLD]"` member assignments remain visible for repair
  - unresolved legacy issues block both template save and template apply
  - no separate legacy template interface; existing list/edit/clone flows serve as the migration path

## 2026-03-10 old-bootstrap template audit

Data work completed in a standalone Postgres 15 container using the old worktree SQL chain.

Concrete findings from the bootstrapped old database:
- `138` templates total
- all templates are full-grid `168` row shapes
- `7,344` template cells reference `"[OLD]"` researchers
- `8,288` template cells use `'(none)'`
- `114` templates are hidden

Important inference now confirmed by data and migration behavior:
- `"[OLD]"` researcher references are not a `003-import-data.sql` baseline literal in the rooted flow.
- They are produced by `018-invalidate-old-researchercodes.sql` after `015-reseachers.sql` adds `ON UPDATE CASCADE` researcher FKs.
- Pre-seeding `"[OLD]"` researcher codes in early template data causes bootstrap collisions on modern/current chains.

Grounded subset currently targeted for the fast rooted seed:
- `d/a` hidden legacy-heavy template
- `d/i` visible template
- `d/j` visible template
- `test/t` all-open template

Relevant old-data facts for scheduler-adjacent coverage:
- `device d` has real linked reservation groups in `devicegroup`
- `device d` group members in `groupmembers` match the schedulable roster previously observed in the UI (`AMRIS`, `BEI`, `DNU`, `FIM`, `HCPS`, `IPS`, `LFMI`, `LNI`, `NEI_USCA`, `NIDA`, `NMRF`, `SDAN`, plus `DEV`)
- visible `device d` templates are `i`, `j`, `k`, `l`

New tooling/artifacts:
- [bootstrap-old-compat-db.sh](/Users/johnlee/.codex/worktrees/be6d/fmrif-scheduler-morse-version/scripts/bootstrap-old-compat-db.sh): bootstraps the old repo into a target Postgres DB, with compatibility shims for legacy `plpgsql` and `default_with_oids` usage
- [generate-rooted-template-seed.py](/Users/johnlee/.codex/worktrees/be6d/fmrif-scheduler-morse-version/scripts/generate-rooted-template-seed.py): extracts a deterministic rooted subset from the bootstrapped old DB and emits pre-`018` SQL seed rows
- [generated-rooted-template-subset.sql](/Users/johnlee/.codex/worktrees/be6d/fmrif-scheduler-morse-version/sql/generated-rooted-template-subset.sql): first generated rooted subset artifact

Outstanding implementation work:
- wire the generated rooted subset into the current seed chain
- remove the remaining hand-authored template scaffolding from `003-import-data.sql`
- get the current repo bootstrap clean through `015`, `018`, and `900` using rooted generated data

### 2026-03-10 current-seed replay outcome

- Replayed the full current repo SQL chain into a standalone Postgres debug database after replacing the broken hand-authored template block in `003-import-data.sql` with `\ir generated-rooted-template-subset.sql` plus a smaller current-dated schedule stub.
- The first generated-subset shape was wrong in one important way: it inserted `tbltemplates` and expected the old `template_fill` rule to materialize `tbltemplate`. Under the current bootstrap, `003-import-data.sql` is loaded with `session_replication_role = replica`, so rules are disabled and the replay silently produced `4` template headers with `0` template cells.
- The generator now needs to emit explicit `tbltemplate` rows in rooted old-dump shape while still stripping researcher `"[OLD]"` suffixes back to pre-`018` values.
- With that correction, the success criterion is not just “the chain exits cleanly” but “the chain exits cleanly and the rooted templates are present as full `168`-row grids after replay.”
- Follow-up design decision recorded in docs: the current SQL chain should support both pre-`018` and post-`018` rooted dumps, with an opt-in compatibility verifier guarding that contract against regressions.
- The compatibility verifier now supports separate source/target Postgres endpoints so old rooted data can be read from one container and current-chain scratch verification DBs can be created on another.
- This confirms the rooted generated subset is compatible with the current migration chain in a way the previous `TEST/LAB1` template scaffolding was not.
- The remaining path caveat is tooling-only: host-side `psql -f sql/900-import-new-data.sql` from the repo root does not resolve CSV paths the same way as the normal bootstrap environment.

### 2026-03-10 rooted template editor alignment

- Reset the scoped runtime after the rooted subset changes and confirmed the live current DB now contains `4` template headers and `672` template cells.
- Confirmed the rooted production-shaped template issues on `device d`:
  - `i`: `20` stale member assignments and `51` unavailable group assignments
  - `j`: `16` stale member assignments and `63` unavailable group assignments
- Confirmed the unavailable groups in the rooted dataset are concrete and repairable in the current editor, not synthetic: `EEG`, `LCCG`, `NCR`, and `training`.
- Found an interface bug in the template editor:
  - the underlying template inputs were invalid on load, but the grid cells were not marked errored because cell error state was only mirrored when `changed && invalid`
  - result: the compatibility summary showed counts, but the grid did not show which cells needed repair
- Found a second interface mismatch:
  - template saves were blocked server-side by rooted invalid cells
  - the client-side save gate only checked `changedInvalid`, so it still let users attempt a save that the server would reject immediately
- Found a template-editor inspector bug:
  - selecting an errored template cell activated the cell, but the visible aside inspector stayed on its default placeholder copy
  - root cause: the JS was querying `.editor-inspector-detail-*` nodes while the template editor renders `.editor-inspector-*`
- Found a validation-layer mismatch behind the summary output:
  - template compatibility was treating “groups that have member datalists” as the full set of valid groups
  - rooted group-only reservations with no current members were therefore misclassified as invalid groups even when they were valid device-linked groups
- Current fix direction:
  - mark template cells errored whenever they are invalid, not only after user edits
  - block template save on any outstanding invalid cell so the editor matches server behavior
  - validate groups against the device-linked group set, while still allowing only `None` for memberless groups
  - expand compatibility summaries to name rooted stale or unavailable values, not just counts

### Tests to add or update after the interface patch

- Add a Playwright regression covering rooted template editor load for `device d / template i`:
  - stale `"[OLD]"` members and unavailable groups should be visibly marked as errored in-grid on initial load
- Add a Playwright regression covering template save gating:
  - with unresolved rooted invalid cells present, the client should block submit before the request is sent
- Add a Playwright regression covering template-cell inspection:
  - selecting a rooted invalid template cell should update the visible inspector target and error count, not leave the placeholder copy in place
- Add a route or unit regression covering compatibility summaries:
  - summary output should include the concrete unavailable groups and stale member values from rooted production-shaped data, not just counts
## 2026-03-10 rooted template follow-up

- Completed a live add/clone/archive pass against the rooted template data on `/device/d`.
- No new UI bug reproduced in those flows after the compatibility/editor fixes.
- Reproduced one apply-flow bug on `/device/d/templates`: helper buttons disabled repair-required templates, but typing `i` manually still opened the apply confirmation dialog before the server rejected it.
- Completed an end-to-end repair/save/apply pass by cloning `i`, repairing all blocking cells, saving it to a ready template, and applying it successfully.
- Added targeted Playwright regression coverage for:
  - rooted compatibility summary and initial in-grid error state on template editor load
  - visible inspector sync when selecting a rooted invalid cell
  - save gating when one cell is repaired but other rooted errors remain
  - clone plus archive flow preserving rooted repair-required summaries
  - blocking manual apply entry for repair-required templates before confirmation
  - full clone-repair-save-apply path for a production-shaped template
- Validated the new template apply and repair/apply regressions with:
  - `FMRIF_RUNTIME_SCOPE=tmpl-compat-20260310 pixi run test-integration-ci tests/playwright/integration/template-rooted-data.spec.ts --project=chromium`
  - result: `6 passed`
- Restored old template week semantics for apply start selection.
  - Root cause: template `dow` still represented literal weekdays, but the current apply route used the raw day after the latest scheduled date even when that fell midweek.
  - Fix: normalize template application to the next Sunday on or after the next unscheduled day, and surface that normalization in the apply page note.
  - Regression coverage: route test for midweek existing schedule data now asserts the apply page warns and the inserted schedule block starts on Sunday.
- Fixed stale multi-slot duration carryover when reopening the same slot after save.
  - Reproduction: save a 3-slot edit, close the results dialog, reopen the same slot, then make one more change. The inspector still carried `End time = ... (3 slots)` and the next edit silently targeted 3 slots again.
  - Fix: reset the inspector duration state after a fully successful save, not only when the next opened slot differs from the previous anchor.
  - Regression coverage: Playwright now covers reopening the same slot after save and expects the inspector to reset to `1 slot`.
