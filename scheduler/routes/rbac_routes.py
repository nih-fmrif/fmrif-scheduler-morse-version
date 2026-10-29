from __future__ import annotations

import csv
import datetime
import io
from time import perf_counter
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode

from flask import (
    Response,
    abort,
    current_app,
    flash,
    g,
    has_request_context,
    jsonify,
    redirect,
    request,
    url_for,
)
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import InvalidRequestError, SQLAlchemyError

from scheduler import logic, model

from .email_audit import (
    _EMAIL_AUDIT_ISSUE_STATE_LABELS,
    _EMAIL_AUDIT_SEARCH_FIELD_LABELS,
    _EMAIL_AUDIT_STATUS_LABELS,
    _email_audit_issue_state,
    _email_audit_limit,
    _email_audit_limit_from_raw,
    _email_audit_payload,
    _email_audit_rows,
    _email_audit_search_field,
    _email_audit_status,
)
from .rbac_audit import (
    _RBAC_AUDIT_SEARCH_FIELD_LABELS,
    RBAC_AUDIT_DEFAULT_LIMIT,
    RBAC_AUDIT_MAX_LIMIT,
    RBAC_AUDIT_SHOW_MORE_INCREMENT,
    _rbac_audit_limit,
    _rbac_audit_limit_from_raw,
    _rbac_audit_payload,
    _rbac_audit_rows,
    _rbac_audit_search_field,
    _rbac_include_inactive_from_request,
)
from .rbac_explorer import (
    _RBAC_AUDIT_SCOPE_LABELS,
    _RBAC_SCOPE_LABELS,
    _rbac_actor,
    _rbac_actor_allows_scope,
    _rbac_actor_scope_labels,
    _rbac_detail,
    _rbac_empty_detail,
    _rbac_entities_for_actor,
    _rbac_entity_visible_for_actor,
    _rbac_restrict_detail_for_actor,
    _rbac_scopes,
)
from .rbac_issues import (
    NOTIFICATION_INCIDENT_SEARCH_FIELD_LABELS,
    _build_potential_issue_sections,
    _build_potential_issues,
    _notification_incident_search_field,
    notification_incident_category_values,
    notification_incident_rows,
    notification_scan_last_updated_at,
    run_notification_detection_scan,
    set_notification_incident_state,
)
from .rbac_mutations import _rbac_mutate_batch, _rbac_required_form_value

Breadcrumb_links = Dict[str, List[Tuple[str, str]]]
Subpage_links = Dict[str, Dict[str, Any]]

_breadcrumb_fn: Optional[Callable[..., Breadcrumb_links]] = None
_subpage_nav_fn: Optional[
    Callable[[str, List[Tuple[bool, str, str]]], Subpage_links]
] = None
_RBAC_PROFILE_PATHS = frozenset(
    {
        "/rbac",
        "/json/v1/rbac/explorer",
        "/json/v1/rbac/audit",
        "/json/v1/email/audit",
    }
)


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


def _rbac_profile_requested() -> bool:
    token = request.args.get("profile", "").strip().lower()
    if token in {"1", "true", "yes", "on"}:
        return True
    header = request.headers.get("X-RBAC-Profile", "").strip().lower()
    return header in {"1", "true", "yes", "on"}


def _rbac_profile_should_trace_request() -> bool:
    return request.path in _RBAC_PROFILE_PATHS and _rbac_profile_requested()


def _rbac_profile_payload_bytes(response) -> int:
    payload_size = response.calculate_content_length()
    if payload_size is not None:
        return int(payload_size)
    return len(response.get_data(cache=True))


