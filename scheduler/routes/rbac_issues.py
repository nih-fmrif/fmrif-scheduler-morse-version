from __future__ import annotations

import datetime
import hashlib
from typing import Any, Dict, List, Optional

from flask import url_for
from sqlalchemy import or_
from sqlalchemy.orm import load_only
from sqlalchemy.sql import func

from scheduler import logic, model

NOTIFICATION_INCIDENT_STATE_OPEN = "open"
NOTIFICATION_INCIDENT_STATE_IGNORED = "ignored"
NOTIFICATION_INCIDENT_STATE_RESOLVED = "resolved"
NOTIFICATION_INCIDENT_STATE_VALUES = (
    NOTIFICATION_INCIDENT_STATE_OPEN,
    NOTIFICATION_INCIDENT_STATE_IGNORED,
    NOTIFICATION_INCIDENT_STATE_RESOLVED,
)
NOTIFICATION_INCIDENT_RETENTION_DAYS = 365 * 5

NOTIFICATION_INCIDENT_SEARCH_FIELD_LABELS: Dict[str, str] = {
    "all": "all fields",
    "title": "title",
    "detail": "detail",
    "issue_key": "issue key",
    "category": "category",
}


def _user_map(user_ids: List[str]) -> Dict[str, model.User]:
    unique_user_ids = sorted(
        {(user_id or "").strip() for user_id in user_ids if user_id}
    )
    if len(unique_user_ids) == 0:
        return {}

    rows = (
        model.User.query.options(
            load_only(model.User.id, model.User.active, model.User.addr)
        )
        .filter(model.User.id.in_(unique_user_ids))
        .all()
    )
    return {row.id: row for row in rows}


def _append_issue(
    issues: List[Dict[str, str]],
    *,
    issue_key: str,
    issue_type: str,
    severity: str,
    category: str,
    title: str,
    detail: str,
    href: str,
    link_label: str,
) -> None:
    issues.append(
        {
            "issue_key": issue_key,
            "issue_type": issue_type,
            "severity": severity,
            "category": category,
            "title": title,
            "detail": detail,
            "href": href,
            "link_label": link_label,
        }
    )


