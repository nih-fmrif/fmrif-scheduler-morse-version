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
- `GET /app/issues` (admin only): Potential issues page (warnings + RBAC/email audit)

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
2. Admin or DEV PI: full device capability.
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

- Group PI users get constrained `group` scope for PI-managed active groups.
- DEV PI users get constrained `device` scope and can manage device links and
  DEV-user device flags.
- Non-admin delegated users cannot create groups/devices, cannot toggle
  active/inactive entity state, and cannot access audit feeds.
- Non-admin delegated users can create pending membership requests, but cannot
  approve membership escalation from the RBAC matrix.
- Server-side batch authorization enforces these constraints atomically.

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
- `GET /app/issues` (global page with potential-issue warnings and full RBAC log)
  - includes top-priority failed-notification issues for pending group and
    technologist requests so admins can fix PI email + resend or approve directly

Email events are persisted in `email_audit_log` (created by
`sql/207-email-audit-log.sql`) and exposed via:

- `GET /json/v1/email/audit`
- `GET /app/issues` (email audit section with status/issue-state/search filters,
  including resolved issue history lookup)

Timeline filtering:

- `scope=group&entity=<group_id>` -> events matching target group
- `scope=device&entity=<device_id>` -> events matching target device
- `scope=user&entity=<user_id>` -> events matching actor/target/requester user
- `scope=all` -> unfiltered global feed (entity ignored)

If the table is not present in a local database yet, the endpoint safely returns
an empty feed instead of failing the page.

## Notes for Tests

- Route contracts include:
  - `GET /json/v1/rbac/explorer` (admin only)
  - `POST /json/v1/rbac/mutate` (admin only mutating + CSRF)
  - `GET /json/v1/rbac/audit` (admin only)
  - `GET /json/v1/email/audit` (admin only)
  - `GET /app/issues` (admin only)
- Seed writes for membership should target `groupmembers` and
  `primarygroupmember` (the `membership` view is read-only).
