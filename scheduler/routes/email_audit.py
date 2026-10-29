from __future__ import annotations

from typing import Any, Dict, List

from flask import abort, request
from sqlalchemy import text as sql_text

from scheduler import model

_EMAIL_AUDIT_STATUS_LABELS: Dict[str, str] = {
    "all": "all statuses",
    "sent": "sent",
    "failed": "failed",
    "resolved": "resolved",
    "skipped": "skipped",
}

_EMAIL_AUDIT_ISSUE_STATE_LABELS: Dict[str, str] = {
    "all": "all issue states",
    "open": "open",
    "resolved": "resolved",
    "none": "none",
}

_EMAIL_AUDIT_SEARCH_FIELD_LABELS: Dict[str, str] = {
    "all": "all fields",
    "action": "action",
    "actor": "actor",
    "details": "details",
    "recipient": "recipient",
    "issue_key": "issue key",
    "subject": "subject",
}


def _email_audit_limit_from_raw(
    raw_limit: str,
    *,
    default: int,
    max_limit: int,
    strict: bool = False,
) -> int:
    token = (raw_limit or "").strip()
    if token == "":
        return default
    if not token.isdigit():
        if strict:
            abort(400, f"invalid limit: {token}")
        return default
    limit = int(token)
    if limit < 1 or limit > max_limit:
        if strict:
            abort(400, f"limit must be between 1 and {max_limit}")
        return max(1, min(limit, max_limit))
    return limit


def _email_audit_limit(default: int = 40, max_limit: int = 200) -> int:
    return _email_audit_limit_from_raw(
        request.args.get("limit", str(default)),
        default=default,
        max_limit=max_limit,
        strict=True,
    )


def _email_audit_status(value: str, *, default: str = "all") -> str:
    token = (value or "").strip().lower()
    if token in _EMAIL_AUDIT_STATUS_LABELS:
        return token
    return default


def _email_audit_issue_state(value: str, *, default: str = "all") -> str:
    token = (value or "").strip().lower()
    if token in _EMAIL_AUDIT_ISSUE_STATE_LABELS:
        return token
    return default


def _email_audit_search_field(value: str, *, default: str = "all") -> str:
    token = (value or "").strip().lower()
    if token in _EMAIL_AUDIT_SEARCH_FIELD_LABELS:
        return token
    return default


def _email_audit_rows(
    scope: str,
    entity: str,
    *,
    limit: int,
    status: str = "all",
    issue_state: str = "all",
    search: str = "",
    search_field: str = "all",
) -> List[Dict[str, Any]]:
    filters: List[str] = []
    params: Dict[str, Any] = {"limit": limit}

    if scope != "all" and entity != "":
        params["entity"] = entity
        if scope == "group":
            filters.append("deptcode = :entity")
        elif scope == "device":
            filters.append("scannercode = :entity")
        elif scope == "user":
            filters.append(
                "(researchercode = :entity or requestercode = :entity or actor = :entity)"
            )

    status_value = _email_audit_status(status, default="all")
    if status_value != "all":
        filters.append("status = :status")
        params["status"] = status_value

    issue_state_value = _email_audit_issue_state(issue_state, default="all")
    if issue_state_value != "all":
        filters.append("issue_state = :issue_state")
        params["issue_state"] = issue_state_value

    search_value = (search or "").strip()
    if search_value != "":
        field = _email_audit_search_field(search_field, default="all")
        if field == "all":
            filters.append(
                """
                (
                    action ilike :search
                    or actor ilike :search
                    or recipient ilike :search
                    or subject ilike :search
                    or details ilike :search
                    or coalesce(issue_key, '') ilike :search
                )
                """
            )
        elif field == "action":
            filters.append("action ilike :search")
        elif field == "actor":
            filters.append("actor ilike :search")
        elif field == "details":
            filters.append("details ilike :search")
        elif field == "recipient":
            filters.append("recipient ilike :search")
        elif field == "issue_key":
            filters.append("coalesce(issue_key, '') ilike :search")
        else:
            filters.append("subject ilike :search")
        params["search"] = f"%{search_value}%"

    where = ""
    if len(filters) > 0:
        where = "where " + " and ".join(filters)

    rows = model.db.session.execute(
        sql_text(
            f"""
            select
                auditid, occurred_at, action, actor, ip_addr,
                where_path, how, status, recipient, subject,
                details, issue_key, issue_state,
                deptcode, scannercode, researchercode, requestercode
            from email_audit_log
            {where}
            order by auditid desc
            limit :limit
            """
        ),
        params,
    ).mappings()
    return [dict(row) for row in rows]


def _email_audit_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    occurred_at = row.get("occurred_at")
    when = ""
    if occurred_at is not None:
        when = (
            occurred_at.isoformat()
            if hasattr(occurred_at, "isoformat")
            else str(occurred_at)
        )

    return {
        "id": row.get("auditid"),
        "when": when,
        "action": row.get("action", ""),
        "actor": row.get("actor", ""),
        "ip": str(row.get("ip_addr") or "").strip(),
        "where": row.get("where_path", ""),
        "how": row.get("how", ""),
        "status": row.get("status", ""),
        "recipient": row.get("recipient", ""),
        "subject": row.get("subject", ""),
        "details": row.get("details", ""),
        "issue_key": row.get("issue_key", ""),
        "issue_state": row.get("issue_state", ""),
    }