def _rbac_profile_start_request() -> None:
    if not _rbac_profile_should_trace_request():
        return

    state: Dict[str, Any] = {
        "started_at": perf_counter(),
        "query_count": 0,
    }

    def _before_cursor_execute(
        _conn,
        _cursor,
        _statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        if not has_request_context():
            return
        current_state = getattr(g, "_rbac_profile_state", None)
        if current_state is not state:
            return
        state["query_count"] = int(state["query_count"]) + 1

    event.listen(Engine, "before_cursor_execute", _before_cursor_execute)
    state["listener"] = _before_cursor_execute
    g._rbac_profile_state = state


def _rbac_profile_cleanup_state() -> Optional[Dict[str, Any]]:
    state = getattr(g, "_rbac_profile_state", None)
    if not isinstance(state, dict):
        return None

    listener = state.get("listener")
    if listener is not None:
        try:
            event.remove(Engine, "before_cursor_execute", listener)
        except (InvalidRequestError, ValueError, TypeError):
            pass

    g._rbac_profile_state = None
    return state


def _rbac_profile_finish_request(response):
    state = _rbac_profile_cleanup_state()
    if state is None:
        return response

    duration_ms = max(0.0, (perf_counter() - float(state["started_at"])) * 1000.0)
    query_count = int(state.get("query_count", 0))
    payload_bytes = _rbac_profile_payload_bytes(response)

    response.headers["X-RBAC-Profile-Duration-Ms"] = f"{duration_ms:.2f}"
    response.headers["X-RBAC-Profile-SQL-Queries"] = str(query_count)
    response.headers["X-RBAC-Profile-Payload-Bytes"] = str(payload_bytes)

    current_app.logger.info(
        "RBAC profile path=%s endpoint=%s status=%s duration_ms=%.2f sql_queries=%d payload_bytes=%d",
        request.path,
        request.endpoint,
        response.status_code,
        duration_ms,
        query_count,
        payload_bytes,
    )
    return response


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
    filtered_pairs = [
        (name, value) for name, value in pairs if name not in set(updates.keys())
    ]
    for key, value in updates.items():
        normalized = "" if value is None else str(value).strip()
        if normalized != "":
            filtered_pairs.append((key, normalized))
    return urlencode(filtered_pairs)


def _app_issues_query_with_flag(raw_query: str, key: str, enabled: bool) -> str:
    return _app_issues_query_with_updates(raw_query, {key: "1" if enabled else None})


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
            abort(400, f"invalid limit: {token}")
        return default
    limit = int(token)
    if limit < 1 or limit > max_limit:
        if strict:
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
            "description": "device permissions per user (templates,slot,technologist,medical,training)",
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
        logic.log_rbac_audit_event(
            action=action,
            actor=actor,
            where=where,
            how=how,
            what=what,
            source_ip=client_ip,
        )
    except TypeError:
        logic.log_rbac_audit_event(
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


def rbac_explorer_data():
    actor = _rbac_actor(g.user)
    if not bool(actor.get("can_access")):
        abort(403, "access denied")

    allowed_scopes = actor.get("allowed_scopes", [])
    if not isinstance(allowed_scopes, list) or len(allowed_scopes) == 0:
        abort(403, "access denied")

    scope = request.args.get("scope", "group").strip().lower()
    if scope not in _RBAC_SCOPE_LABELS or scope not in allowed_scopes:
        scope = allowed_scopes[0]
    include_inactive = False
    if bool(actor.get("is_admin")):
        include_inactive = _rbac_include_inactive_from_request(False)

    include_entities = request.args.get("entities", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    include_detail = request.args.get("detail", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }

    entities = (
        _rbac_entities_for_actor(scope, actor, include_inactive=include_inactive)
        if include_entities
        else []
    )
    selected = request.args.get("entity", "").strip()
    if selected != "" and not _rbac_entity_visible_for_actor(
        scope, selected, actor, include_inactive=include_inactive
    ):
        selected = ""
    detail = _rbac_empty_detail(scope)

    if include_entities and len(entities) > 0:
        if selected != "":
            valid_ids = {entry["id"] for entry in entities}
            if selected not in valid_ids:
                selected = ""
        if include_detail and selected == "":
            selected = entities[0]["id"]

    if include_detail and selected != "":
        detail = _rbac_detail(scope, selected, include_inactive=include_inactive)
        detail = _rbac_restrict_detail_for_actor(scope, detail, actor)

    return jsonify(
        {
            "scope": scope,
            "scopes": _rbac_scopes(allowed_scopes=allowed_scopes),
            "entities": entities,
            "entities_included": include_entities,
            "include_inactive": include_inactive,
            "selected": selected,
            "detail": detail,
        }
    )


def rbac_explorer_audit():
    scope = request.args.get("scope", "group").strip().lower()
    if scope not in _RBAC_AUDIT_SCOPE_LABELS:
        abort(400, f"invalid scope: {scope}")

    entity = request.args.get("entity", "").strip()
    search = request.args.get("search", "").strip()
    search_field = _rbac_audit_search_field(
        request.args.get("search_field", "all"),
        default="all",
    )
    limit = _rbac_audit_limit()
    if not logic.rbac_audit_table_available():
        return jsonify(
            {
                "scope": scope,
                "selected": entity,
                "search": search,
                "search_field": search_field,
                "limit": limit,
                "count": 0,
                "events": [],
            }
        )

    try:
        rows = _rbac_audit_rows(
            scope,
            entity,
            limit=limit,
            search=search,
            search_field=search_field,
        )
    except SQLAlchemyError:
        model.db.session.rollback()
        current_app.logger.exception("Failed to query RBAC audit feed")
        rows = []
    events = [_rbac_audit_payload(row) for row in rows]

    return jsonify(
        {
            "scope": scope,
            "selected": entity,
            "search": search,
            "search_field": search_field,
            "limit": limit,
            "count": len(events),
            "events": events,
        }
    )


def email_audit_feed():
    scope = request.args.get("scope", "all").strip().lower()
    if scope not in _RBAC_AUDIT_SCOPE_LABELS:
        abort(400, f"invalid scope: {scope}")

    entity = request.args.get("entity", "").strip()
    status = _email_audit_status(request.args.get("status", "all"), default="all")
    issue_state = _email_audit_issue_state(
        request.args.get("issue_state", "all"),
        default="all",
    )
    search = request.args.get("search", "").strip()
    search_field = request.args.get("search_field", "all").strip().lower()
    search_field = _email_audit_search_field(search_field, default="all")
    limit = _email_audit_limit(default=40, max_limit=200)

    if not logic.email_audit_table_available():
        return jsonify(
            {
                "scope": scope,
                "selected": entity,
                "status": status,
                "issue_state": issue_state,
                "search": search,
                "search_field": search_field,
                "limit": limit,
                "count": 0,
                "events": [],
            }
        )

    try:
        rows = _email_audit_rows(
            scope,
            entity,
            limit=limit,
            status=status,
            issue_state=issue_state,
            search=search,
            search_field=search_field,
        )
    except SQLAlchemyError:
        model.db.session.rollback()
        current_app.logger.exception("Failed to query email audit feed")
        rows = []
    events = [_email_audit_payload(row) for row in rows]

    return jsonify(
        {
            "scope": scope,
            "selected": entity,
            "status": status,
            "issue_state": issue_state,
            "search": search,
            "search_field": search_field,
            "limit": limit,
            "count": len(events),
            "events": events,
        }
    )


def app_error_feed():
    actor = request.args.get("actor", "").strip()
    reference_id = request.args.get("reference_id", "").strip()
    exception_type = request.args.get("exception_type", "").strip()
    where_path = request.args.get("where_path", "").strip()
    search = request.args.get("search", "").strip()
    limit = _app_error_limit_from_raw(
        request.args.get("limit", str(logic.APP_ERROR_EVENT_DEFAULT_LIMIT)),
        default=logic.APP_ERROR_EVENT_DEFAULT_LIMIT,
        max_limit=logic.APP_ERROR_EVENT_MAX_LIMIT,
        strict=True,
    )

    if not logic.app_error_event_table_available():
        return jsonify(
            {
                "actor": actor,
                "reference_id": reference_id,
                "exception_type": exception_type,
                "where_path": where_path,
                "search": search,
                "limit": limit,
                "count": 0,
                "events": [],
            }
        )

    try:
        rows = logic.app_error_event_rows(
            limit=limit,
            actor=actor,
            reference_id=reference_id,
            exception_type=exception_type,
            where_path=where_path,
            search=search,
        )
    except SQLAlchemyError:
        model.db.session.rollback()
        current_app.logger.exception("Failed to query app error feed")
        rows = []
    events = [logic.app_error_event_payload(row) for row in rows]

    return jsonify(
        {
            "actor": actor,
            "reference_id": reference_id,
            "exception_type": exception_type,
            "where_path": where_path,
            "search": search,
            "limit": limit,
            "count": len(events),
            "events": events,
        }
    )


def rbac_explorer_mutate():
    actor = _rbac_actor(g.user)
    if not bool(actor.get("can_access")):
        abort(403, "access denied")

    form = logic.CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400, "invalid form submission")

    scope = _rbac_required_form_value("scope").strip().lower()
    if scope not in _RBAC_SCOPE_LABELS:
        abort(400, f"invalid scope: {scope}")
    if not _rbac_actor_allows_scope(actor, scope):
        abort(403, f"scope not allowed: {scope}")
    entity = _rbac_required_form_value("entity")
    payload, status = _rbac_mutate_batch(scope, entity, actor=actor)
    return jsonify(payload), status


def rbac():
    actor = _rbac_actor(g.user)
    if not bool(actor.get("can_access")):
        abort(403, "access denied")

    allowed_scopes = actor.get("allowed_scopes", [])
    if not isinstance(allowed_scopes, list) or len(allowed_scopes) == 0:
        abort(403, "access denied")

    scope = request.args.get("scope", "group").strip().lower()
    if scope not in _RBAC_SCOPE_LABELS or scope not in allowed_scopes:
        scope = allowed_scopes[0]
    entity = request.args.get("entity", "").strip()
    include_inactive = False
    if bool(actor.get("is_admin")):
        include_inactive = _rbac_include_inactive_from_request(False)
    create = request.args.get("create", "").strip().lower()
    if not bool(actor.get("is_admin")) or create not in {"group", "device"}:
        create = ""
    audit_scope = request.args.get("audit_scope", "all").strip().lower()
    if audit_scope not in _RBAC_AUDIT_SCOPE_LABELS:
        audit_scope = "all"
    audit_entity = request.args.get("audit_entity", "").strip()
    audit_search = request.args.get("audit_search", "").strip()
    audit_search_field = _rbac_audit_search_field(
        request.args.get("audit_search_field", "all"),
        default="all",
    )
    audit_limit = _rbac_audit_limit_from_raw(
        request.args.get("audit_limit", str(RBAC_AUDIT_DEFAULT_LIMIT)),
        default=RBAC_AUDIT_DEFAULT_LIMIT,
        max_limit=RBAC_AUDIT_MAX_LIMIT,
        strict=False,
    )
    audit_events = []
    if logic.rbac_audit_table_available():
        try:
            rows = _rbac_audit_rows(
                audit_scope,
                audit_entity,
                limit=audit_limit,
                search=audit_search,
                search_field=audit_search_field,
            )
            audit_events = [_rbac_audit_payload(row) for row in rows]
        except SQLAlchemyError:
            model.db.session.rollback()
            current_app.logger.exception("Failed to query RBAC audit page")
    institutes = logic.get_institutes_datalist()

    return {
        "title": "RBAC",
        "initial_scope": scope,
        "initial_entity": entity,
        "initial_include_inactive": include_inactive,
        "initial_create": create,
        "scope_labels": _rbac_actor_scope_labels(actor),
        "institutes": institutes,
        "can_include_inactive": bool(actor.get("is_admin")),
        "can_create_group": bool(actor.get("is_admin")),
        "can_create_device": bool(actor.get("is_admin")),
        "can_view_audit": bool(actor.get("is_admin")),
        "audit_scope": audit_scope,
        "audit_entity": audit_entity,
        "audit_search": audit_search,
        "audit_search_field": audit_search_field,
        "audit_limit": audit_limit,
        "audit_events": audit_events,
        "audit_scopes": [
            {
                "id": scope_id,
                "label": scope_label,
                "selected": audit_scope == scope_id,
            }
            for scope_id, scope_label in _RBAC_AUDIT_SCOPE_LABELS.items()
        ],
        "rbac_audit_search_field_options": [
            {
                "id": option_id,
                "label": option_label,
                "selected": audit_search_field == option_id,
            }
            for option_id, option_label in _RBAC_AUDIT_SEARCH_FIELD_LABELS.items()
        ],
        "audit_show_more_increment": RBAC_AUDIT_SHOW_MORE_INCREMENT,
        "audit_max_limit": RBAC_AUDIT_MAX_LIMIT,
        "csrf_form": logic.CsrfOnlyForm(),
        **breadcrumb("RBAC"),
    }


def app_issues():
    app_error_actor = request.args.get("app_error_actor", "").strip()
    app_error_reference_id = request.args.get("app_error_reference_id", "").strip()
    app_error_exception_type = request.args.get("app_error_exception_type", "").strip()
    app_error_where_path = request.args.get("app_error_where_path", "").strip()
    app_error_search = request.args.get("app_error_search", "").strip()
    app_error_limit = _app_error_limit_from_raw(
        request.args.get("app_error_limit", str(logic.APP_ERROR_EVENT_DEFAULT_LIMIT)),
        default=logic.APP_ERROR_EVENT_DEFAULT_LIMIT,
        max_limit=logic.APP_ERROR_EVENT_MAX_LIMIT,
        strict=False,
    )
    email_scope = request.args.get("email_scope", "all").strip().lower()
    if email_scope not in _RBAC_AUDIT_SCOPE_LABELS:
        email_scope = "all"
    email_entity = request.args.get("email_entity", "").strip()
    email_status = _email_audit_status(
        request.args.get("email_status", "all"),
        default="all",
    )
    email_issue_state = _email_audit_issue_state(
        request.args.get("email_issue_state", "all"),
        default="all",
    )
    email_search = request.args.get("email_search", "").strip()
    email_search_field = request.args.get("email_search_field", "all").strip().lower()
    email_search_field = _email_audit_search_field(email_search_field, default="all")
    email_limit = _email_audit_limit_from_raw(
        request.args.get("email_limit", str(RBAC_AUDIT_DEFAULT_LIMIT)),
        default=RBAC_AUDIT_DEFAULT_LIMIT,
        max_limit=RBAC_AUDIT_MAX_LIMIT,
        strict=False,
    )
    notification_state_filter = (
        request.args.get("notification_state_filter", "").strip() != ""
        or "notification_include_open" in request.args
        or "notification_include_ignored" in request.args
        or "notification_include_resolved" in request.args
    )
    if notification_state_filter:
        notification_include_open = _request_truthy(
            request.args.get("notification_include_open", ""),
            default=False,
        )
        notification_include_ignored = _request_truthy(
            request.args.get("notification_include_ignored", ""),
            default=False,
        )
        notification_include_resolved = _request_truthy(
            request.args.get("notification_include_resolved", ""),
            default=False,
        )
    else:
        notification_include_open = True
        notification_include_ignored = False
        notification_include_resolved = False
    notification_search = request.args.get("notification_search", "").strip()
    notification_search_field = _notification_incident_search_field(
        request.args.get("notification_search_field", "all"),
        default="all",
    )
    notification_categories = notification_incident_category_values()
    notification_category = request.args.get("notification_category", "all").strip()
    if (
        notification_category != "all"
        and notification_category not in notification_categories
    ):
        notification_category = "all"

    app_error_events: List[Dict[str, Any]] = []
    app_error_events_available = logic.app_error_event_table_available()
    if app_error_events_available:
        try:
            rows = logic.app_error_event_rows(
                limit=app_error_limit,
                actor=app_error_actor,
                reference_id=app_error_reference_id,
                exception_type=app_error_exception_type,
                where_path=app_error_where_path,
                search=app_error_search,
            )
            app_error_events = [logic.app_error_event_payload(row) for row in rows]
        except SQLAlchemyError:
            model.db.session.rollback()
            current_app.logger.exception("Failed to query app error page")

    csp_violation_events: List[Dict[str, Any]] = []
    csp_violation_events_available = logic.csp_violation_event_table_available()
    if csp_violation_events_available:
        try:
            rows = logic.csp_violation_event_rows(
                limit=logic.CSP_VIOLATION_EVENT_DEFAULT_LIMIT
            )
            csp_violation_events = [
                logic.csp_violation_event_payload(row) for row in rows
            ]
        except SQLAlchemyError:
            model.db.session.rollback()
            current_app.logger.exception("Failed to query CSP violation page")

    email_events: List[Dict[str, Any]] = []
    if logic.email_audit_table_available():
        try:
            rows = _email_audit_rows(
                email_scope,
                email_entity,
                limit=email_limit,
                status=email_status,
                issue_state=email_issue_state,
                search=email_search,
                search_field=email_search_field,
            )
            email_events = [_email_audit_payload(row) for row in rows]
        except SQLAlchemyError:
            model.db.session.rollback()
            current_app.logger.exception("Failed to query email audit page")

    notification_incidents_available = logic.notification_incident_table_available()
    if notification_incidents_available:
        potential_issues = notification_incident_rows(
            include_open=notification_include_open,
            include_resolved=notification_include_resolved,
            include_ignored=notification_include_ignored,
            category=notification_category,
            search=notification_search,
            search_field=notification_search_field,
        )
    else:
        potential_issues = _build_potential_issues()
    potential_issue_sections = _build_potential_issue_sections(potential_issues)
    notification_scan_last_updated = notification_scan_last_updated_at()
    notification_return_query = _normalized_return_query(
        request.query_string.decode("utf-8", errors="ignore")
    )
    organization_mapping = logic.get_admin_group_institute_mapping()
    organization_mapping_error = logic.get_admin_group_institute_mapping_error()
    organization_mapping_scan = logic.scan_admin_group_institute_mapping(
        organization_mapping
    )
    organization_history_scan_enabled = _request_truthy(
        request.args.get("organization_history_scan", ""),
        default=False,
    )
    organization_history_window_years = (
        logic.normalize_group_institute_history_window_years(
            request.args.get("organization_history_years", "")
        )
    )
    organization_history_scan = (
        logic.scan_admin_group_institute_schedule_history(
            organization_mapping,
            window_years=organization_history_window_years,
        )
        if organization_history_scan_enabled
        else {"summary": None, "sections": []}
    )

    return {
        "title": "Admin Panel",
        "app_error_events_available": app_error_events_available,
        "app_error_events": app_error_events,
        "csp_violation_events_available": csp_violation_events_available,
        "csp_violation_events": csp_violation_events,
        "app_error_limit": app_error_limit,
        "app_error_actor": app_error_actor,
        "app_error_reference_id": app_error_reference_id,
        "app_error_exception_type": app_error_exception_type,
        "app_error_where_path": app_error_where_path,
        "app_error_search": app_error_search,
        "email_scope": email_scope,
        "email_entity": email_entity,
        "email_limit": email_limit,
        "email_status": email_status,
        "email_issue_state": email_issue_state,
        "email_search": email_search,
        "email_search_field": email_search_field,
        "email_events": email_events,
        "audit_show_more_increment": RBAC_AUDIT_SHOW_MORE_INCREMENT,
        "audit_max_limit": RBAC_AUDIT_MAX_LIMIT,
        "notification_incidents_available": notification_incidents_available,
        "notification_state_filter": notification_state_filter,
        "notification_include_open": notification_include_open,
        "notification_include_resolved": notification_include_resolved,
        "notification_include_ignored": notification_include_ignored,
        "notification_search": notification_search,
        "notification_search_field": notification_search_field,
        "notification_category": notification_category,
        "notification_scan_last_updated": notification_scan_last_updated,
        "notification_return_query": notification_return_query,
        "notification_scan_form": logic.CsrfOnlyForm(),
        "notification_state_form": logic.CsrfOnlyForm(),
        "potential_issue_sections": potential_issue_sections,
        "notification_category_options": [
            {
                "id": "all",
                "label": "all categories",
                "selected": notification_category == "all",
            },
            *[
                {
                    "id": category,
                    "label": category,
                    "selected": notification_category == category,
                }
                for category in notification_categories
            ],
        ],
        "notification_search_field_options": [
            {
                "id": option_id,
                "label": option_label,
                "selected": notification_search_field == option_id,
            }
            for option_id, option_label in NOTIFICATION_INCIDENT_SEARCH_FIELD_LABELS.items()
        ],
        "email_audit_scopes": [
            {
                "id": scope_id,
                "label": scope_label,
                "selected": email_scope == scope_id,
            }
            for scope_id, scope_label in _RBAC_AUDIT_SCOPE_LABELS.items()
        ],
        "email_status_options": [
            {
                "id": option_id,
                "label": option_label,
                "selected": email_status == option_id,
            }
            for option_id, option_label in _EMAIL_AUDIT_STATUS_LABELS.items()
        ],
        "email_issue_state_options": [
            {
                "id": option_id,
                "label": option_label,
                "selected": email_issue_state == option_id,
            }
            for option_id, option_label in _EMAIL_AUDIT_ISSUE_STATE_LABELS.items()
        ],
        "email_search_field_options": [
            {
                "id": option_id,
                "label": option_label,
                "selected": email_search_field == option_id,
            }
            for option_id, option_label in _EMAIL_AUDIT_SEARCH_FIELD_LABELS.items()
        ],
        "admin_config_form": logic.CsrfOnlyForm(),
        "admin_mapping_form": logic.CsrfOnlyForm(),
        "organization_history_scan_form": logic.CsrfOnlyForm(),
        "admin_listserv": logic.get_admin_listserv(),
        "admin_default_sender": logic.get_admin_default_sender(),
        "admin_mailing_lists": logic.format_admin_mailing_lists_for_form(),
        "admin_group_institute_mapping": (
            logic.format_admin_group_institute_mapping_for_form()
        ),
        "admin_group_institute_mapping_error": organization_mapping_error,
        "admin_group_institute_mapping_uses_recommended_default": (
            logic.admin_group_institute_mapping_uses_recommended_default()
        ),
        "admin_settings_available": logic.admin_settings_available(),
        "admin_mapping_kinds": _admin_mapping_kinds(),
        "organization_mapping_summary": organization_mapping_scan["summary"],
        "organization_mapping_issue_sections": organization_mapping_scan["sections"],
        "organization_history_scan_enabled": organization_history_scan_enabled,
        "organization_history_scan_window_years": organization_history_window_years,
        "organization_history_scan_window_years_max": (
            logic.GROUP_INSTITUTE_HISTORY_WINDOW_MAX_YEARS
        ),
        "organization_history_scan_summary": organization_history_scan["summary"],
        "organization_history_issue_sections": organization_history_scan["sections"],
        **breadcrumb(("RBAC", url_for("rbac")), "Admin Panel"),
    }


def app_issues_config():
    form = logic.CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400, "invalid form submission")

    if not logic.admin_settings_available():
        flash(
            "Admin configuration storage is unavailable. Run database migrations.",
            "error",
        )
        return _app_issues_redirect(request.form.get("return_query", ""))

    listserv = (request.form.get("admin_listserv", "") or "").strip()
    default_sender = (request.form.get("admin_default_sender", "") or "").strip()
    mailing_lists_raw = request.form.get("admin_mailing_lists", "")
    group_institute_mapping_raw = request.form.get("admin_group_institute_mapping", "")

    try:
        mailing_lists = logic.parse_admin_mailing_lists(mailing_lists_raw)
        group_institute_mapping = logic.parse_admin_group_institute_mapping(
            group_institute_mapping_raw
        )
    except ValueError as ex:
        flash(str(ex), "error")
        return _app_issues_redirect(request.form.get("return_query", ""))

    if listserv == "":
        flash("listserv is required", "error")
        return _app_issues_redirect(request.form.get("return_query", ""))
    if default_sender != "" and "@" not in default_sender:
        flash("default sender must be an email address", "error")
        return _app_issues_redirect(request.form.get("return_query", ""))

    actor_id = g.user.id if g.user is not None else "unknown"
    try:
        logic.set_admin_listserv(listserv, updated_by=actor_id)
        logic.set_admin_default_sender(default_sender, updated_by=actor_id)
        logic.set_admin_mailing_lists(mailing_lists, updated_by=actor_id)
        logic.set_admin_group_institute_mapping(
            group_institute_mapping, updated_by=actor_id
        )
        model.db.session.commit()
        flash("admin configuration updated", "message")
    except SQLAlchemyError:
        model.db.session.rollback()
        current_app.logger.exception("Failed to persist admin config update")
        flash("failed to save admin configuration", "error")
    return _app_issues_redirect(request.form.get("return_query", ""))


def app_issues_import_mapping():
    form = logic.CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400, "invalid form submission")

    mapping_kind = (request.form.get("mapping_kind", "") or "").strip()
    if mapping_kind not in {"user-dept", "dev-dept", "devperm"}:
        flash("invalid mapping kind", "error")
        return _app_issues_redirect(request.form.get("return_query", ""))

    mapping_text = request.form.get("mapping_text", "")
    file = request.files.get("mapping_file")
    if (mapping_text or "").strip() == "" and file is None:
        flash("mapping CSV text or file is required", "error")
        return _app_issues_redirect(request.form.get("return_query", ""))

    try:
        if (mapping_text or "").strip() != "":
            raw_rows = logic.parse_admin_mapping_text(mapping_kind, mapping_text)
        else:
            raw_rows = logic.parse_admin_mapping_file(mapping_kind, file)
        rows = logic.validate_import_rows(mapping_kind, raw_rows)
        applied_count = logic.apply_import_rows(mapping_kind, rows)
        model.db.session.commit()
    except ValueError as ex:
        model.db.session.rollback()
        flash(str(ex), "error")
        return _app_issues_redirect(request.form.get("return_query", ""))
    except SQLAlchemyError:
        model.db.session.rollback()
        current_app.logger.exception("Failed to persist admin mapping import")
        flash("failed to import mapping data", "error")
        return _app_issues_redirect(request.form.get("return_query", ""))

    _record_rbac_action(
        action="admin.mapping.import",
        where="/app/issues",
        how="admin-panel",
        what=f"kind={mapping_kind}, rows={applied_count}",
    )
    flash(f"imported {applied_count} rows into {mapping_kind}", "message")
    return _app_issues_redirect(request.form.get("return_query", ""))


