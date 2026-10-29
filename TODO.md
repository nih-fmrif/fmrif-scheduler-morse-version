# TODO

This file captures follow-up work that still looks relevant after the March
2026 documentation cleanup. It intentionally excludes closed upgrade-history
notes and stale planning documents.

## Code Structure

- Review whether `scheduler/logic/__init__.py` still needs broad wildcard
  re-exports, or whether more internal imports can move to direct module
  references.
- Continue decomposing the largest remaining logic and route modules when they
  become the next maintenance hotspot: `scheduler/routes/_rbac_explorer_core.py`,
  `scheduler/logic/_admin_config_operations.py`,
  `scheduler/logic/schedule_editor.py`,
  `scheduler/routes/rbac_mutation_apply.py`, and
  `scheduler/routes/rbac_mutation_validation.py`.
- Add clearer typed payload or row-shape helpers in the RBAC explorer and
  admin-config paths where broad dict-based structures still dominate.

## Testing

- Fix the pending Playwright contract in
  `tests/playwright/integration/device-ui-navigation.spec.ts`: lateral fallback
  day jumps should not mutate URL or history state.
- Add end-to-end coverage that `MAIL_SUPPRESS_SEND` prevents SMTP network
  activity; current coverage only verifies config mapping.
- Revisit worker-aware route isolation only if broader parallel route execution
  becomes necessary; do not widen xdist usage for routes without an explicit
  isolation design.
- Revisit further Playwright suite splitting only if
  `pixi run test-integration-ci` becomes a recurring bottleneck again.
