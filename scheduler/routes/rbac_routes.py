from __future__ import annotations

from typing import Any, Callable, List, Tuple

from flask import abort, current_app, g, jsonify, request, url_for
from sqlalchemy.exc import SQLAlchemyError

import scheduler.logic.admin_config as logic
import scheduler.logic.app_error_events as app_error_logic
import scheduler.logic.core as core_logic
import scheduler.logic.csp_violation_events as csp_logic
import scheduler.logic.rbac_audit_support as audit_logic
import scheduler.logic.schedule_editor as schedule_logic
from scheduler import model

from ._rbac_admin_actions import (
    app_issues_config,
    app_issues_export_mapping,
    app_issues_import_mapping,
    app_issues_notification_state,
    app_issues_organization_history_scan,
    app_issues_run_backup,
    app_issues_run_restore_drill,
    app_issues_scan,
)
from ._rbac_explorer_core import (
    _RBAC_AUDIT_SCOPE_LABELS,
    _RBAC_SCOPE_LABELS,
    _rbac_actor,
    _rbac_actor_allows_scope,
    _rbac_actor_scope_labels,
    _rbac_detail,
    _rbac_empty_detail,
    _rbac_entities_for_actor,
    _rbac_entity_visible_for_actor,
    _rbac_scopes,
)
from ._rbac_profile import register_rbac_profile_hooks
from ._rbac_route_support import (
    Breadcrumb_links,
    Subpage_links,
    _admin_mapping_kinds,
    _app_error_limit_from_raw,
    _normalized_return_query,
    _request_truthy,
    audit_rbac_action,
    breadcrumb,
    configure_rbac_route_helpers,
)
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
from .rbac_explorer_serialization import _rbac_restrict_detail_for_actor
from .rbac_issues import (
    NOTIFICATION_INCIDENT_SEARCH_FIELD_LABELS,
    _build_potential_issue_sections,
    _build_potential_issues,
    _notification_incident_search_field,
    notification_incident_category_values,
    notification_incident_rows,
    notification_scan_last_updated_at,
)
from .rbac_mutations import _rbac_mutate_batch, _rbac_required_form_value

__all__ = ["audit_rbac_action", "register_rbac_blueprint"]


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
    if not audit_logic.rbac_audit_table_available():
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

    if not audit_logic.email_audit_table_available():
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
        request.args.get("limit", str(app_error_logic.APP_ERROR_EVENT_DEFAULT_LIMIT)),
        default=app_error_logic.APP_ERROR_EVENT_DEFAULT_LIMIT,
        max_limit=app_error_logic.APP_ERROR_EVENT_MAX_LIMIT,
        strict=True,
    )

    if not app_error_logic.app_error_event_table_available():
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
        rows = app_error_logic.app_error_event_rows(
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
    events = [app_error_logic.app_error_event_payload(row) for row in rows]

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

    form = schedule_logic.CsrfOnlyForm()
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
    if audit_logic.rbac_audit_table_available():
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
    institutes = core_logic.get_institutes_datalist()

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
        "csrf_form": schedule_logic.CsrfOnlyForm(),
        **breadcrumb("RBAC"),
    }


def app_issues():
    app_error_actor = request.args.get("app_error_actor", "").strip()
    app_error_reference_id = request.args.get("app_error_reference_id", "").strip()
    app_error_exception_type = request.args.get("app_error_exception_type", "").strip()
    app_error_where_path = request.args.get("app_error_where_path", "").strip()
    app_error_search = request.args.get("app_error_search", "").strip()
    app_error_limit = _app_error_limit_from_raw(
        request.args.get(
            "app_error_limit", str(app_error_logic.APP_ERROR_EVENT_DEFAULT_LIMIT)
        ),
        default=app_error_logic.APP_ERROR_EVENT_DEFAULT_LIMIT,
        max_limit=app_error_logic.APP_ERROR_EVENT_MAX_LIMIT,
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

    app_error_events: List[dict[str, Any]] = []
    app_error_events_available = app_error_logic.app_error_event_table_available()
    if app_error_events_available:
        try:
            rows = app_error_logic.app_error_event_rows(
                limit=app_error_limit,
                actor=app_error_actor,
                reference_id=app_error_reference_id,
                exception_type=app_error_exception_type,
                where_path=app_error_where_path,
                search=app_error_search,
            )
            app_error_events = [
                app_error_logic.app_error_event_payload(row) for row in rows
            ]
        except SQLAlchemyError:
            model.db.session.rollback()
            current_app.logger.exception("Failed to query app error page")

    csp_violation_events: List[dict[str, Any]] = []
    csp_violation_events_available = csp_logic.csp_violation_event_table_available()
    if csp_violation_events_available:
        try:
            rows = csp_logic.csp_violation_event_rows(
                limit=csp_logic.CSP_VIOLATION_EVENT_DEFAULT_LIMIT
            )
            csp_violation_events = [
                csp_logic.csp_violation_event_payload(row) for row in rows
            ]
        except SQLAlchemyError:
            model.db.session.rollback()
            current_app.logger.exception("Failed to query CSP violation page")

    email_events: List[dict[str, Any]] = []
    if audit_logic.email_audit_table_available():
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

    notification_incidents_available = (
        audit_logic.notification_incident_table_available()
    )
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
    admin_backup_config = logic.get_admin_backup_operations_config()
    admin_restore_config = logic.get_admin_restore_drill_operations_config()
    operations_status = logic.collect_admin_operations_status()

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
        "notification_scan_form": schedule_logic.CsrfOnlyForm(),
        "notification_state_form": schedule_logic.CsrfOnlyForm(),
        "admin_backup_form": schedule_logic.CsrfOnlyForm(),
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
        "admin_config_form": schedule_logic.CsrfOnlyForm(),
        "admin_mapping_form": schedule_logic.CsrfOnlyForm(),
        "admin_restore_form": schedule_logic.CsrfOnlyForm(),
        "organization_history_scan_form": schedule_logic.CsrfOnlyForm(),
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
        "admin_ops_backup_enabled": admin_backup_config.enabled,
        "admin_ops_backup_directory": admin_backup_config.directory,
        "admin_ops_backup_format": admin_backup_config.format,
        "admin_ops_backup_retention_count": admin_backup_config.retention_count,
        "admin_ops_backup_max_age_hours": admin_backup_config.max_age_hours,
        "admin_ops_backup_min_free_gb": admin_backup_config.min_free_gb,
        "admin_ops_restore_enabled": admin_restore_config.enabled,
        "admin_ops_restore_interval_days": admin_restore_config.interval_days,
        "admin_operations_status": operations_status,
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


def register_rbac_blueprint(
    app,
    *,
    active_user_required: Callable[[Callable[..., Any]], Callable[..., Any]],
    admin_only: Callable[[Callable[..., Any]], Callable[..., Any]],
    render_to: Callable[[str], Callable[[Callable[..., Any]], Callable[..., Any]]],
    breadcrumb_fn: Callable[..., Breadcrumb_links],
    subpage_nav_fn: Callable[[str, List[Tuple[bool, str, str]]], Subpage_links],
) -> None:
    configure_rbac_route_helpers(
        breadcrumb_fn=breadcrumb_fn,
        subpage_nav_fn=subpage_nav_fn,
    )
    register_rbac_profile_hooks(app)

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
        "/app/issues/operations/backup",
        methods=["POST"],
        view_func=admin_only(app_issues_run_backup),
    )

    app.add_url_rule(
        "/app/issues/operations/restore-drill",
        methods=["POST"],
        view_func=admin_only(app_issues_run_restore_drill),
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
