from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from flask import Response, abort, current_app, flash, g, request, url_for
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

import scheduler.logic.core as logic
import scheduler.logic.notifications as notification_logic
import scheduler.logic.rbac_audit_support as audit_logic
import scheduler.logic.schedule_editor as schedule_logic
from scheduler import model
from scheduler.auth.test_session_state import (
    get_auth_test_session_pi_groups,
    has_auth_test_session_pi_group,
)

BreadcrumbLinks = Dict[str, List[Tuple[str, str]]]
SubpageLinks = Dict[str, Dict[str, Union[str, List[Tuple[str, str]]]]]

_my_url_fn: Optional[Callable[[], str]] = None
_to_fn: Optional[Callable[..., Any]] = None
_breadcrumb_fn: Optional[Callable[..., BreadcrumbLinks]] = None
_subpage_nav_fn: Optional[
    Callable[[str, List[Tuple[bool, str, str]]], SubpageLinks]
] = None
_audit_rbac_action_fn: Optional[Callable[..., None]] = None


def _require_helper(
    helper: Optional[Callable[..., Any]], name: str
) -> Callable[..., Any]:
    if helper is None:
        raise RuntimeError(f"Core route helper not configured: {name}")
    return helper


def my_url() -> str:
    return _require_helper(_my_url_fn, "my_url")()


def to(page: str, **kwargs: Any) -> Any:
    return _require_helper(_to_fn, "to")(page, **kwargs)


def breadcrumb(*routes: Union[str, Tuple[str, str]]) -> BreadcrumbLinks:
    return _require_helper(_breadcrumb_fn, "breadcrumb")(*routes)


def subpage_nav(title: str, links: List[Tuple[bool, str, str]]) -> SubpageLinks:
    return _require_helper(_subpage_nav_fn, "subpage_nav")(title, links)


def audit_rbac_action(action: str, where: str, how: str, what: str) -> None:
    _require_helper(_audit_rbac_action_fn, "audit_rbac_action")(
        action=action,
        where=where,
        how=how,
        what=what,
    )


def _cached_memberships() -> List[str]:
    user = getattr(g, "user", None)
    user_id = str(getattr(user, "id", "") or "").strip()
    if user_id == "":
        return []
    if not bool(getattr(user, "active", False)):
        return []
    memberships = getattr(g, "_cached_memberships", None)
    cached_user_id = str(getattr(g, "_cached_memberships_user_id", "") or "").strip()
    if memberships is not None and cached_user_id == user_id:
        return memberships
    memberships = logic.get_memberships(user)
    g._cached_memberships = memberships
    g._cached_memberships_user_id = user_id
    return memberships


def _request_bool_cache(name: str) -> Dict[str, bool]:
    try:
        cache = getattr(g, name, None)
    except RuntimeError:
        return {}
    if isinstance(cache, dict):
        return cache
    cache = {}
    setattr(g, name, cache)
    return cache


def _cached_show_tech_join_form(user) -> bool:
    user_id = str(getattr(user, "id", "") or "").strip()
    if user_id == "":
        return False

    cache = _request_bool_cache("_cached_show_tech_join_form_by_user")
    cached = cache.get(user_id)
    if cached is not None:
        return bool(cached)

    user_record = user
    if not isinstance(user_record, model.User):
        user_record = logic.get_user(user_id)
        if user_record is None:
            cache[user_id] = False
            return False

    value = bool(logic.show_tech_join_form(user_record))
    cache[user_id] = value
    return value


def _cached_is_admin() -> bool:
    user = getattr(g, "user", None)
    if user is None or not bool(getattr(user, "active", False)):
        return False
    is_admin = getattr(g, "_cached_is_admin", None)
    if is_admin is None:
        memberships = _cached_memberships()
        is_admin = "admin" in memberships
        g._cached_is_admin = is_admin
    return is_admin


