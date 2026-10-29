# SQLAlchemy Upgrade Progress

Date started: 2026-03-20
Runtime scope: `codex-sa20-compat-20260319`

## Goal

Align local development with Debian 13 package expectations directly, modernize the SQLAlchemy usage substantially, and simplify the test harness around the modern Flask / Flask-SQLAlchemy / SQLAlchemy baseline.

## Durable Context

- Code commit already landed for explicit `Mapped[...]` model annotations:
  - `60c9196` `Adopt explicit SQLAlchemy mapped annotations`
- Review document with the starting assessment:
  - `docs/sqlalchemy-upgrade-review.md`
- Technical rationale for dropping Debian 12 compatibility as an active constraint:
  - `docs/debian-12-support-technical-debt.md`

## Intended Target

- Local dev and upgrade work should target Debian 13 package versions directly:
  - Flask 3.1.x
  - Flask-SQLAlchemy 3.1.x
  - SQLAlchemy 2.0.x
  - Werkzeug 3.1.x

## Planned Workstreams

1. Update dependency pins and any environment/bootstrap assumptions.
2. Simplify the test harness around one modern Flask-SQLAlchemy 3 / SQLAlchemy 2 model.
3. Replace high-value legacy SQLAlchemy usage with modern patterns.
4. Keep the review and this progress file updated across sizeable commits.

## Progress Log

### Completed

- Added explicit `Mapped[...]` model annotations and removed `__allow_unmapped__`.
- Added a regression test to keep mapped annotations explicit.
- Wrote the initial upgrade review.
- Created this progress log.
- Confirmed the live Pixi environment had already drifted from both `pyproject.toml` and Debian:
  - Flask-SQLAlchemy `2.5.1` was still paired with SQLAlchemy `2.0.43`
  - this reinforces the need to make the declared stack explicit and coherent
- Landed the first dependency-alignment changeset locally:
  - `pyproject.toml` now pins Flask `3.1.1`, Flask-SQLAlchemy `3.1.1`, SQLAlchemy `2.0.40`, Werkzeug `3.1.3`
  - session-related pins were moved toward the Debian 13 package line as well
  - Flask 3 import cleanup removed submodule imports and the obsolete `FLASK_ENV` assignment
  - the unit-test transaction fixture now has a compatibility path that does not depend on `db.create_scoped_session()`
- Synced the Pixi environment to the new declared stack and confirmed the runtime now matches:
  - Flask `3.1.1`
  - Flask-SQLAlchemy `3.1.1`
  - SQLAlchemy `2.0.40`
  - Werkzeug `3.1.3`
  - Flask-Session `0.8.0`
  - Flask-Mail `0.9.1`
- Adjusted the mapped-annotation regression test so it still resolves inherited Flask-SQLAlchemy 3.x base-model annotations.
- Validation for this changeset:
  - `pixi run test-unit -- tests/unit/test_sqlalchemy_model_annotations.py -q tests/unit/test_message.py -q`
  - `pixi run test-routes -- tests/unit/test_device_permission_matrix.py -q`
  - `pixi run pre-commit`
- Completed the second compatibility pass around test/runtime behavior on the upgraded stack:
  - non-route unit tests now reset to a fresh ORM-created database instead of relying on the previous transactional isolation wrapper
  - route tests now refresh the seeded database per test from the SQL-bootstrap template clone, which keeps route behavior aligned with real schema/bootstrap state under Flask-SQLAlchemy 3.x and SQLAlchemy 2.x
  - the old transaction-bound session helper path was removed from `tests/unit/conftest.py` once the per-test database refresh approach proved stable
  - OAuth login now constructs the `next` redirect query explicitly before rendering the login form, which preserves safe relative targets with the expected URL encoding under the newer stack
- Validation for the second pass:
  - `pixi run test-unit -- tests/unit/test_app_error_events.py -q tests/unit/test_csp_violation_events.py -q tests/unit/test_db_isolation.py -q`
  - `pixi run test-unit`
  - `pixi run test-routes -- tests/unit/test_auth_login_route.py -q tests/unit/test_route_db_isolation.py -q tests/unit/test_app_error_capture_routes.py -q tests/unit/test_csp_report_routes.py -q tests/unit/test_auth_session_endpoint.py -q tests/unit/test_auth_test_session_endpoint.py -q`
  - `pixi run test-routes`
- Modernized the auth/session access layer away from the legacy `Query` API in the highest-value places:
  - `scheduler/auth/authorization.py` now loads users by email with `select(...)`
  - `scheduler/auth/session.py` now uses `select(...)` for existing-user and primary-membership lookups
  - `scheduler/auth/session.py` now uses ORM `delete(...)` statements instead of raw SQL / `Query.delete(...)` in the auth-test cleanup path
  - `scheduler/auth/views.py` now consumes OAuth state with an explicit `select(...)` statement