def app_issues_export_mapping(mapping_kind):
    if mapping_kind == "organization-issues":
        include_recent_history = _request_truthy(
            request.args.get("organization_history_scan", ""),
            default=False,
        )
        organization_history_window_years = (
            logic.normalize_group_institute_history_window_years(
                request.args.get("organization_history_years", "")
            )
        )
        headers, rows = logic.export_group_institute_issue_rows(
            include_recent_history=include_recent_history,
            window_years=organization_history_window_years,
        )
        filename = (
            "organization-issues-recent-history.csv"
            if include_recent_history
            else "organization-issues.csv"
        )
    elif mapping_kind in {"user-dept", "dev-dept", "devperm"}:
        try:
            headers, rows = logic.export_mapping_rows(mapping_kind)
        except ValueError as ex:
            abort(400, str(ex))
        filename = f"{mapping_kind}.csv"
    else:
        abort(400, "invalid mapping kind")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(list(headers))
    writer.writerows(rows)
    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Cache-Control"] = "no-store"
    return response


def app_issues_organization_history_scan():
    form = logic.CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400, "invalid form submission")

    return_query = request.form.get("return_query", "")
    enabled = _request_truthy(request.form.get("enabled", ""), default=True)
    organization_history_window_years = (
        logic.normalize_group_institute_history_window_years(
            request.form.get("organization_history_years", "")
        )
    )
    _record_rbac_action(
        action="organization.history.scan.toggle",
        where="/app/issues",
        how="admin-panel",
        what=(f"enabled={enabled}, window_years={organization_history_window_years}"),
    )
    try:
        model.db.session.commit()
    except SQLAlchemyError:
        model.db.session.rollback()
        current_app.logger.exception(
            "Failed to persist organization history scan audit"
        )
    return _app_issues_redirect(
        _app_issues_query_with_updates(
            return_query,
            {
                "organization_history_scan": "1" if enabled else None,
                "organization_history_years": str(organization_history_window_years),
            },
        )
    )


