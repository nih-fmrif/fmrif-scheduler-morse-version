from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode

from flask import current_app, g, redirect, request, url_for
from sqlalchemy.exc import SQLAlchemyError

import scheduler.logic.admin_config as logic
import scheduler.logic.rbac_audit_support as audit_logic
from scheduler import model

Breadcrumb_links = Dict[str, List[Tuple[str, str]]]
Subpage_links = Dict[str, Dict[str, Any]]

_breadcrumb_fn: Optional[Callable[..., Breadcrumb_links]] = None
_subpage_nav_fn: Optional[
    Callable[[str, List[Tuple[bool, str, str]]], Subpage_links]
] = None


def configure_rbac_route_helpers(
    *,
    breadcrumb_fn: Callable[..., Breadcrumb_links],
    subpage_nav_fn: Callable[[str, List[Tuple[bool, str, str]]], Subpage_links],
) -> None:
    global _breadcrumb_fn, _subpage_nav_fn
    _breadcrumb_fn = breadcrumb_fn
    _subpage_nav_fn = subpage_nav_fn


def _require_helper(
    helper: Optional[Callable[..., Any]], name: str
) -> Callable[..., Any]:
    if helper is None:
        raise RuntimeError(f"Route helper not configured: {name}")
    return helper


def breadcrumb(*routes):
    return _require_helper(_breadcrumb_fn, "breadcrumb")(*routes)


def subpage_nav(title: str, links: List[Tuple[bool, str, str]]) -> Subpage_links:
    return _require_helper(_subpage_nav_fn, "subpage_nav")(title, links)


def _request_client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded:
        first = forwarded.split(",", 1)[0].strip()
        if first:
            return first
    real_ip = request.headers.get("X-Real-IP", "").strip()
    if real_ip:
        return real_ip
    remote = (request.remote_addr or "").strip()
    return remote or "unknown"


def _request_truthy(value: str, *, default: bool = False) -> bool:
    token = (value or "").strip().lower()
    if token == "":
        return default
    return token in {"1", "true", "yes", "on"}


def _normalized_return_query(raw_query: str) -> str:
    token = (raw_query or "").strip()
    if token.startswith("?"):
        return token[1:]
    return token


def _app_issues_redirect(raw_query: str):
    query = _normalized_return_query(raw_query)
    target = url_for("app_issues")
    if query != "":
        target = f"{target}?{query}"
    return redirect(target)


def _app_issues_query_with_updates(
    raw_query: str, updates: Dict[str, Optional[str]]
) -> str:
    query = _normalized_return_query(raw_query)
    pairs = [(name, value) for name, value in parse_qsl(query, keep_blank_values=True)]
    update_keys = set(updates.keys())
    filtered_pairs = [(name, value) for name, value in pairs if name not in update_keys]
    for key, value in updates.items():
        normalized = "" if value is None else str(value).strip()
        if normalized != "":
            filtered_pairs.append((key, normalized))
    return urlencode(filtered_pairs)


def _app_error_limit_from_raw(
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
            from flask import abort

            abort(400, f"invalid limit: {token}")
        return default
    limit = int(token)
    if limit < 1 or limit > max_limit:
        if strict:
            from flask import abort

            abort(400, f"limit must be between 1 and {max_limit}")
        return max(1, min(limit, max_limit))
    return limit


def _admin_mapping_kinds() -> List[Dict[str, str]]:
    return [
        {
            "id": "user-dept",
            "label": "user-dept.csv",
            "description": (
                "user to group membership and PI assignment. Use the RBAC explorer "
                "for day-to-day production edits; use this CSV for bulk review, "
                "import/export, and reconciliation."
            ),
            "legacy_tooltip": (
                "Legacy CSV import/export still uses the column name dept because "
                "older schema and bootstrap scripts stored group ids in "
                "deptcode/tlkpdept. In the current app these values are validated "
                "against Group.id, so dept in these files means group id."
            ),
            "current_value": logic.format_admin_mapping_rows_for_form("user-dept"),
        },
        {
            "id": "dev-dept",
            "label": "dev-dept.csv",
            "description": (
                "device to group mapping. Use the RBAC explorer for day-to-day "
                "production edits; use this CSV for bulk review, import/export, "
                "and reconciliation."
            ),
            "legacy_tooltip": (
                "Legacy CSV import/export still uses the column name dept because "
                "older schema and bootstrap scripts stored group ids in "
                "deptcode/tlkpdept. In the current app these values are validated "
                "against Group.id, so dept in these files means group id."
            ),
            "current_value": logic.format_admin_mapping_rows_for_form("dev-dept"),
        },
        {
            "id": "devperm",
            "label": "devperm.csv",
            "description": (
                "device permissions per user "
                "(templates,slot,technologist,medical,training)"
            ),
            "current_value": logic.format_admin_mapping_rows_for_form("devperm"),
        },
    ]


def _record_rbac_action(
    action: str,
    where: str,
    how: str,
    what: str,
    *,
    source_ip: Optional[str] = None,
) -> None:
    actor = g.user.id if g.user is not None else "unknown"
    client_ip = source_ip or _request_client_ip()
    try:
        audit_logic.log_rbac_audit_event(
            action=action,
            actor=actor,
            where=where,
            how=how,
            what=what,
            source_ip=client_ip,
        )
    except TypeError:
        audit_logic.log_rbac_audit_event(
            action=action,
            actor=actor,
            where=where,
            how=how,
            what=what,
        )


def audit_rbac_action(
    action: str,
    where: str,
    how: str,
    what: str,
) -> None:
    _record_rbac_action(action=action, where=where, how=how, what=what)
    try:
        model.db.session.commit()
    except SQLAlchemyError:
        model.db.session.rollback()
        current_app.logger.exception("Failed to commit RBAC audit record")
