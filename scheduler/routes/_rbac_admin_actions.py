from __future__ import annotations

import csv
import datetime
import io

from flask import Response, abort, current_app, flash, g, request
from sqlalchemy.exc import SQLAlchemyError

import scheduler.logic.admin_config as logic
import scheduler.logic.rbac_audit_support as audit_logic
import scheduler.logic.schedule_editor as schedule_logic
from scheduler import model

from ._rbac_route_support import (
    _app_issues_query_with_updates,
    _app_issues_redirect,
    _record_rbac_action,
    _request_truthy,
)
from .rbac_issues import (
    run_notification_detection_scan,
    set_notification_incident_state,
)


def app_issues_config():
    form = schedule_logic.CsrfOnlyForm()
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
        backup_config, restore_config = logic.parse_admin_operations_form(request.form)
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
        logic.set_admin_operations_config(
            backup_config,
            restore_config,
            updated_by=actor_id,
        )
        model.db.session.commit()
        flash("admin configuration updated", "message")
    except SQLAlchemyError:
        model.db.session.rollback()
        current_app.logger.exception("Failed to persist admin config update")
        flash("failed to save admin configuration", "error")
    return _app_issues_redirect(request.form.get("return_query", ""))


def _compact_detail(value: str, *, limit: int = 240) -> str:
    normalized = " ".join((value or "").split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3]}..."


def _admin_operation_audit_detail(result: logic.AdminOperationResult) -> str:
    parts = [f"status={result.status}"]
    if result.backup_path:
        parts.append(f"backup_path={result.backup_path}")
    if result.backup_format:
        parts.append(f"backup_format={result.backup_format}")
    if result.size_bytes is not None:
        parts.append(f"size_bytes={result.size_bytes}")
    if result.database_name:
        parts.append(f"database_name={result.database_name}")
    if result.duration_seconds is not None:
        parts.append(f"duration_seconds={round(float(result.duration_seconds), 3)}")
    if result.next_due_at:
        parts.append(f"next_due_at={result.next_due_at}")
    if result.detail:
        parts.append(f"detail={_compact_detail(result.detail)}")
    return ", ".join(parts)


def _flash_admin_operation_result(
    *,
    success_label: str,
    error_label: str,
    result: logic.AdminOperationResult,
) -> None:
    if result.status == "ok":
        flash(f"{success_label}: {result.detail}", "message")
        return
    if result.status == "skipped":
        flash(result.detail, "message")
        return
    flash(f"{error_label}: {result.detail}", "error")


def app_issues_run_backup():
    form = schedule_logic.CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400, "invalid form submission")

    return_query = request.form.get("return_query", "")
    if not logic.admin_settings_available():
        flash(
            "Admin configuration storage is unavailable. Run database migrations.",
            "error",
        )
        return _app_issues_redirect(return_query)

    actor_id = g.user.id if g.user is not None else "unknown"
    result = logic.run_backup_operation(force=True, updated_by=actor_id)
    _record_rbac_action(
        action="operations.backup.run",
        where="/app/issues",
        how="admin-panel",
        what=_admin_operation_audit_detail(result),
    )
    try:
        model.db.session.commit()
    except SQLAlchemyError:
        model.db.session.rollback()
        current_app.logger.exception("Failed to persist manual backup execution")
        flash(
            "backup run completed but the app could not save status or audit details",
            "error",
        )
        return _app_issues_redirect(return_query)

    _flash_admin_operation_result(
        success_label="backup completed",
        error_label="backup failed",
        result=result,
    )
    return _app_issues_redirect(return_query)


def app_issues_run_restore_drill():
    form = schedule_logic.CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400, "invalid form submission")

    return_query = request.form.get("return_query", "")
    if not logic.admin_settings_available():
        flash(
            "Admin configuration storage is unavailable. Run database migrations.",
            "error",
        )
        return _app_issues_redirect(return_query)

    actor_id = g.user.id if g.user is not None else "unknown"
    result = logic.run_restore_drill_operation(force=True, updated_by=actor_id)
    _record_rbac_action(
        action="operations.restore_drill.run",
        where="/app/issues",
        how="admin-panel",
        what=_admin_operation_audit_detail(result),
    )
    try:
        model.db.session.commit()
    except SQLAlchemyError:
        model.db.session.rollback()
        current_app.logger.exception("Failed to persist manual restore drill execution")
        flash(
            "restore drill completed but the app could not save status or audit details",
            "error",
        )
        return _app_issues_redirect(return_query)

    _flash_admin_operation_result(
        success_label="restore drill completed",
        error_label="restore drill failed",
        result=result,
    )
    return _app_issues_redirect(return_query)


def app_issues_import_mapping():
    form = schedule_logic.CsrfOnlyForm()
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
    form = schedule_logic.CsrfOnlyForm()
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
    form = schedule_logic.CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400, "invalid form submission")

    return_query = request.form.get("return_query", "")
    if not audit_logic.notification_incident_table_available():
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
    form = schedule_logic.CsrfOnlyForm()
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
