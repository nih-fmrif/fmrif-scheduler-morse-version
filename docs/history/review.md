# Static Review: `1596/fmrif-scheduler-morse-version` vs original `ade3/fmrif-scheduler-morse-version`

> Historical design or review notes. This records earlier work and may not
> describe the current application. Start with [the documentation index](../README.md).

## Scope

- Static analysis only.
- No application runtime, test, or compose stack execution.
- Current worktree was reset from `a6d070e` to `01b52cc` per request before review.

## Review Areas

### 1. Runtime, packaging, and deployment

- The current app is not a drop-in replacement for the original header-auth deployment model.
- Original auth was passive/request-header based (`HTTP_SM_USER`, `HTTP_USER_EMAIL`, `HTTP_NIH_DISPLAYNAME`) and therefore compatible with a SiteMinder-style reverse proxy.
- Current auth is explicit Entra/OIDC login plus session/bearer handling; there is no visible compatibility path for the old proxy-header login contract.
- Original operator tooling included `flask force-login <user>` plus `/force-login/<token>` and a `reset_tokens` table. Current codebase removed that path entirely and includes a migration that drops `reset_tokens`.

Notes:
- If the intended target environment is the new Entra deployment, this is an intentional platform migration, not necessarily a product regression.
- If the intended target is “same environment as the old app,” this is a major compatibility regression.

### 2. Data model and persistence

- No obvious loss of persisted business data concepts relative to the original schema surfaced from model comparison.
- Current `scheduler/model.py` is a superset of the original model surface: old core entities remain (`User`, `Group`, `Device`, `Template`, `TemplateEntry`, `ScheduleEntry`, `Membership`, `GroupMember`, `PrimaryGroupMember`, `Technologist`, `DeviceGroup`, `UserDevice`, `SchedLogEntry`) and new operational tables are additive.
- The repository contains explicit backward-compatibility work for bootstrapping old production-shaped data into the new chain.

Preliminary conclusion:
- Data compatibility appears intentionally preserved rather than regressed.

### 3. Scheduling and core business logic

- The scheduler route surface and logic look expanded rather than reduced: synthetic slot ids, explicit save error attribution, lazy row hydration, next-non-empty-day navigation, and richer notification/audit handling are all new.
- Template workflows also appear strictly richer, with compatibility inspection and validation gates that did not exist in the original app.
- One clear resilience regression exists: the current device page no longer server-renders schedule cells. It renders placeholder table cells and depends on client-side JS to hydrate rows from `/json/v1/device/<device>/schedule-rows`. The original page rendered the schedule grid and cells directly in HTML.

Notes:
- This is not necessarily a regression for JS-enabled browsers in the intended environment.
- It is a functional regression for no-JS / broken-JS / CSP-failure scenarios that the old app handled more gracefully.

### 4. Auth, authorization, and access control

- Auth and authorization are significantly more sophisticated now (OIDC, bearer support, RBAC, audit, auth-test scaffolding).
- Original join forms were explicitly NIH-network restricted via `@in_network_required`; the current join routes no longer enforce that restriction.
- This is a behavioral/security-model change, not a pure loss of functionality, but it means the current app is not behaviorally equivalent to the old access model.

### 5. Routes and functional surface area

- The current app removes a large set of original management routes instead of preserving them or redirecting them.
- Removed route families include:
  - `/groups`
  - `/groups/inactive`
  - `/groups/add`
  - `/group/<the_group>/edit`
  - `/group/<the_group>/membership`
  - `/group/<the_group>/pi`
  - `/devices`
  - `/devices/inactive`
  - `/device-add`
  - `/device/<the_device>/edit`
  - `/device/<the_device>/groups`
  - `/device/<the_device>/groups/add`
  - `/device/<the_device>/users`
  - `/device/<the_device>/users/<the_user>`
- Much of that functionality appears intentionally consolidated into `/rbac`, but URL/API compatibility is still lost and there are no obvious redirects from old paths.
- Concrete regression: inactive group detail pages used to remain viewable by admins on `/group/<the_group>`. The current `group()` handler hard-blocks inactive groups for everyone.

### 6. Notifications and external integrations

- Notification handling appears materially stronger than the original app: email audit logging, issue tracking, admin notification state, and app-error capture are additive.
- One workflow-level notification loss was visible in the technologist self-service path on initial review:
  - Original `/join/tech` auto-approved the user and then notified the DEV PI.
  - Current `/join/tech` auto-approves the user and notifies the requester of the outcome, but does not notify the DEV PI on the normal success path.
- Patched during review:
  - added a DEV PI informational email for the `/join/tech` auto-approval path, distinct from the existing pending-request email that includes approve/deny links.

Preliminary conclusion:
- General notification infrastructure is improved.
- After the patch above, no remaining notification functionality loss stands out from static comparison.

### 7. Operational safeguards and test coverage

- The current repository is substantially stronger operationally than the original one: route-contract tests, unit/integration/playwright/load coverage, migration tooling, compose/runtime scripts, and compatibility documentation are all new.
- The repo also contains explicit documentation and tests intended to preserve compatibility with old seeded data.

Preliminary conclusion:
- Operational maturity is improved, not regressed.

## Working Notes

- Original app is a comparatively small Flask application centered on scheduling, devices, groups, templates, mailing lists, and join flows.
- Current app is a major expansion with modularized logic, auth/RBAC, migrations, tests, docs, runtime scripts, and deployment assets.
- Review objective is to identify regressions or functionality losses relative to the original app, not to enumerate net-new capabilities unless they affect compatibility or preservation.
- The strongest regressions found so far are:
  - old deployment/auth compatibility loss (SiteMinder/header auth + force-login path removed)
  - route compatibility loss for many group/device management URLs
  - inactive group detail access regression for admins
  - heavier client-side dependence on JS for core schedule rendering

## Review Follow-Up Notes

- Added a minimal `<noscript>` read-only summary to the device page so CSP or JS failures no longer strand the user on a fully placeholder-backed schedule grid.
- Added a local nginx reverse proxy to the full compose stack so proxy header and CSP behavior can be exercised closer to deployment topology.
- Created `docs/history/csp-policy-improvements.md` to track the remaining work needed for proxy-aware CSP verification and future policy tightening.
- Updated the local serving split so host mode remains Werkzeug-first for low-friction development while the full compose stack runs nginx in front of Gunicorn for better deployment parity.
- Added `docs/deployment-considerations.md` to capture proxy/port/Gunicorn/CSP details that matter during deployment work but should not clutter the environment-specific runbook.
- Replaced the temporary container-only `pip install gunicorn` workaround with a Pixi-managed app image, then simplified it again so Docker now resolves from the shared repository `pixi.toml` under `linux/amd64` emulation, narrowing the copied in-image manifest to `linux-64` instead of depending on the checked-in lockfile.
