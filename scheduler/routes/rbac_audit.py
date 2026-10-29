from __future__ import annotations

import re
from typing import Any, Dict, List

from flask import abort, request
from sqlalchemy import text as sql_text

import scheduler.logic.rbac_audit_support as logic
from scheduler import model

RBAC_AUDIT_DEFAULT_LIMIT = 10
RBAC_AUDIT_SHOW_MORE_INCREMENT = 20
RBAC_AUDIT_MAX_LIMIT = 200
_RBAC_AUDIT_SEARCH_FIELD_LABELS: Dict[str, str] = {
    "all": "all fields",
    "action": "action",
    "actor": "actor",
    "entity": "entity ids",
    "how": "how",
    "ip": "ip",
    "what": "details",
    "where": "where",
}


def _rbac_audit_limit_from_raw(
    raw_limit: str,
    *,
    default: int = RBAC_AUDIT_DEFAULT_LIMIT,
    max_limit: int = RBAC_AUDIT_MAX_LIMIT,
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


def _rbac_audit_limit() -> int:
    return _rbac_audit_limit_from_raw(
        request.args.get("limit", str(RBAC_AUDIT_DEFAULT_LIMIT)),
        default=RBAC_AUDIT_DEFAULT_LIMIT,
        max_limit=RBAC_AUDIT_MAX_LIMIT,
        strict=True,
    )


def _rbac_include_inactive_from_request(default: bool = False) -> bool:
    raw = request.args.get("active")
    if raw is None:
        return default
    token = raw.strip().lower()
    return token in {"1", "true", "yes", "on", "all", "inactive"}


def _rbac_audit_search_field(value: str, *, default: str = "all") -> str:
    token = (value or "").strip().lower()
    if token in _RBAC_AUDIT_SEARCH_FIELD_LABELS:
        return token
    return default


def _rbac_audit_rows(
    scope: str,
    entity: str,
    *,
    limit: int,
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
                "(researchercode = :entity or requestercode = :entity "
                "or actor = :entity)"
            )
    ip_filter_expr = (
        "coalesce(ip_addr::text, '')"
        if logic.rbac_audit_ip_column_available()
        else "''"
    )
    search_value = (search or "").strip()
    if search_value != "":
        field = _rbac_audit_search_field(search_field, default="all")
        if field == "all":
            filters.append(
                f"""
                (
                    action ilike :search
                    or actor ilike :search
                    or {ip_filter_expr} ilike :search
                    or where_path ilike :search
                    or how ilike :search
                    or what ilike :search
                    or coalesce(deptcode, '') ilike :search
                    or coalesce(scannercode, '') ilike :search
                    or coalesce(researchercode, '') ilike :search
                    or coalesce(requestercode, '') ilike :search
                )
                """
            )
        elif field == "action":
            filters.append("action ilike :search")
        elif field == "actor":
            filters.append("actor ilike :search")
        elif field == "entity":
            filters.append(
                """
                (
                    coalesce(deptcode, '') ilike :search
                    or coalesce(scannercode, '') ilike :search
                    or coalesce(researchercode, '') ilike :search
                    or coalesce(requestercode, '') ilike :search
                )
                """
            )
        elif field == "how":
            filters.append("how ilike :search")
        elif field == "ip":
            filters.append(f"{ip_filter_expr} ilike :search")
        elif field == "where":
            filters.append("where_path ilike :search")
        else:
            filters.append("what ilike :search")
        params["search"] = f"%{search_value}%"
    where = ""
    if len(filters) > 0:
        where = "where " + " and ".join(filters)
    ip_projection = (
        "ip_addr as ip_addr"
        if logic.rbac_audit_ip_column_available()
        else "null as ip_addr"
    )
    rows = model.db.session.execute(
        sql_text(
            f"""
            select
                auditid, occurred_at, action, actor,
                {ip_projection},
                where_path, how, what,
                deptcode, scannercode, researchercode, requestercode
            from rbac_audit_log
            {where}
            order by auditid desc
            limit :limit
            """
        ),
        params,
    ).mappings()
    return [dict(row) for row in rows]


def _rbac_audit_payload(
    row: Dict[str, Any],
) -> Dict[str, Any]:
    occurred_at = row.get("occurred_at")
    when = ""
    if occurred_at is not None:
        when = (
            occurred_at.isoformat()
            if hasattr(occurred_at, "isoformat")
            else str(occurred_at)
        )
    ip = str(row.get("ip_addr") or "").strip()
    if ip == "":
        match = re.search(r"(?:^|,\s*)ip=([^,]+)", str(row.get("what") or ""))
        if match:
            ip = match.group(1).strip()
    return {
        "id": row.get("auditid"),
        "action": row.get("action", ""),
        "actor": row.get("actor", ""),
        "where": row.get("where_path", ""),
        "when": when,
        "how": row.get("how", ""),
        "what": row.get("what", ""),
        "ip": ip,
    }