def app_issues_scan():
    form = logic.CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400, "invalid form submission")

    return_query = request.form.get("return_query", "")
    if not logic.notification_incident_table_available():
        return _app_issues_redirect(return_query)

    stats = run_notification_detection_scan()
    _record_rbac_action(
        action="notifications.scan.run",
        where="/app/issues",
        how="admin-panel",
        what=(
            f"detected={stats['detected']}, created={stats['created']}, "
            f"reopened={stats['reopened']}, ignore_expired={stats['ignore_expired']}, "
            f"auto_resolved={stats['auto_resolved']}, expired={stats['expired']}"
        ),
    )
    try:
        model.db.session.commit()
    except SQLAlchemyError:
        model.db.session.rollback()
        current_app.logger.exception("Failed to persist notification detection scan")
    return _app_issues_redirect(return_query)


def app_issues_notification_state():
    form = logic.CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400, "invalid form submission")

    return_query = request.form.get("return_query", "")
    issue_key = request.form.get("issue_key", "").strip()
    target_state = request.form.get("target_state", "").strip().lower()
    note = request.form.get("note", "").strip()
    ignored_until_raw = request.form.get("ignored_until", "").strip()
    ignored_until = None

    if target_state == "ignored" and ignored_until_raw != "":
        try:
            ignored_until_date = datetime.date.fromisoformat(ignored_until_raw)
        except ValueError:
            abort(400, "ignored_until must be a valid date")
        ignored_until = datetime.datetime.combine(
            ignored_until_date,
            datetime.time(23, 59, 59),
            tzinfo=datetime.timezone.utc,
        )

    actor_id = g.user.id if g.user is not None else "unknown"
    try:
        updated = set_notification_incident_state(
            issue_key=issue_key,
            target_state=target_state,
            note=note,
            actor=actor_id,
            ignored_until=ignored_until,
        )
    except ValueError as ex:
        abort(400, str(ex))

    if not updated:
        abort(404, "incident not found")

    ignored_until_label = ignored_until_raw if ignored_until_raw != "" else "-"
    _record_rbac_action(
        action="notifications.incident.state.update",
        where="/app/issues",
        how="admin-panel",
        what=(
            f"issue_key={issue_key}, target_state={target_state}, "
            f"ignored_until={ignored_until_label}, note={note}"
        ),
    )
    try:
        model.db.session.commit()
    except SQLAlchemyError:
        model.db.session.rollback()
        current_app.logger.exception("Failed to persist notification incident state")
    return _app_issues_redirect(return_query)