def _home_device_permissions(
    devices: List[model.Device],
) -> Dict[str, Dict[str, object]]:
    user = getattr(g, "user", None)
    device_permissions: Dict[str, Dict[str, object]] = {}
    device_ids = [str(getattr(device, "id", "")).strip() for device in devices]
    device_id_set = {device_id for device_id in device_ids if device_id}

    if not device_id_set:
        return device_permissions

    user_id = str(getattr(user, "id", "") or "").strip()
    if not user_id:
        for device_id in device_id_set:
            device_permissions[device_id] = {"can_edit": False, "extra_privileges": []}
        return device_permissions

    if not bool(getattr(user, "active", False)):
        for device_id in device_id_set:
            device_permissions[device_id] = {"can_edit": False, "extra_privileges": []}
        return device_permissions

    memberships = _cached_memberships()
    is_admin = "admin" in memberships

    is_dev_pi = False
    if not is_admin and "DEV" in memberships:
        is_dev_pi = has_auth_test_session_pi_group(user_id, "DEV")
        if not is_dev_pi:
            membership = model.Membership
            dev_pi_statement = (
                select(membership.user)
                .where(membership.user == user_id)
                .where(membership.group == "DEV")
                .where(membership.pi)
                .where(membership.approved)
                .where(membership.user_active)
                .where(membership.group_active)
            )
            is_dev_pi = model.db.session.scalar(dev_pi_statement) is not None

    if is_admin or is_dev_pi:
        for device_id in device_id_set:
            device_permissions[device_id] = {"can_edit": True, "extra_privileges": []}
        return device_permissions

    editable_device_ids = set()
    if memberships:
        editable_device_statement = select(model.DeviceGroup.device).where(
            model.DeviceGroup.group.in_(memberships)
        )
        editable_device_ids = {
            device_id
            for device_id in model.db.session.scalars(editable_device_statement).all()
            if device_id in device_id_set
        }

    user_device_statement = (
        select(model.UserDevice)
        .where(model.UserDevice.user == user_id)
        .where(model.UserDevice.device.in_(device_id_set))
    )
    user_devices = {
        row.device: row for row in model.db.session.scalars(user_device_statement).all()
    }

    for device_id in device_id_set:
        user_device = user_devices.get(device_id)
        perms = logic.DevicePerms(
            False,
            False,
            device_id in editable_device_ids,
            user_device,
        )
        extra_privileges = []
        if user_device is not None and user_device.templates:
            extra_privileges.append("templates")
        if user_device is not None and user_device.slot:
            extra_privileges.append("slot")
        if user_device is not None and user_device.tech:
            extra_privileges.append("technologist")
        if user_device is not None and user_device.medical:
            extra_privileges.append("medical")
        if user_device is not None and user_device.training:
            extra_privileges.append("training")

        device_permissions[device_id] = {
            "can_edit": perms.edit,
            "extra_privileges": extra_privileges,
        }

    return device_permissions


def _rbac_user_is_group_pi(user: model.User) -> bool:
    if not bool(getattr(user, "active", False)):
        return False
    user_id = str(getattr(user, "id", "") or "").strip()
    if user_id == "":
        return False

    cache = _request_bool_cache("_cached_rbac_group_pi_by_user")
    cached = cache.get(user_id)
    if cached is not None:
        return bool(cached)

    value = len(get_auth_test_session_pi_groups(user_id)) > 0
    if not value:
        membership = model.Membership
        group_pi_statement = (
            select(membership.user)
            .where(membership.user == user_id)
            .where(membership.user_active)
            .where(membership.approved)
            .where(membership.pi)
            .where(membership.group_active)
        )
        value = model.db.session.scalar(group_pi_statement) is not None
    cache[user_id] = bool(value)
    return value


def _rbac_user_can_access(
    user: Optional[model.User], *, is_admin: Optional[bool] = None
) -> bool:
    if user is None or not user.active:
        return False

    if is_admin is None:
        if user is g.user:
            is_admin = _cached_is_admin()
        else:
            is_admin = logic.is_admin(user)
    if is_admin:
        return True
    return _rbac_user_is_group_pi(user)


def inject_template_context():
    """Provide shared template context values."""

    user = getattr(g, "user", None)
    menu_links: List[Tuple[str, str, str]] = []
    admin_menu_links: List[Tuple[str, str, str]] = []

    if user is not None:
        is_admin_user = _cached_is_admin() if user is g.user else logic.is_admin(user)
        menu_links.append(("email", url_for("mailing_lists"), "email"))
        if user.active:
            menu_links.insert(0, ("join form", url_for("join_form"), "form"))
            if _cached_show_tech_join_form(user):
                menu_links.append(
                    ("technologist join form", url_for("join_form_tech"), "form")
                )
        if _rbac_user_can_access(user, is_admin=is_admin_user):
            admin_menu_links.append(("RBAC", url_for("rbac"), "rbac"))
        if is_admin_user:
            admin_menu_links.append(("Admin Panel", url_for("app_issues"), "admin"))

    return {
        "logout_form": schedule_logic.CsrfOnlyForm(),
        "csp_nonce": getattr(g, "csp_nonce", ""),
        "user_menu_links": menu_links,
        "admin_menu_links": admin_menu_links,
    }


