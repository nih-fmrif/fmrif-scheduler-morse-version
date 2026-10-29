# RBAC Implementation

## Summary

Authorization is database-backed and enforced on each request. Effective access
is computed from group membership, device-to-group links, and user-specific
device flags.

The RBAC surface is exposed as a single page:

- `GET /rbac` (admins and delegated PI roles): RBAC Explorer UI
- `GET /json/v1/rbac/explorer` (admins and delegated PI roles): scope/entity relationship payload
- `POST /json/v1/rbac/mutate` (admins and delegated PI roles + CSRF): atomic batch RBAC writes
- `GET /json/v1/rbac/audit` (admin only): RBAC audit timeline feed
- `GET /json/v1/email/audit` (admin only): email delivery + issue lifecycle feed
- `GET /app/issues` (admin only): Potential issues page (warnings + email audit)

## Enforcement Points

- Auth gate: `scheduler/app.py` -> `login_required()` (via `require_jwt()`)
- Active-user gate: `scheduler/app.py` -> `active_user_required()`
- Admin gate: `scheduler/app.py` -> `admin_only()`
- Admin role resolution: `scheduler/logic.py` -> `is_admin()`

## Data Model (RBAC Source of Truth)

- `membership` view (`scheduler/model.py` -> `Membership`)
  - effective membership read path: `group`, `user`, `approved`, `pi`,
    `group_active`, `user_active`, `email_status`
- `groupmembers` table (`GroupMember`)
  - membership writes (add/pending/approved/removal)
  - pending-request notification state (`email_status`: `none|sent|failed`)
- `primarygroupmember` table (`PrimaryGroupMember`)
  - PI assignment
- `devicegroup` table (`DeviceGroup`)
  - group <-> device links
- `userdevice` table (`UserDevice`)
  - per-user device flags (`templates`, `slot`, `tech`, `medical`, `training`)
- `technologist` table (`Technologist`)
  - request state (`applied_on`, nullable `approved_on`, `email_status`)
  - eligibility for technologist-specific permission flag when approved

## Effective Permission Logic

`scheduler/logic.py:get_dev_perms(user, device)` resolves device capability:

1. Inactive user: read-only.
2. Admin or DEV PI: full active-device capability (RBAC model behavior; not
   restricted to device-group links).
3. Otherwise:
   - edit access from approved membership in any group linked to the device.
   - extra capability from `userdevice` flags.

Important current behavior:

- Template capability is currently gated by `slot` (or admin/DEV-PI), not the
  `templates` flag (`DevicePerms.template`).

## RBAC Explorer (Current UX)

The `/rbac` page is entity-focused and progressively loaded.

- Scope selector: `group`, `device`, `user`
- Fuzzy combobox entity picker (type + keyboard/mouse choose in one control)
- Explorer control buttons for inline create flows:
  - `+ add group` (modal -> `group.create` batch operation)
  - `+ add device` (modal -> `device.create` batch operation)
- Relationship map:
  - sources -> selected entity -> targets
- Compact review-and-update matrices (inline checkboxes, linked/active rows first):
  - Group: transposed key/value settings matrix (includes active +
    membership-enabled/joinable read-only flags), membership state matrix,
    device-link matrix
  - Device: transposed key/value settings matrix (includes active), group-link
    matrix, DEV user permission matrix
    with `+ add DEV user` quick-add modal
  - User: transposed key/value settings matrix (active + read-only role flags),
    profile email + technologist request rows (applied/approved/email state),
    group membership matrix, device-specific permission matrix
- Batch writes are applied atomically per submit (`mode=batch`):
  - request carries changed row operations only
  - server validates all operations first
  - if any validation fails, no DB changes are committed
- Summary cards/links are intentionally removed/minimized so RBAC mutations stay
  in-page.

Delegated RBAC behavior:

- Group PI users for non-`DEV` groups are constrained to `group` scope for
  PI-managed active groups only.
- DEV PI users get delegated `device` scope over active devices (broad active-device scope)
  and can manage device links and DEV-user device flags.
- Group PI role for non-`DEV` groups does not expand into linked-device RBAC
  explorer scope.
- Non-admin delegated users cannot create groups/devices, cannot toggle
  active/inactive entity state, and cannot access audit feeds.
- RBAC UI does not render audit tabs/panels for non-admin delegated users.
- Non-admin delegated users can create pending membership requests, but cannot
  approve membership escalation from the RBAC matrix.
- Server-side batch authorization enforces these constraints atomically.

### Admin vs DEV PI (RBAC model split)