- Validation for the auth/session modernization pass:
  - `pixi run test-unit -- tests/unit/test_auth.py -q tests/unit/test_bearer_auto_provisioning.py -q tests/unit/test_oauth_views_pkce.py -q`
  - `pixi run test-routes -- tests/unit/test_auth_login_route.py -q tests/unit/test_auth_session_endpoint.py -q`
- Modernized additional read-heavy logic helpers to SQLAlchemy 2-style statement execution:
  - `scheduler/logic/app_error_events.py` now builds listing queries with `select(...)`
  - `scheduler/logic/csp_violation_events.py` now loads event rows with `select(...)`
  - `scheduler/logic/schedule_editor.py` now uses `select(...)` / `session.execute(...)` for schedule lookups and existence checks
- Validation for the logic-helper modernization pass:
  - `pixi run test-unit -- tests/unit/test_app_error_events.py -q tests/unit/test_csp_violation_events.py -q`
  - `pixi run test-routes -- tests/unit/test_app_error_capture_routes.py -q tests/unit/test_csp_report_routes.py -q tests/unit/test_schedule_next_day.py -q tests/unit/test_schedule_editor.py -q`
- Added the Debian 12 debt rationale and changed the upgrade direction to target Debian 13 directly.
- Replaced the per-test route database clone bridge with a modern transaction-isolation harness:
  - route tests now SQL-bootstrap once per suite instead of cloning a template database per test
  - unit tests now ORM-bootstrap once per suite instead of rebuilding schema per test
  - both suites now isolate tests by rebinding Flask-SQLAlchemy 3.x to one connection / one outer transaction for the active app context
  - the modern fixture depends on Flask-SQLAlchemy 3.x behavior directly, including rebinding through `db.engines[None]`
- Current status of the isolation decision:
  - targeted route tests successfully returned to transaction isolation on the Debian 13 baseline
  - no currently-validated route slice requires the old database-clone fallback
  - if a future test subset proves to need heavier isolation, that reason should be documented explicitly before reintroducing it
- Validation for the transaction-isolation restoration pass:
  - `pixi run test-unit -- tests/unit/test_db_isolation.py -q`
  - `pixi run test-routes -- tests/unit/test_route_db_isolation.py -q`
  - `pixi run test-routes -- tests/unit/test_auth_login_route.py -q tests/unit/test_app_error_capture_routes.py -q tests/unit/test_form_mutating_routes.py -q`
- Broadened confidence in the restored route transaction fixture:
  - RBAC route pages and issue-scan flows passed cleanly on the modern transaction model
  - this is the first stronger signal that the route-test clone fallback is no longer needed on the Debian 13 baseline
- Modernized the RBAC issue/history path and route seed helpers toward SQLAlchemy 2 APIs:
  - `scheduler/routes/rbac_issues.py` now uses `select(...)`, `session.execute(...)`, and ORM `delete(...)` instead of legacy `Query` APIs
  - `tests/unit/route_seed.py` now uses modern statement execution for scanner/user lookups and PI reassignment cleanup
- Validation for the RBAC issue/history modernization pass:
  - `pixi run test-routes -- tests/unit/rbac_page/test_rbac_page_part_01.py -q tests/unit/rbac_page/test_rbac_page_part_04.py -q tests/unit/rbac_page/test_rbac_page_part_08.py -q`
  - `pixi run test-routes -- tests/unit/rbac_page/test_rbac_page_part_01.py -q tests/unit/rbac_page/test_rbac_page_part_04.py -q tests/unit/rbac_page/test_rbac_page_part_08.py -q tests/unit/rbac_page/test_rbac_page_part_09.py -q`
- Removed the remaining legacy ORM `Query` API usage across the Python application and unit/route tests:
  - `scheduler/routes/_rbac_explorer_core.py` now uses `select(...)` / `session.execute(...)` throughout the explorer read model
  - `scheduler/app.py`, `scheduler/logic/core.py`, `scheduler/logic/templates.py`, `scheduler/logic/admin_config.py`, `scheduler/logic/notifications.py`, `scheduler/routes/rbac_mutation_apply.py`, and `scheduler/routes/rbac_mutation_validation.py` were converted to SQLAlchemy 2-style statements
  - unit and route tests were updated to assert through `select(...)`, `session.scalars(...)`, `session.scalar(...)`, and `scalar_one[_or_none]()` rather than `.query`
  - repository-wide Python search for `session.query`, `.query`, `with_entities`, and `Query` now only hits URL query-string parsing, not ORM access
- Fixed the first SQLAlchemy-2-only regression that surfaced after the purge:
  - `ScheduleEntry` reads now call `unique()` before `scalars()` when joined eager-loading `requests`, which avoids the ORM duplicate-row error on the modern stack
- Validation for this modernization/stabilization pass:
  - `pixi run test-unit -- tests/unit/test_sqlalchemy_model_annotations.py -q`
  - `pixi run test-routes -- tests/unit/test_schedule_rows_security.py -q tests/unit/test_schedule_editor.py -q tests/unit/test_device_mutating_routes.py -q tests/unit/test_device_notification_routes.py -q`