def robots():
    return Response("User-agent: *\nDisallow: /", mimetype="text/plain")


def home():
    devices = logic.get_devices(active=True)
    groups: List[model.Group] = []
    show_groups = g.user.active

    if show_groups:
        memberships = _cached_memberships()
        is_admin = "admin" in memberships
        if is_admin:
            groups = logic.get_all_groups_with_members(active=True)
        else:
            groups = logic.get_groups(memberships)

    return {
        "devices": devices,
        "groups": groups,
        "show_groups": show_groups,
        "device_permissions": _home_device_permissions(devices),
        **breadcrumb(),
    }


def mailing_lists():
    form = notification_logic.get_mailing_list_form(name=g.user.label, addr=g.user.addr)
    if form.validate_on_submit():
        notification_logic.process_mailing_list_form_submissions(form)
        try:
            model.db.session.commit()
        except SQLAlchemyError:
            model.db.session.rollback()
            current_app.logger.exception(
                "Failed to commit email audit records for mailing-list update"
            )
        flash("your mailing list subscription status has been updated")
        return to("home")
    return {
        "form": form,
        "action": my_url(),
        **breadcrumb("email"),
    }


def join_form_subnav(user: model.User) -> SubpageLinks:
    return subpage_nav(
        "forms",
        [
            (True, "join form", url_for("join_form")),
            (
                _cached_show_tech_join_form(user),
                "technologist join form",
                url_for("join_form_tech"),
            ),
        ],
    )


def join_form_breadcrumb() -> BreadcrumbLinks:
    return breadcrumb(("join form", url_for("join_form")))


def join_form():
    departments = notification_logic.get_departments_for_join_form(g.user)
    form = logic.JoinForm(departments)
    no_departments = len(departments) == 0
    if form.validate_on_submit():
        if logic.record_join_form(form, g.user, form.group.data):
            notify_state = notification_logic.notify_group_pi_of_join_form(
                g.user, form.group.data
            )
            request_row = model.db.session.get(
                model.GroupMember, (form.group.data, g.user.id)
            )
            if request_row is not None and request_row.approved is None:
                request_row.email_status = notify_state
                model.db.session.add(request_row)
                model.db.session.commit()
            audit_rbac_action(
                action="group.join.request",
                where=f"/join/{form.group.data}",
                how="email",
                what=f"group={form.group.data}, email_status={notify_state}",
            )
            flash("your membership request is being processed")
            return to("home")
    return {
        "form": form,
        "action": my_url(),
        "no_departments": no_departments,
        **join_form_subnav(g.user),
        **join_form_breadcrumb(),
    }


def join_form_tech():
    if not _cached_show_tech_join_form(g.user):
        abort(
            403,
            "Only DEV members who have not become technologists already may access this form",
        )
    form = schedule_logic.CsrfOnlyForm()
    if form.validate_on_submit():
        request_row = logic.record_tech_join_request(g.user)
        logic.handle_tech_join_request(True, request_row)
        request_row.email_status = audit_logic.EMAIL_STATUS_NONE
        model.db.session.add(request_row)
        model.db.session.commit()
        audit_rbac_action(
            action="group.join.tech.autoapprove",
            where="/join/tech",
            how="form",
            what=f"user={g.user.id}, group=DEV, approved=true",
        )
        notification_logic.notify_dev_pi_of_tech_autoapproval(g.user)
        notification_logic.notify_user_of_tech_join_request_outcome(True, g.user)
        try:
            model.db.session.commit()
        except SQLAlchemyError:
            model.db.session.rollback()
            current_app.logger.exception(
                "Failed to commit email audit records for technologist auto-approval"
            )
        flash("your technologist access has been approved")
        return to("home")
    return {
        "form": form,
        **join_form_subnav(g.user),
        **join_form_breadcrumb(),
    }