def _build_potential_issues() -> List[Dict[str, str]]:
    issues: List[Dict[str, str]] = []

    if not logic.rbac_audit_table_available():
        _append_issue(
            issues,
            issue_key="infra-rbac-audit-unavailable",
            issue_type="infra-rbac-audit-unavailable",
            severity="warning",
            category="logging",
            title="RBAC audit persistence is unavailable",
            detail=(
                "The rbac_audit_log table is missing or inaccessible. "
                "RBAC events can still execute, but timeline history will be empty."
            ),
            href=url_for("rbac"),
            link_label="open RBAC explorer",
        )

    failed_group_notifications = (
        model.GroupMember.query.filter(model.GroupMember.approved.is_(None))
        .filter(model.GroupMember.email_status == logic.EMAIL_STATUS_FAILED)
        .order_by(model.GroupMember.group, model.GroupMember.user)
        .all()
    )
    for row in failed_group_notifications:
        _append_issue(
            issues,
            issue_key=f"join-group:{row.group}:{row.user}",
            issue_type="join-group-notification-failed",
            severity="critical",
            category="top priority",
            title="Join request notification failed",
            detail=(
                f"Pending join request for user {row.user} in group {row.group} "
                "was not emailed to a PI. Update the PI email address in RBAC and "
                "set the request email state to sent, or approve directly."
            ),
            href=url_for("rbac", scope="group", entity=row.group),
            link_label="open group in RBAC explorer",
        )

    failed_tech_notifications = (
        model.Technologist.query.filter(model.Technologist.approved_on.is_(None))
        .filter(model.Technologist.email_status == logic.EMAIL_STATUS_FAILED)
        .order_by(model.Technologist.user)
        .all()
    )
    for row in failed_tech_notifications:
        _append_issue(
            issues,
            issue_key=f"join-tech:DEV:{row.user}",
            issue_type="join-tech-notification-failed",
            severity="critical",
            category="top priority",
            title="Technologist request notification failed",
            detail=(
                f"Pending technologist request for user {row.user} could not be "
                "emailed to a DEV PI. Update the DEV PI email in RBAC and resend, "
                "or approve directly."
            ),
            href=url_for("rbac", scope="user", entity=row.user),
            link_label="open user in RBAC explorer",
        )

    joinable_groups = (
        model.Group.query.filter(model.Group.active)
        .filter(model.Group.has_membership)
        .filter(model.Group.is_joinable)
        .order_by(model.Group.label, model.Group.id)
        .all()
    )

    pi_memberships = (
        model.Membership.query.filter(model.Membership.pi)
        .filter(model.Membership.approved)
        .filter(model.Membership.group_active)
        .filter(model.Membership.user_active)
        .all()
    )
    pi_by_group: Dict[str, List[str]] = {}
    for row in pi_memberships:
        pi_by_group.setdefault(row.group, []).append(row.user)
    pi_user_map = _user_map(
        [user_id for user_ids in pi_by_group.values() for user_id in user_ids]
    )

    pending_counts_rows = (
        model.db.session.query(
            model.GroupMember.group,
            func.count(model.GroupMember.user),
        )
        .filter(model.GroupMember.approved.is_(None))
        .group_by(model.GroupMember.group)
        .all()
    )
    pending_counts = {group_id: int(count) for group_id, count in pending_counts_rows}

    for group in joinable_groups:
        pi_ids = sorted(set(pi_by_group.get(group.id, [])))
        group_membership_url = url_for("rbac", scope="group", entity=group.id)

        if len(pi_ids) == 0:
            pending_count = pending_counts.get(group.id, 0)
            pending_suffix = ""
            if pending_count > 0:
                pending_suffix = f" Pending requests currently queued: {pending_count}."
            _append_issue(
                issues,
                issue_key=f"group-no-pi:{group.id}",
                issue_type="group-no-active-pi",
                severity="warning",
                category="membership workflow",
                title=f"Group {group.id} has no active PI configured",
                detail=(
                    "Join requests can be submitted but no PI can be notified to review them."
                    f"{pending_suffix}"
                ),
                href=group_membership_url,
                link_label="open in RBAC explorer",
            )
            continue

        for pi_id in pi_ids:
            pi_user = pi_user_map.get(pi_id)
            if pi_user is None:
                _append_issue(
                    issues,
                    issue_key=f"group-missing-pi-user:{group.id}:{pi_id}",
                    issue_type="group-missing-pi-user",
                    severity="warning",
                    category="data integrity",
                    title=f"Group {group.id} references missing PI user {pi_id}",
                    detail="The PI reference cannot be resolved to an active user record.",
                    href=group_membership_url,
                    link_label="open in RBAC explorer",
                )
                continue
            if not pi_user.active:
                _append_issue(
                    issues,
                    issue_key=f"group-pi-inactive:{group.id}:{pi_user.id}",
                    issue_type="group-pi-inactive",
                    severity="warning",
                    category="membership workflow",
                    title=f"Group {group.id} PI {pi_user.id} is inactive",
                    detail="Inactive PI users cannot reliably review join requests.",
                    href=group_membership_url,
                    link_label="open in RBAC explorer",
                )
                continue
            if (pi_user.addr or "").strip() == "":
                _append_issue(
                    issues,
                    issue_key=f"group-pi-no-email:{group.id}:{pi_user.id}",
                    issue_type="group-pi-no-email",
                    severity="warning",
                    category="notifications",
                    title=f"Group {group.id} PI {pi_user.id} has no email address",
                    detail="Join-request notifications cannot be delivered to this PI.",
                    href=group_membership_url,
                    link_label="open in RBAC explorer",
                )

    dev_pi_ids = sorted(set(pi_by_group.get("DEV", [])))
    if len(dev_pi_ids) == 0:
        _append_issue(
            issues,
            issue_key="dev-no-active-pi",
            issue_type="dev-no-active-pi",
            severity="warning",
            category="technologist workflow",
            title="DEV group has no active PI configured",
            detail="Technologist application notifications cannot be routed to a DEV PI.",
            href=url_for("rbac", scope="group", entity="DEV"),
            link_label="open DEV in RBAC explorer",
        )
    else:
        has_dev_pi_contact = False
        for dev_pi_id in dev_pi_ids:
            dev_pi_user = pi_user_map.get(dev_pi_id)
            if dev_pi_user is None:
                continue
            if not dev_pi_user.active:
                continue
            if (dev_pi_user.addr or "").strip() == "":
                continue
            has_dev_pi_contact = True
            break
        if not has_dev_pi_contact:
            _append_issue(
                issues,
                issue_key="dev-pi-contact-unavailable",
                issue_type="dev-pi-contact-unavailable",
                severity="warning",
                category="technologist workflow",
                title="DEV PI notification contact is unavailable",
                detail=(
                    "Technologist application notifications are configured, "
                    "but no active DEV PI currently has a usable email address."
                ),
                href=url_for("rbac", scope="group", entity="DEV"),
                link_label="open DEV in RBAC explorer",
            )

    return issues