- Admin: user with approved active membership in `admin`.
- DEV PI: approved active PI assignment on group `DEV` (`Group PI of DEV`).
- DEV PI is not equivalent to admin.
- DEV PI capability is broad across active devices (not constrained by
  `devicegroup` links), but remains delegated/non-admin.
- Admin-only capabilities include:
  - create groups/devices
  - inactive-entity admin views/edit paths
  - active/inactive state toggles
  - RBAC/email audit feed access

### Role delineation (RBAC model)

- `PI`: a user assigned as PI for a specific group.
- `Group PI`: PI for a non-`DEV` group.
- `DEV PI`: PI for the `DEV` group (`Group PI of DEV` is the same role).
- Single-PI rule: each group has one PI at a time, including `DEV`.
- One user can be PI for multiple groups.
- A user can be a DEV member and PI of some other group while not being Group
  PI of `DEV` (DEV PI).
- A DEV member who is not Group PI of `DEV` may get schedule edit rights via
  group/device linkage, but does not get delegated PI management scope.
- Devices are not typed as DEV/non-DEV in this model; DEV PI active-device
  capability is global across active devices.

### Role-change flows

- PI assignment is group-scoped and replaces the previous PI for that group.
- For `DEV`, the same PI-assignment flow determines DEV PI.
- Group membership workflows are group-scoped; delegated Group PI manages those
  workflows for managed active groups.
- Device-management workflows remain admin/DEV-PI delegated actions.
- In general app UI, DEV PI should be presented as Group PI of `DEV`; the
  additional active-device capability is a behavior/capability distinction, not
  a separate user-facing role label.

### Test-only mock auth note

Route tests and Playwright mock-auth tests use a test-only session bootstrap
endpoint that now requires a scoped `session_key`.

- Mock users are resolved to session-scoped usernames/emails.
- For non-test authorization, PI authority remains database-backed.
- For scoped mock `DEV` PI sessions, PI authority is carried in session-local
  test state so parallel test sessions do not compete over the single
  `PrimaryGroupMember` row for `DEV`.

This is a test-isolation mechanism, not a production authorization design.

If that boundary starts to spread, treat it as ordinary cleanup work and keep
the production-versus-test distinction explicit in code review.

### UI Consolidation

Delegated-management flows live in `/rbac`; management paths are registered there.

## RBAC Audit Logging

All RBAC mutations route through `logic.log_rbac_audit_event(...)` with a stable
log-line format:

`RBAC_AUDIT action=... actor=... ip=... where=... when=... how=... what=...`

Origins are captured by `how`, including:

- `admin-ui`
- `rbac-explorer`
- `email` (join request and approval/denial flows)

### Persisted audit timeline and potential issues

RBAC events are also persisted in `rbac_audit_log` (created by
`sql/204-rbac-audit-log.sql` with `ip_addr` added in
`sql/205-rbac-audit-log-ip.sql`) and exposed via:

- `GET /json/v1/rbac/audit`
- `GET /rbac` (RBAC page audit module; admin-visible only)

Email events are persisted in `email_audit_log` (created by
`sql/207-email-audit-log.sql`) and exposed via:

- `GET /json/v1/email/audit`
- `GET /app/issues` (email audit section with status/issue-state/search filters,
  including resolved issue history lookup)

`GET /app/issues` also includes top-priority failed-notification issues for
pending group and technologist requests so admins can fix PI email + resend or
approve directly.

Timeline filtering:

- `scope=group&entity=<group_id>` -> events matching target group
- `scope=device&entity=<device_id>` -> events matching target device
- `scope=user&entity=<user_id>` -> events matching actor/target/requester user
- `scope=all` -> unfiltered global feed (entity ignored)

If the table is not present in a local database yet, the endpoint safely returns
an empty feed instead of failing the page.

## Notes for Tests

- Route contracts include:
  - `GET /json/v1/rbac/explorer` (admin + delegated PI scope fixtures; baseline mock-role matrix remains admin-only because PI role is fixture-driven)
  - `POST /json/v1/rbac/mutate` (admin + delegated PI scope-limited mutating + CSRF)
  - `GET /json/v1/rbac/audit` (admin only)
  - `GET /json/v1/email/audit` (admin only)
  - `GET /app/issues` (admin only)
- Seed writes for membership should target `groupmembers` and
  `primarygroupmember` (the `membership` view is read-only).
- `/join/tech` now auto-approves eligible DEV submissions and should be tested as immediate technologist approval (not pending queue creation).