def handle_join_group(token):
    signed = audit_logic.read_signed_message(token)

    if (
        signed is None
        or len(signed) != 3
        or signed[0] not in {"join-group", "join-tech"}
    ):
        abort(400)

    request_type, uid, gid = signed
    user = logic.get_user(uid)
    if user is None or not user.active:
        abort(400)
    group = logic.get_group(gid)
    if group is None or not group.active:
        abort(400)

    if request_type == "join-group":
        request_row = logic.get_join_request(user, group)
        if request_row is None:
            flash("this request was previously denied")
            return to("home")

        if request_row.approved is not None:
            flash("this request was previously approved")
            return to("home")
    else:
        request_row = logic.get_pending_tech_join_request(user)
        if request_row is None:
            if logic.is_technologist(user.id):
                flash("this request was previously approved")
            else:
                flash("this request was previously denied")
            return to("home")
    had_failed_notification = (
        request_row.email_status or ""
    ).strip() == audit_logic.EMAIL_STATUS_FAILED
    issue_key = ""
    if had_failed_notification:
        if request_type == "join-group":
            issue_key = f"join-group:{group.id}:{user.id}"
        else:
            issue_key = f"join-tech:DEV:{user.id}"

    pi = logic.pi_of_group(gid)
    if pi != g.user.id:
        abort(403, f"only the PI of {group.label} can approve or deny this request")

    approve = request.endpoint == "join-group-approve"
    form = schedule_logic.CsrfOnlyForm()

    if request.method == "POST":
        if not form.validate_on_submit():
            abort(400, "invalid form submission")

        if request_type == "join-group":
            logic.handle_join_request(approve, request_row)
        else:
            logic.handle_tech_join_request(approve, request_row)
        model.db.session.commit()
        action_label = "approve" if approve else "deny"
        action_prefix = "group.join"
        if request_type == "join-tech":
            action_prefix = "group.join.tech"
        audit_rbac_action(
            action=f"{action_prefix}.{action_label}",
            where=f"/join/{action_label}/{group.id}",
            how="email",
            what=f"group={group.id}, requester={user.id}",
        )

        if request_type == "join-group":
            if approve:
                flash(f"you have approved {user.id} to be a member of {group.label}")
            else:
                flash(f"you have denied {user.id} from becoming a member {group.label}")
            notification_logic.notify_user_of_join_request_outcome(
                approve, user, group.label
            )
        else:
            if approve:
                flash(f"you have approved {user.id} as a technologist")
            else:
                flash(f"you have denied technologist access for {user.id}")
            notification_logic.notify_user_of_tech_join_request_outcome(approve, user)
        if had_failed_notification:
            audit_logic.log_email_issue_resolution(
                issue_key=issue_key,
                actor=g.user.id if g.user is not None else "unknown",
                where=f"/join/{action_label}/{group.id}",
                how="join-request-review",
                details=f"group={group.id}, requester={user.id}, outcome={action_label}",
            )
        try:
            model.db.session.commit()
        except SQLAlchemyError:
            model.db.session.rollback()
            current_app.logger.exception(
                "Failed to commit email audit records for join request review"
            )
        return to("home")

    action = "approve" if approve else "deny"
    return {
        "form": form,
        "action": action,
        "user_id": user.id,
        "group_label": group.label,
        "action_url": my_url(),
        "cancel_url": url_for("home"),
        **breadcrumb("join request review"),
    }


def register_core_routes(
    app,
    *,
    active_user_required: Callable[[Callable[..., Any]], Callable[..., Any]],
    login_required: Callable[[Callable[..., Any]], Callable[..., Any]],
    render_to: Callable[[str], Callable[[Callable[..., Any]], Callable[..., Any]]],
    my_url_fn: Callable[[], str],
    to_fn: Callable[..., Any],
    breadcrumb_fn: Callable[..., BreadcrumbLinks],
    subpage_nav_fn: Callable[[str, List[Tuple[bool, str, str]]], SubpageLinks],
    audit_rbac_action_fn: Callable[..., None],
) -> None:
    global _my_url_fn, _to_fn, _breadcrumb_fn, _subpage_nav_fn, _audit_rbac_action_fn
    _my_url_fn = my_url_fn
    _to_fn = to_fn
    _breadcrumb_fn = breadcrumb_fn
    _subpage_nav_fn = subpage_nav_fn
    _audit_rbac_action_fn = audit_rbac_action_fn

    app.add_url_rule("/robots.txt", endpoint="robots", view_func=robots)
    app.add_url_rule(
        "/", endpoint="home", view_func=login_required(render_to("index")(home))
    )
    app.add_url_rule(
        "/mailing-lists",
        endpoint="mailing_lists",
        view_func=login_required(render_to("mailing-lists")(mailing_lists)),
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/join",
        endpoint="join_form",
        view_func=active_user_required(render_to("join")(join_form)),
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/join/tech",
        endpoint="join_form_tech",
        view_func=active_user_required(render_to("join_tech")(join_form_tech)),
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/join/approve/<token>",
        endpoint="join-group-approve",
        view_func=active_user_required(
            render_to("join_group_decision")(handle_join_group)
        ),
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/join/deny/<token>",
        endpoint="join-group-deny",
        view_func=active_user_required(
            render_to("join_group_decision")(handle_join_group)
        ),
        methods=["GET", "POST"],
    )