def _notification_incident_state(
    value: str, *, default: str = NOTIFICATION_INCIDENT_STATE_OPEN
) -> str:
    token = (value or "").strip().lower()
    if token in NOTIFICATION_INCIDENT_STATE_VALUES:
        return token
    return default


def _notification_incident_search_field(value: str, *, default: str = "all") -> str:
    token = (value or "").strip().lower()
    if token in NOTIFICATION_INCIDENT_SEARCH_FIELD_LABELS:
        return token
    return default


def _notification_issue_fingerprint(issue: Dict[str, Any]) -> str:
    parts = [
        str(issue.get("issue_type") or "").strip().lower(),
        str(issue.get("category") or "").strip().lower(),
        str(issue.get("severity") or "").strip().lower(),
        str(issue.get("title") or "").strip(),
        str(issue.get("detail") or "").strip(),
        str(issue.get("href") or "").strip(),
        str(issue.get("link_label") or "").strip(),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _normalized_detected_issues(
    detected_issues: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    seen_keys = set()
    for issue in detected_issues:
        issue_key = (issue.get("issue_key") or "").strip()
        if issue_key == "" or issue_key in seen_keys:
            continue
        seen_keys.add(issue_key)

        normalized.append(
            {
                "issue_key": issue_key,
                "issue_type": (issue.get("issue_type") or "unknown").strip()
                or "unknown",
                "category": (issue.get("category") or "uncategorized").strip()
                or "uncategorized",
                "severity": (issue.get("severity") or "warning").strip().lower()
                or "warning",
                "title": (issue.get("title") or "").strip(),
                "detail": (issue.get("detail") or "").strip(),
                "href": (issue.get("href") or "").strip(),
                "link_label": (issue.get("link_label") or "").strip(),
            }
        )
    return normalized


def reconcile_notification_incidents(
    detected_issues: List[Dict[str, str]],
) -> Dict[str, int]:
    stats = {
        "detected": len(detected_issues),
        "created": 0,
        "reopened": 0,
        "ignore_expired": 0,
        "auto_resolved": 0,
        "expired": 0,
    }
    if not logic.notification_incident_table_available():
        return stats

    now = datetime.datetime.now(datetime.timezone.utc)
    normalized = _normalized_detected_issues(detected_issues)
    keys = sorted({issue["issue_key"] for issue in normalized})
    existing_rows: Dict[str, model.NotificationIncident] = {}

    if len(keys) > 0:
        rows = model.NotificationIncident.query.filter(
            model.NotificationIncident.issue_key.in_(keys)
        ).all()
        existing_rows = {row.issue_key: row for row in rows}

    for issue in normalized:
        issue_key = issue["issue_key"]
        fingerprint = _notification_issue_fingerprint(issue)
        row = existing_rows.get(issue_key)

        if row is None:
            row = model.NotificationIncident(
                issue_key=issue_key,
                issue_type=issue["issue_type"],
                category=issue["category"],
                severity=issue["severity"],
                title=issue["title"],
                detail=issue["detail"],
                href=issue["href"] or None,
                link_label=issue["link_label"],
                active=True,
                state=NOTIFICATION_INCIDENT_STATE_OPEN,
                state_note="Detected by issue scanner.",
                state_changed_by="system",
                state_changed_at=now,
                ignored_until=None,
                first_seen_at=now,
                last_seen_at=now,
                last_detected_at=now,
                last_resolved_at=None,
                occurrence_count=1,
                fingerprint=fingerprint,
            )
            model.db.session.add(row)
            stats["created"] += 1
            continue

        was_active = bool(row.active)
        row.issue_type = issue["issue_type"]
        row.category = issue["category"]
        row.severity = issue["severity"]
        row.title = issue["title"]
        row.detail = issue["detail"]
        row.href = issue["href"] or None
        row.link_label = issue["link_label"]
        row.fingerprint = fingerprint
        row.last_seen_at = now
        row.last_detected_at = now
        row.active = True

        row_state = _notification_incident_state(row.state)
        ignore_expired = (
            row_state == NOTIFICATION_INCIDENT_STATE_IGNORED
            and row.ignored_until is not None
            and row.ignored_until <= now
        )

        if not was_active:
            row.occurrence_count = max(1, int(row.occurrence_count or 1)) + 1
            row.state = NOTIFICATION_INCIDENT_STATE_OPEN
            row.state_note = "Reopened automatically by issue scanner."
            row.state_changed_by = "system"
            row.state_changed_at = now
            row.ignored_until = None
            row.last_resolved_at = None
            stats["reopened"] += 1
        elif ignore_expired:
            row.state = NOTIFICATION_INCIDENT_STATE_OPEN
            row.state_note = "Ignore expired; reopened automatically by issue scanner."
            row.state_changed_by = "system"
            row.state_changed_at = now
            row.ignored_until = None
            row.last_resolved_at = None
            stats["ignore_expired"] += 1
        elif row_state == NOTIFICATION_INCIDENT_STATE_RESOLVED:
            row.state = NOTIFICATION_INCIDENT_STATE_OPEN
            row.state_note = "Reopened automatically by issue scanner."
            row.state_changed_by = "system"
            row.state_changed_at = now
            row.last_resolved_at = None
            stats["reopened"] += 1

        model.db.session.add(row)

    stale_query = model.NotificationIncident.query.filter(
        model.NotificationIncident.active.is_(True)
    )
    if len(keys) > 0:
        stale_query = stale_query.filter(
            ~model.NotificationIncident.issue_key.in_(keys)
        )
    stale_rows = stale_query.all()

    for row in stale_rows:
        row.active = False
        if row.state != NOTIFICATION_INCIDENT_STATE_RESOLVED:
            stats["auto_resolved"] += 1
        row.state = NOTIFICATION_INCIDENT_STATE_RESOLVED
        row.state_note = "Resolved automatically by issue scanner."
        row.state_changed_by = "system"
        row.state_changed_at = now
        row.ignored_until = None
        row.last_resolved_at = now
        model.db.session.add(row)

    cutoff = now - datetime.timedelta(days=NOTIFICATION_INCIDENT_RETENTION_DAYS)
    stats["expired"] = int(
        model.NotificationIncident.query.filter(
            model.NotificationIncident.active.is_(False),
            func.coalesce(
                model.NotificationIncident.last_resolved_at,
                model.NotificationIncident.last_seen_at,
                model.NotificationIncident.first_seen_at,
            )
            < cutoff,
        ).delete(synchronize_session=False)
    )

    return stats


def run_notification_detection_scan() -> Dict[str, int]:
    detected_issues = _build_potential_issues()
    return reconcile_notification_incidents(detected_issues)


def set_notification_incident_state(
    *,
    issue_key: str,
    target_state: str,
    note: str,
    actor: str,
    ignored_until: Optional[datetime.datetime] = None,
) -> bool:
    if not logic.notification_incident_table_available():
        return False

    issue_token = (issue_key or "").strip()
    if issue_token == "":
        raise ValueError("issue_key is required")

    note_token = (note or "").strip()
    if note_token == "":
        raise ValueError("note is required")

    state_token = _notification_incident_state(target_state, default="")
    if state_token not in {
        NOTIFICATION_INCIDENT_STATE_OPEN,
        NOTIFICATION_INCIDENT_STATE_IGNORED,
    }:
        raise ValueError(f"invalid state target: {target_state}")

    row = model.NotificationIncident.query.get(issue_token)
    if row is None:
        return False

    if not bool(row.active):
        raise ValueError("only active incidents can be changed")

    now = datetime.datetime.now(datetime.timezone.utc)
    if state_token == NOTIFICATION_INCIDENT_STATE_OPEN:
        row.state = NOTIFICATION_INCIDENT_STATE_OPEN
        row.ignored_until = None
    else:
        row.state = NOTIFICATION_INCIDENT_STATE_IGNORED
        row.ignored_until = ignored_until
    row.state_note = note_token
    row.state_changed_by = (actor or "").strip() or "unknown"
    row.state_changed_at = now
    model.db.session.add(row)
    return True


def _notification_incident_payload(
    row: model.NotificationIncident,
) -> Dict[str, Any]:
    state = _notification_incident_state(row.state)
    return {
        "issue_key": row.issue_key,
        "issue_type": row.issue_type,
        "category": row.category,
        "severity": row.severity,
        "title": row.title,
        "detail": row.detail,
        "href": row.href or "",
        "link_label": row.link_label,
        "state": state,
        "state_note": row.state_note or "",
        "state_changed_by": row.state_changed_by or "",
        "state_changed_at": row.state_changed_at,
        "ignored_until": row.ignored_until,
        "active": bool(row.active),
        "occurrence_count": int(row.occurrence_count or 1),
    }


def notification_incident_category_values() -> List[str]:
    if not logic.notification_incident_table_available():
        return []

    rows = (
        model.db.session.query(model.NotificationIncident.category)
        .distinct()
        .order_by(model.NotificationIncident.category.asc())
        .all()
    )
    categories: List[str] = []
    for row in rows:
        category = (row[0] or "").strip()
        if category == "":
            continue
        categories.append(category)
    return categories


def notification_incident_rows(
    *,
    include_open: bool,
    include_resolved: bool,
    include_ignored: bool,
    category: str = "all",
    search: str = "",
    search_field: str = "all",
) -> List[Dict[str, Any]]:
    if not logic.notification_incident_table_available():
        return []

    allowed_states: List[str] = []
    if include_open:
        allowed_states.append(NOTIFICATION_INCIDENT_STATE_OPEN)
    if include_ignored:
        allowed_states.append(NOTIFICATION_INCIDENT_STATE_IGNORED)
    if include_resolved:
        allowed_states.append(NOTIFICATION_INCIDENT_STATE_RESOLVED)
    if len(allowed_states) == 0:
        return []

    query = model.NotificationIncident.query.filter(
        model.NotificationIncident.state.in_(allowed_states)
    )

    category_token = (category or "").strip()
    if category_token != "" and category_token.lower() != "all":
        query = query.filter(model.NotificationIncident.category == category_token)

    search_token = (search or "").strip()
    if search_token != "":
        search_like = f"%{search_token}%"
        field = _notification_incident_search_field(search_field, default="all")
        if field == "all":
            query = query.filter(
                or_(
                    model.NotificationIncident.title.ilike(search_like),
                    model.NotificationIncident.detail.ilike(search_like),
                    model.NotificationIncident.issue_key.ilike(search_like),
                    model.NotificationIncident.category.ilike(search_like),
                )
            )
        elif field == "title":
            query = query.filter(model.NotificationIncident.title.ilike(search_like))
        elif field == "detail":
            query = query.filter(model.NotificationIncident.detail.ilike(search_like))
        elif field == "issue_key":
            query = query.filter(
                model.NotificationIncident.issue_key.ilike(search_like)
            )
        else:
            query = query.filter(model.NotificationIncident.category.ilike(search_like))

    rows = query.order_by(
        model.NotificationIncident.category.asc(),
        model.NotificationIncident.last_seen_at.desc(),
    ).all()
    return [_notification_incident_payload(row) for row in rows]


def notification_scan_last_updated_at() -> Optional[datetime.datetime]:
    if logic.rbac_audit_table_available():
        row = (
            model.RbacAuditLog.query.filter(
                model.RbacAuditLog.action == "notifications.scan.run"
            )
            .order_by(model.RbacAuditLog.occurred_at.desc())
            .first()
        )
        if row is not None and row.occurred_at is not None:
            return row.occurred_at

    if not logic.notification_incident_table_available():
        return None

    latest_detected_at = model.db.session.query(
        func.max(model.NotificationIncident.last_detected_at)
    ).scalar()
    if latest_detected_at is not None:
        return latest_detected_at

    latest_state_change = model.db.session.query(
        func.max(model.NotificationIncident.state_changed_at)
    ).scalar()
    if latest_state_change is not None:
        return latest_state_change

    return model.db.session.query(
        func.max(model.NotificationIncident.last_seen_at)
    ).scalar()


def _build_potential_issue_sections(
    potential_issues: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    urgent_categories = {"top priority", "membership workflow", "technologist workflow"}

    issues_by_category: Dict[str, List[Dict[str, Any]]] = {}
    for issue in potential_issues:
        category = (issue.get("category") or "uncategorized").strip()
        if category == "":
            category = "uncategorized"
        issues_by_category.setdefault(category, []).append(issue)

    def _category_priority(category: str) -> int:
        if category == "top priority":
            return 2
        if category in urgent_categories:
            return 1
        return 0

    sorted_categories = sorted(
        issues_by_category,
        key=lambda category: (
            -(_category_priority(category)),
            -(len(issues_by_category[category])),
            category.lower(),
        ),
    )

    def _issue_sort_key(issue: Dict[str, Any]) -> Any:
        state = _notification_incident_state(str(issue.get("state") or "open"))
        state_rank = 0
        if state == NOTIFICATION_INCIDENT_STATE_IGNORED:
            state_rank = 1
        elif state == NOTIFICATION_INCIDENT_STATE_RESOLVED:
            state_rank = 2
        return (
            state_rank,
            issue.get("severity", "warning") == "warning",
            issue.get("title", "").lower(),
        )

    sections = []
    for category in sorted_categories:
        issue_list = sorted(issues_by_category[category], key=_issue_sort_key)
        category_has_open = any(
            _notification_incident_state(str(issue.get("state") or "open"))
            == NOTIFICATION_INCIDENT_STATE_OPEN
            for issue in issue_list
        )
        sections.append(
            {
                "category": category,
                "issue_count": len(issue_list),
                "urgent": category in urgent_categories and category_has_open,
                "issues": issue_list,
            }
        )

    return sections