- Finished the broader post-purge stabilization pass on the Debian 13 baseline:
  - `scheduler/auth/session.py` now follows Flask-Session `0.8.0`'s modern regeneration contract instead of calling the old private `_generate_sid()` shape directly
  - `_store_session()` now writes the authenticated session payload before rotating the server-side session identifier, which lets `session_interface.regenerate(session)` work cleanly on the modern stack
  - the remaining request-cache test that still patched ORM `.query` now patches `db.session.scalar(...)`, keeping the final route assertions aligned with the SQLAlchemy 2 codepath
- Removed a remaining older-stack config relic:
  - `SESSION__USE_SIGNER` / `SESSION_USE_SIGNER` was dropped from settings, app config, tests, and docs because Flask-Session `0.8.0` treats it as deprecated and the SQLAlchemy-backed server-side sessions do not need the legacy signer flag
- Removed the remaining repo-local `model.get(...)` wrapper usage from application code:
  - `scheduler/auth/session.py`, `scheduler/app.py`, `scheduler/logic/core.py`, `scheduler/logic/schedule_editor.py`, `scheduler/logic/templates.py`, `scheduler/logic/notifications.py`, `scheduler/logic/admin_config.py`, `scheduler/routes/_rbac_explorer_core.py`, `scheduler/routes/rbac_issues.py`, `scheduler/routes/rbac_mutation_apply.py`, and `scheduler/routes/rbac_mutation_validation.py` now call `model.db.session.get(...)` directly
  - application code no longer depends on the local identity-load helper, which makes the SQLAlchemy 2 session surface more explicit and reduces one more legacy abstraction layer
- Finished the `model.get(...)` purge across the repository:
  - unit and route tests now use `model.db.session.get(...)` directly as well
  - the `model.get(...)` helper itself was removed from `scheduler/model.py`
  - repository-wide search for `model.get(` is now clean outside this progress log
  - one stale session-hardening test monkeypatch was updated to patch `model.db.session.get(...)` directly, matching the modern codepath
- Removed the remaining repo-local `model.execute(...)` wrapper across app code and tests:
  - raw SQL call sites now use explicit `model.db.session.execute(...)`
  - truly SQL-shaped statements now declare `text(...)` directly instead of relying on hidden string coercion
  - `scheduler/model.py` no longer exposes a local execute shim
  - `scheduler/logic/core.py` and `scheduler/logic/notifications.py` also picked up a few direct SQLAlchemy 2 statement rewrites while touching the same surface
- Tightened the session-rotation helper to the modern Flask-Session contract only:
  - `scheduler/auth/session.py` no longer falls back to the private `_generate_sid()` path
  - session fixation hardening now depends on `session_interface.regenerate(session)` as the Debian 13 baseline API
- Validation for the execute-wrapper purge and modern-session cleanup:
  - `pixi run test-unit -- tests/unit/test_session_hardening.py -q tests/unit/test_admin_config.py -q tests/unit/test_template_validation.py -q`
  - `pixi run test-routes -- tests/unit/test_seed_shape_contract.py -q tests/unit/test_schedule_editor.py -q tests/unit/test_device_mutating_routes.py -q tests/unit/test_device_notification_routes.py -q tests/unit/test_form_mutating_routes.py -q tests/unit/test_auth_test_session_endpoint.py -q tests/unit/test_home_navigation.py -q tests/unit/rbac_page/test_rbac_page_part_09.py -q tests/unit/rbac_page/test_rbac_page_part_10.py -q`
  - `pixi run test-unit`
  - `pixi run test-routes`
  - `pixi run test-integration-ci`
  - `pixi run pre-commit`
- Validation for the repository-wide `model.get(...)` purge:
  - `pixi run test-unit`
  - `pixi run test-routes`
  - `pixi run test-integration-ci`
- Validation for the final stabilization pass:
  - `pixi run test-unit -- tests/unit/test_session_hardening.py -q tests/unit/test_auth.py -q`
  - `pixi run test-routes -- tests/unit/test_auth_login_route.py -q tests/unit/test_auth_session_endpoint.py -q tests/unit/test_auth_test_session_endpoint.py -q`
  - `pixi run test-unit`
  - `pixi run test-routes`
  - `pixi run test-integration-ci`
- Current end-state for this upgrade slice:
  - full unit suite is green: `160 passed, 1 skipped, 442 deselected`
  - full route suite is green: `442 passed, 161 deselected`
  - Debian 13 integration suite is green: `234 passed, 12 skipped`
  - repository-wide Python search for legacy ORM `Query` usage remains clean aside from URL query-string parsing

### In Progress

- No active blocker in this pass.

### Next

- If more modernization is desired, treat it as follow-on cleanup rather than stack-enablement work:
  - optional refactors to shrink remaining ORM helper complexity
  - optional Playwright test-splitting for the slowest `device-ui-interactions` / schedule-contract files

## Notes For Future Continuations

- Keep this file current before or after each sizeable commit.
- Prefer multiple trajectory commits over one large end-state commit.
- Do not rotate the runtime scope unless intentionally starting a separate isolated run.
