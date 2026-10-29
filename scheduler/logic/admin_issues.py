from __future__ import annotations

import datetime
import hashlib
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError

from scheduler import model

from . import rbac_audit_support as audit_logic

LIVE_ISSUE_TYPE_PREFIX = "live."
NOTIFICATION_ISSUE_STATE_OPEN = "open"
NOTIFICATION_ISSUE_STATE_IGNORED = "ignored"
NOTIFICATION_ISSUE_STATE_RESOLVED = "resolved"


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def live_issue_type(value: str) -> str:
    token = (value or "").strip()
    if token.startswith(LIVE_ISSUE_TYPE_PREFIX):
        return token
    return f"{LIVE_ISSUE_TYPE_PREFIX}{token}"


def live_issue_fingerprint(*parts: object) -> str:
    normalized = [str(part or "").strip() for part in parts]
    return hashlib.sha256("|".join(normalized).encode("utf-8")).hexdigest()


def scheduler_save_failure_issue_key(device_id: str, fingerprint: str) -> str:
    return (
        f"scheduler-save-db:{(device_id or '').strip()}:{(fingerprint or '').strip()}"
    )


def scheduler_notification_issue_key(device_id: str, stream: str, kind: str) -> str:
    return (
        f"scheduler-notification:{(kind or '').strip()}:"
        f"{(device_id or '').strip()}:{(stream or '').strip()}"
    )


def _scheduler_save_diag(err: SQLAlchemyError) -> tuple[str, str, str, str]:
    orig = getattr(err, "orig", None)
    diag = getattr(orig, "diag", None)
    sqlstate = str(
        getattr(orig, "pgcode", None) or getattr(diag, "sqlstate", None) or ""
    ).strip()
    constraint = str(getattr(diag, "constraint_name", None) or "").strip()
    primary = str(getattr(diag, "message_primary", None) or "").strip()
    detail = str(getattr(diag, "message_detail", None) or "").strip()
    if not (primary or detail):
        primary = str(orig or err).splitlines()[0].strip()
    return sqlstate, constraint, primary, detail


def scheduler_save_failure_fingerprint(err: SQLAlchemyError) -> str:
    sqlstate, constraint, primary, detail = _scheduler_save_diag(err)
    return live_issue_fingerprint(
        "scheduler-save-db",
        sqlstate,
        constraint,
        primary,
        detail,
    )[:20]


def upsert_scheduler_save_failure_issue(
    err: SQLAlchemyError,
    *,
    actor: str,
    device_id: str,
    device_label: str,
    source: str,
    code: str,
    client_message: str,
    href: str,
    link_label: str = "open schedule",
) -> Optional[str]:
    sqlstate, constraint, primary, detail = _scheduler_save_diag(err)
    fingerprint = scheduler_save_failure_fingerprint(err)
    detail_lines = [
        f"Scheduler save for device {device_label or device_id} hit an unmapped database rejection path.",
        f"Client-safe response: {client_message}",
        f"Policy source/code: {source}/{code}",
    ]
    if sqlstate:
        detail_lines.append(f"SQLSTATE: {sqlstate}")
    if constraint:
        detail_lines.append(f"Constraint: {constraint}")
    if primary:
        detail_lines.append(f"Primary: {primary}")
    if detail:
        detail_lines.append(f"Detail: {detail}")
    return upsert_live_issue(
        issue_key=scheduler_save_failure_issue_key(device_id, fingerprint),
        issue_type="scheduler.db_error",
        category="scheduler persistence",
        severity="critical",
        title="Scheduler save hit an unmapped database rejection",
        detail=" ".join(detail_lines),
        href=href,
        link_label=link_label,
        fingerprint=fingerprint,
        actor=actor,
    )


def upsert_scheduler_notification_issue(
    *,
    actor: str,
    device_id: str,
    device_label: str,
    stream: str,
    kind: str,
    href: str,
    link_label: str = "open schedule",
) -> Optional[str]:
    stream_label = {
        "schedule": "Schedule",
        "training": "Training support",
        "medical": "Medical support",
        "technologist": "Technologist support",
    }.get(stream, stream.replace("_", " ").title())
    kind_token = (kind or "").strip()
    if kind_token == "missing_recipient":
        return upsert_live_issue(
            issue_key=scheduler_notification_issue_key(device_id, stream, kind_token),
            issue_type="scheduler.notification_missing_recipient",
            category="notifications",
            severity="warning",
            title=f"{stream_label} notification has no configured recipient",
            detail=(
                f"The {stream_label.lower()} notification for device "
                f"{device_label or device_id} could not be sent because no "
                "recipient address is configured."
            ),
            href=href,
            link_label=link_label,
            fingerprint=live_issue_fingerprint(device_id, stream, kind_token)[:20],
            actor=actor,
        )
    if kind_token == "delivery_failed":
        return upsert_live_issue(
            issue_key=scheduler_notification_issue_key(device_id, stream, kind_token),
            issue_type="scheduler.notification_delivery_failed",
            category="notifications",
            severity="critical",
            title=f"{stream_label} notification failed to send",
            detail=(
                f"The {stream_label.lower()} notification for device "
                f"{device_label or device_id} failed to send. Review the "
                "mail configuration, SMTP path, and recent email audit entries."
            ),
            href=href,
            link_label=link_label,
            fingerprint=live_issue_fingerprint(device_id, stream, kind_token)[:20],
            actor=actor,
        )
    raise ValueError(f"unsupported scheduler notification issue kind: {kind}")