def register_rbac_blueprint(
    app,
    *,
    active_user_required: Callable[[Callable[..., Any]], Callable[..., Any]],
    admin_only: Callable[[Callable[..., Any]], Callable[..., Any]],
    render_to: Callable[[str], Callable[[Callable[..., Any]], Callable[..., Any]]],
    breadcrumb_fn: Callable[..., Breadcrumb_links],
    subpage_nav_fn: Callable[[str, List[Tuple[bool, str, str]]], Subpage_links],
) -> None:
    global _breadcrumb_fn, _subpage_nav_fn
    _breadcrumb_fn = breadcrumb_fn
    _subpage_nav_fn = subpage_nav_fn

    @app.before_request
    def _rbac_profile_before_request() -> None:
        _rbac_profile_start_request()

    @app.after_request
    def _rbac_profile_after_request(response):
        return _rbac_profile_finish_request(response)

    @app.teardown_request
    def _rbac_profile_teardown_request(_exc: Optional[BaseException]) -> None:
        _rbac_profile_cleanup_state()

    app.add_url_rule(
        "/json/v1/rbac/explorer",
        view_func=active_user_required(rbac_explorer_data),
    )

    app.add_url_rule(
        "/json/v1/rbac/audit",
        view_func=admin_only(rbac_explorer_audit),
    )

    app.add_url_rule(
        "/json/v1/email/audit",
        view_func=admin_only(email_audit_feed),
    )

    app.add_url_rule(
        "/json/v1/app-errors",
        view_func=admin_only(app_error_feed),
    )

    app.add_url_rule(
        "/json/v1/rbac/mutate",
        methods=["POST"],
        view_func=active_user_required(rbac_explorer_mutate),
    )

    app.add_url_rule(
        "/rbac",
        view_func=active_user_required(render_to("rbac")(rbac)),
    )

    app.add_url_rule(
        "/app/issues/notifications/scan",
        methods=["POST"],
        view_func=admin_only(app_issues_scan),
    )

    app.add_url_rule(
        "/app/issues/notifications/state",
        methods=["POST"],
        view_func=admin_only(app_issues_notification_state),
    )

    app.add_url_rule(
        "/app/issues/organization/history-scan",
        methods=["POST"],
        view_func=admin_only(app_issues_organization_history_scan),
    )

    app.add_url_rule(
        "/app/issues",
        view_func=admin_only(render_to("rbac_audit")(app_issues)),
    )

    app.add_url_rule(
        "/app/issues/config",
        methods=["POST"],
        view_func=admin_only(app_issues_config),
    )

    app.add_url_rule(
        "/app/issues/mapping/import",
        methods=["POST"],
        view_func=admin_only(app_issues_import_mapping),
    )

    app.add_url_rule(
        "/app/issues/mapping/export/<mapping_kind>",
        view_func=admin_only(app_issues_export_mapping),
    )