def resolve_scheduler_notification_issues(
    *,
    actor: str,
    device_id: str,
    stream: str,
) -> int:
    return resolve_live_issues(
        [
            scheduler_notification_issue_key(device_id, stream, "missing_recipient"),
            scheduler_notification_issue_key(device_id, stream, "delivery_failed"),
        ],
        actor=actor,
        note="Resolved automatically after a notification for this stream succeeded.",
    )


def _upsert_live_issue_row(
    *,
    issue_key: str,
    issue_type: str,
    category: str,
    severity: str,
    title: str,
    detail: str,
    href: str = "",
    link_label: str = "",
    fingerprint: str = "",
    actor: str = "system",
) -> Optional[model.NotificationIncident]:
    if not audit_logic.notification_incident_table_available():
        return None

    issue_token = (issue_key or "").strip()
    if issue_token == "":
        raise ValueError("issue_key is required")

    now = _now()
    actor_token = (actor or "").strip() or "system"
    row = model.db.session.get(model.NotificationIncident, issue_token)

    if row is None:
        row = model.NotificationIncident(
            issue_key=issue_token,
            issue_type=live_issue_type(issue_type),
            category=(category or "").strip() or "operations",
            severity=(severity or "").strip().lower() or "warning",
            title=(title or "").strip() or "Operational issue",
            detail=(detail or "").strip() or "No detail provided.",
            href=(href or "").strip() or None,
            link_label=(link_label or "").strip() or "",
            active=True,
            state=NOTIFICATION_ISSUE_STATE_OPEN,
            state_note="Raised automatically by a live application workflow.",
            state_changed_by=actor_token,
            state_changed_at=now,
            ignored_until=None,
            first_seen_at=now,
            last_seen_at=now,
            last_detected_at=now,
            last_resolved_at=None,
            occurrence_count=1,
            fingerprint=(fingerprint or "").strip(),
        )
        model.db.session.add(row)
        return row

    ignore_expired = (
        row.state == NOTIFICATION_ISSUE_STATE_IGNORED
        and row.ignored_until is not None
        and row.ignored_until <= now
    )

    row.issue_type = live_issue_type(issue_type)
    row.category = (category or "").strip() or row.category
    row.severity = (severity or "").strip().lower() or row.severity
    row.title = (title or "").strip() or row.title
    row.detail = (detail or "").strip() or row.detail
    row.href = (href or "").strip() or None
    row.link_label = (link_label or "").strip() or ""
    row.fingerprint = (fingerprint or "").strip()
    row.last_seen_at = now
    row.last_detected_at = now
    row.occurrence_count = max(1, int(row.occurrence_count or 1)) + 1

    if not bool(row.active):
        row.active = True
        row.state = NOTIFICATION_ISSUE_STATE_OPEN
        row.state_note = "Reopened automatically after the issue recurred."
        row.state_changed_by = actor_token
        row.state_changed_at = now
        row.ignored_until = None
        row.last_resolved_at = None
    elif row.state == NOTIFICATION_ISSUE_STATE_RESOLVED:
        row.active = True
        row.state = NOTIFICATION_ISSUE_STATE_OPEN
        row.state_note = "Reopened automatically after the issue recurred."
        row.state_changed_by = actor_token
        row.state_changed_at = now
        row.ignored_until = None
        row.last_resolved_at = None
    elif ignore_expired:
        row.active = True
        row.state = NOTIFICATION_ISSUE_STATE_OPEN
        row.state_note = (
            "Ignore expired; reopened automatically after the issue recurred."
        )
        row.state_changed_by = actor_token
        row.state_changed_at = now
        row.ignored_until = None
        row.last_resolved_at = None
    else:
        row.active = True

    model.db.session.add(row)
    return row


def upsert_live_issue(**kwargs) -> Optional[str]:
    row = _upsert_live_issue_row(**kwargs)
    if row is None:
        return None
    return row.issue_key


def resolve_live_issue(
    issue_key: str,
    *,
    actor: str = "system",
    note: str = "Resolved automatically by a later successful operation.",
) -> bool:
    if not audit_logic.notification_incident_table_available():
        return False

    issue_token = (issue_key or "").strip()
    if issue_token == "":
        return False

    row = model.db.session.get(model.NotificationIncident, issue_token)
    if row is None:
        return False

    now = _now()
    row.active = False
    row.state = NOTIFICATION_ISSUE_STATE_RESOLVED
    row.state_note = (note or "").strip() or "Resolved automatically."
    row.state_changed_by = (actor or "").strip() or "system"
    row.state_changed_at = now
    row.ignored_until = None
    row.last_seen_at = now
    row.last_resolved_at = now
    model.db.session.add(row)
    return True


def resolve_live_issues(
    issue_keys: list[str],
    *,
    actor: str = "system",
    note: str = "Resolved automatically by a later successful operation.",
) -> int:
    resolved = 0
    for issue_key in issue_keys:
        if resolve_live_issue(issue_key, actor=actor, note=note):
            resolved += 1
    return resolved


__all__ = [
    "LIVE_ISSUE_TYPE_PREFIX",
    "live_issue_fingerprint",
    "live_issue_type",
    "resolve_live_issue",
    "resolve_live_issues",
    "resolve_scheduler_notification_issues",
    "scheduler_notification_issue_key",
    "scheduler_save_failure_fingerprint",
    "scheduler_save_failure_issue_key",
    "upsert_scheduler_notification_issue",
    "upsert_scheduler_save_failure_issue",
    "upsert_live_issue",
]
