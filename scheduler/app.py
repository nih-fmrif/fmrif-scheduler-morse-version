import os
import re
import secrets
from datetime import timedelta
from functools import wraps
from typing import Dict, List, Optional, Tuple, Union

import click
from flask import Blueprint, Flask, abort, current_app, g, redirect, request
from flask.helpers import flash, url_for
from flask.templating import render_template
from flask.wrappers import Response
from flask_session import Session
from itsdangerous.url_safe import URLSafeSerializer
from markupsafe import Markup, escape
from sqlalchemy.exc import SQLAlchemyError

from scheduler.auth.session import (
    authenticate_bearer_token,
    get_user_from_session,
    require_jwt,
)
from scheduler.auth.test_session_state import (
    get_auth_test_session_pi_groups,
    has_auth_test_session_pi_group,
)
from scheduler.auth.views import auth

from . import logic, message, model
from .config import app_config, normalize_app_env, settings
from .logging import configure_app_logging
from .routes.entity_routes import register_entity_routes
from .routes.rbac_routes import audit_rbac_action, register_rbac_blueprint


def css_token(value: str) -> str:
    token = re.sub(r"[^a-z0-9_-]+", "-", (value or "").strip().lower()).strip("-")
    return token or "none"


def current_csp_nonce() -> str:
    """Return request-scoped CSP nonce for templates, if available."""
    try:
        return getattr(g, "csp_nonce", "")
    except RuntimeError:
        return ""


core = Blueprint("", __name__)
_SHARED_SESSION_INTERFACE = None


def proxy_fix(app):
    counts = settings.get_proxy_count()
    if counts is not None:
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, **counts)


def create_app() -> Flask:
    """Build and configure a Flask application instance."""
    app = Flask(__name__)

    app_env = normalize_app_env(os.environ.get("APP_ENV", settings.app_env))

    # Load base settings first, then apply profile/runtime overrides.
    app.config.update(**app_config)
    app.config["APP_ENV"] = app_env
    app.config["DEBUG"] = settings.core.debug
    app.config["AUTH_TEST_ENABLED"] = settings.auth_test.enabled
    app.config["SESSION_COOKIE_SECURE"] = settings.session.cookie_secure
    app.config["TEMPLATES_AUTO_RELOAD"] = settings.core.debug

    if app_env == "development":
        os.environ.setdefault("FLASK_ENV", "development")
        os.environ.setdefault("FLASK_DEBUG", "1")
        os.environ.setdefault("FLASK_RUN_RELOAD", "1")
        app.config["DEBUG"] = True
        app.config["TEMPLATES_AUTO_RELOAD"] = True

    if not app.config.get("SESSION_COOKIE_PATH"):
        app.config["SESSION_COOKIE_PATH"] = app.config.get("APPLICATION_ROOT") or "/"

    app.config.update(
        SESSION_COOKIE_SECURE=settings.session.cookie_secure,
        SESSION_COOKIE_HTTPONLY=settings.session.cookie_httponly,
        SESSION_COOKIE_SAMESITE=settings.session.cookie_samesite,
        PERMANENT_SESSION_LIFETIME=timedelta(
            seconds=settings.session.permanent_lifetime
        ),
    )

    configure_app_logging(app)
    proxy_fix(app)

    model.db.init_app(app)
    app.config.setdefault("SESSION_SQLALCHEMY", model.db)
    global _SHARED_SESSION_INTERFACE
    if _SHARED_SESSION_INTERFACE is None:
        Session(app)
        _SHARED_SESSION_INTERFACE = app.session_interface
    else:
        app.session_interface = _SHARED_SESSION_INTERFACE
    message.mailer.init_app(app)
    signer = URLSafeSerializer(app.config["SECRET_KEY"], salt="nih-scheduler")
    app.config["URL_SIGNER"] = signer

    app.register_blueprint(auth, url_prefix="/auth")
    app.register_blueprint(core)

    register_rbac_blueprint(
        app,
        active_user_required=active_user_required,
        admin_only=admin_only,
        render_to=render_to,
        breadcrumb_fn=breadcrumb,
        subpage_nav_fn=subpage_nav,
    )

    register_entity_routes(
        app,
        active_user_required=active_user_required,
        login_required=login_required,
        render_to=render_to,
        my_url_fn=my_url,
        to_fn=to,
        breadcrumb_fn=breadcrumb,
        subpage_nav_fn=subpage_nav,
    )

    return app


## Authentication


@core.before_app_request
def setup_user():
    """Load user from session if available"""
    g.csp_nonce = secrets.token_urlsafe(16) if settings.security.enable_csp else ""

    # user already loaded
    if "user" in g:
        return

    # add a null user so we can exit early and ensure something is always set
    g.user = None

    # we don't need to bother to do anything special for static assets
    if request.endpoint == "static":
        return

    # Try bearer token first (stateless API calls)
    bearer_user = authenticate_bearer_token(request.headers.get("Authorization"))
    if bearer_user:
        g.user = bearer_user
        return

    # Try to get user from session
    g.user = get_user_from_session()


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
            M = model.Membership
            is_dev_pi = (
                M.query.filter(M.user == user_id)
                .filter(M.group == "DEV")
                .filter(M.pi)
                .filter(M.approved)
                .filter(M.user_active)
                .filter(M.group_active)
                .first()
                is not None
            )

    if is_admin or is_dev_pi:
        for device_id in device_id_set:
            device_permissions[device_id] = {"can_edit": True, "extra_privileges": []}
        return device_permissions

    editable_device_ids = set()
    if memberships:
        editable_device_ids = {
            device_id
            for (device_id,) in model.db.session.query(model.DeviceGroup.device)
            .filter(model.DeviceGroup.group.in_(memberships))
            .all()
            if device_id in device_id_set
        }

    user_devices = {
        row.device: row
        for row in model.UserDevice.query.filter_by(user=user_id)
        .filter(model.UserDevice.device.in_(device_id_set))
        .all()
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
        M = model.Membership
        q = M.query
        q = q.filter(M.user == user_id)
        q = q.filter(M.user_active)
        q = q.filter(M.approved)
        q = q.filter(M.pi)
        q = q.filter(M.group_active)
        value = q.first() is not None
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


@core.app_context_processor
def inject_template_context():
    """Provide shared template context values."""

    user = getattr(g, "user", None)
    menu_links: List[Tuple[str, str, str]] = []
    admin_menu_links: List[Tuple[str, str, str]] = []

    if user is not None:
        is_admin_user = _cached_is_admin() if user is g.user else logic.is_admin(user)
        menu_links.append(("email", url_for("mailing_lists"), "email"))
        if user.active:
            menu_links.insert(0, ("join form", url_for("join_form"), "join"))
            if _cached_show_tech_join_form(user):
                menu_links.append(
                    ("technologist join form", url_for("join_form_tech"), "tech")
                )
        if _rbac_user_can_access(user, is_admin=is_admin_user):
            admin_menu_links.append(("RBAC", url_for("rbac"), "lock"))
        if is_admin_user:
            admin_menu_links.append(("Admin Panel", url_for("app_issues"), "warning"))

    return {
        "logout_form": logic.CsrfOnlyForm(),
        "csp_nonce": getattr(g, "csp_nonce", ""),
        "user_menu_links": menu_links,
        "admin_menu_links": admin_menu_links,
    }


@core.after_app_request
def apply_security_headers(response: Response):
    """Apply baseline security headers without changing page behavior."""
    response.headers["X-Content-Type-Options"] = settings.security.content_type_options
    response.headers["X-Frame-Options"] = settings.security.frame_options
    response.headers["Referrer-Policy"] = settings.security.referrer_policy

    if settings.security.enable_csp:
        policy = settings.security.csp_policy
        nonce = getattr(g, "csp_nonce", "")
        if "{nonce}" in policy:
            policy = policy.replace("{nonce}", nonce)
        csp_header = (
            "Content-Security-Policy-Report-Only"
            if settings.security.csp_report_only
            else "Content-Security-Policy"
        )
        response.headers[csp_header] = policy
        if settings.security.csp_report_only:
            response.headers.pop("Content-Security-Policy", None)
        else:
            response.headers.pop("Content-Security-Policy-Report-Only", None)

    if settings.security.enable_hsts and request.is_secure:
        hsts_parts = [f"max-age={settings.security.hsts_max_age}"]
        if settings.security.hsts_include_subdomains:
            hsts_parts.append("includeSubDomains")
        if settings.security.hsts_preload:
            hsts_parts.append("preload")
        response.headers["Strict-Transport-Security"] = "; ".join(hsts_parts)

    return response


def login_required(f):
    return require_jwt(f)


@core.app_template_filter("css_token")
def _css_token_filter(value: str) -> str:
    return css_token(value)


# Keep nonce access import-mode agnostic: macros imported without context
# can still read the request-scoped CSP nonce through this helper.
@core.app_template_global("current_csp_nonce")
def _current_csp_nonce_global() -> str:
    return current_csp_nonce()


def active_user_required(f):
    @wraps(f)
    @require_jwt
    def protect(*args, **kwargs):
        if not g.user.active:
            abort(403, "Access denied: this page is limited to active users")
        return f(*args, **kwargs)

    return protect


def admin_only(f):
    @wraps(f)
    @require_jwt
    def protect(*args, **kwargs):
        if not (g.user is not None and _cached_is_admin()):
            abort(403, "Access denied: this page is admin only")
        return f(*args, **kwargs)

    return protect


## Error handlers


def render_error_page(
    code: int,
    title: str,
    detail: Optional[str] = None,
    show_login: bool = False,
) -> Tuple[str, int]:
    data = {
        "code": code,
        "title": title,
        "detail": detail,
        "assurance": "The application administrators have been notified.",
        "show_login": show_login,
        **breadcrumb(),
    }
    return render_template("error.html", **data), code


def wants_html_response() -> bool:
    accept = request.accept_mimetypes
    if not accept:
        return False
    return (
        accept.best_match(["text/html", "application/json"]) == "text/html"
        and accept["text/html"] > accept["application/json"]
    )


@core.app_errorhandler(401)
def unauthorized(e):
    # Redirect browser clients to login for unauthenticated requests
    if g.user is None and wants_html_response():
        return redirect(url_for("auth.login"))
    return render_error_page(
        401,
        "Authentication Required",
        "Your session may have expired. Please sign in and try again.",
        show_login=g.user is None,
    )


@core.app_errorhandler(403)
def access_denied(e):
    # Redirect to login page if user is not authenticated
    if g.user is None:
        return redirect(url_for("auth.login"))
    current_app.logger.warning(
        "Access denied for user=%s on path=%s (%s)",
        getattr(g.user, "id", "unknown"),
        request.path,
        e.description,
    )
    return render_error_page(
        403,
        "Access Denied",
        "You do not have permission to view this page.",
    )


@core.app_errorhandler(404)
def not_found(e):
    return render_error_page(
        404,
        "Page Not Found",
        "The page you requested could not be found.",
        show_login=g.user is None,
    )


## CLI commands


@core.cli.command("deactivate-user")
@click.argument("user")
def deactivate_user(user):
    """mark USER as no longer active"""
    u = logic.get_user(user)
    if u is None:
        click.echo(f"no such user {user}")
        return
    u.active = False
    model.db.session.add(u)
    model.db.session.commit()
    click.echo(f"{user} is now inactive")


@core.cli.command("activate-user")
@click.argument("user")
def activate_user(user):
    """mark USER as active"""
    u = logic.get_user(user)
    if u is None:
        click.echo(f"no such user {user}")
        return
    u.active = True
    model.db.session.add(u)
    model.db.session.commit()
    click.echo(f"{user} is now active")


@core.cli.command("add-admin")
@click.argument("user")
def add_admin(user):
    """add USER as an approved member of the admin group"""
    u = logic.get_user(user)
    if u is None:
        click.echo(f"no such user {user}")
        return
    if not u.active:
        click.echo("only active users may be added to admin group")
    if logic.is_admin(u):
        return  # nothing to do
    logic.add_admin(u)
    model.db.session.commit()
    click.echo(f"{user} is now an admin")


## Route helpers


def my_url() -> str:
    route = request.endpoint
    if not isinstance(route, str):
        abort(500)
    kwargs = request.view_args or {}
    return url_for(route, **kwargs)


# arguably a bad name but always used as return to(route)
# so it makes a lot of sense in context and is very concise
def to(page: str, **kwargs):
    return redirect(url_for(page, **kwargs))


# variant of to that goes to the current url
# useful in forms that can be filled out more than once
# redirecting to self prevents reloading the page from resubmitting the data
def to_form():
    return redirect(my_url())


Breadcrumb_links = Dict[str, List[Tuple[str, str]]]


def breadcrumb(*routes: Union[str, Tuple[str, str]]) -> Breadcrumb_links:
    trail: List[Tuple[str, str]] = [("home", url_for("home"))]
    if len(routes) > 0:
        routes, last = routes[:-1], routes[-1]
        for r in routes:
            assert not isinstance(r, str)
            trail.append(r)
        if isinstance(last, str):
            trail.append((last, my_url()))
        else:
            trail.append(last)
    return {"breadcrumb": trail}


def sr_only_tag(s: str) -> Markup:
    """Render compact nav labels with optional sr-only suffix safely.

    Expected pattern: ``visible [screen-reader text]``.
    Any user-provided content is HTML-escaped before optional sr-only wrapping.
    """
    text = str(s or "")
    start = text.find(" [")
    end = text.rfind("]")
    if start == -1 or end <= start + 2:
        return Markup(escape(text))

    visible = escape(text[:start])
    sr_text = escape(text[start + 2 : end])
    tail = escape(text[end + 1 :])
    return Markup(f"{visible}<sr-only> {sr_text}</sr-only>{tail}")


Subpage_links = Dict[str, Dict[str, Union[str, List[Tuple[str, str]]]]]


def subpage_nav(title: str, links: List[Tuple[bool, str, str]]) -> Subpage_links:
    shown = [(sr_only_tag(link), href) for (include, link, href) in links if include]
    if len(shown) <= 1:
        return {"subpage_nav": {}}
    return {
        "subpage_nav": {
            "title": sr_only_tag(title),
            "links": shown,
        },
    }


def render_to(template):
    """decorator that applies template to return of wrapped func"""

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            ctx = f(*args, **kwargs)
            if ctx is None:
                ctx = {}
            elif not isinstance(ctx, dict):
                return ctx
            # always inject user into context for login info component
            ctx["user"] = g.user
            return render_template(template + ".html", **ctx)

        return decorated_function

    return decorator


## Routes


@core.route("/robots.txt")
def robots():
    return Response("User-agent: *\nDisallow: /", mimetype="text/plain")


@core.route("/")
@login_required
@render_to("index")
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


@core.route("/mailing-lists", methods=["GET", "POST"])
@login_required
@render_to("mailing-lists")
def mailing_lists():
    form = logic.get_mailing_list_form(name=g.user.label, addr=g.user.addr)
    if form.validate_on_submit():
        logic.process_mailing_list_form_submissions(form)
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


def join_form_subnav(user: model.User) -> Subpage_links:
    return subpage_nav(
        "forms",
        [
            (True, "join form", url_for("join_form")),
            (
                _cached_show_tech_join_form(g.user),
                "technologist join form",
                url_for("join_form_tech"),
            ),
        ],
    )


def join_form_breadcrumb() -> Breadcrumb_links:
    return breadcrumb(("join form", url_for("join_form")))


@core.route("/join", methods=["GET", "POST"])
@active_user_required
@render_to("join")
def join_form():
    departments = logic.get_departments_for_join_form(g.user)
    form = logic.JoinForm(departments)
    no_departments = False
    if len(departments) == 0:
        no_departments = True
    if form.validate_on_submit():
        if logic.record_join_form(form, g.user, form.group.data):
            notify_state = logic.notify_group_pi_of_join_form(g.user, form.group.data)
            request_row = model.get(model.GroupMember, (form.group.data, g.user.id))
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


@core.route("/join/tech", methods=["GET", "POST"])
@active_user_required
@render_to("join_tech")
def join_form_tech():
    if not _cached_show_tech_join_form(g.user):
        abort(
            403,
            "Only DEV members who have not become technologists already may access this form",
        )
    form = logic.CsrfOnlyForm()
    # we only need to show the form on GET and there's nothing to validate on post:
    # if the browser allowed the form to be submitted, it's good
    if form.validate_on_submit():
        request_row = logic.record_tech_join_request(g.user)
        logic.handle_tech_join_request(True, request_row)
        request_row.email_status = logic.EMAIL_STATUS_NONE
        model.db.session.add(request_row)
        model.db.session.commit()
        audit_rbac_action(
            action="group.join.tech.autoapprove",
            where="/join/tech",
            how="form",
            what=f"user={g.user.id}, group=DEV, approved=true",
        )
        logic.notify_user_of_tech_join_request_outcome(True, g.user)
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


@core.route(
    "/join/approve/<token>", methods=["GET", "POST"], endpoint="join-group-approve"
)
@core.route("/join/deny/<token>", methods=["GET", "POST"], endpoint="join-group-deny")
@active_user_required
@render_to("join_group_decision")
def handle_join_group(token):
    signed = logic.read_signed_message(token)

    # make sure token is a real token
    if (
        signed is None
        or len(signed) != 3
        or signed[0] not in {"join-group", "join-tech"}
    ):
        abort(400)

    # get the user and group from the token data
    request_type, uid, gid = signed
    u = logic.get_user(uid)
    if u is None or not u.active:
        abort(400)
    grp = logic.get_group(gid)
    if grp is None or not grp.active:
        abort(400)

    if request_type == "join-group":
        request_row = logic.get_join_request(u, grp)
        if request_row is None:
            flash("this request was previously denied")
            return to("home")

        if request_row.approved is not None:
            flash("this request was previously approved")
            return to("home")
    else:
        request_row = logic.get_pending_tech_join_request(u)
        if request_row is None:
            if logic.is_technologist(u.id):
                flash("this request was previously approved")
            else:
                flash("this request was previously denied")
            return to("home")
    had_failed_notification = (
        request_row.email_status or ""
    ).strip() == logic.EMAIL_STATUS_FAILED
    issue_key = ""
    if had_failed_notification:
        if request_type == "join-group":
            issue_key = f"join-group:{grp.id}:{u.id}"
        else:
            issue_key = f"join-tech:DEV:{u.id}"

    # make sure current user is PI of g
    pi = logic.pi_of_group(gid)
    if pi != g.user.id:
        abort(403, f"only the PI of {grp.label} can approve or deny this request")

    approve = request.endpoint == "join-group-approve"
    form = logic.CsrfOnlyForm()

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
            where=f"/join/{action_label}/{grp.id}",
            how="email",
            what=f"group={grp.id}, requester={u.id}",
        )

        if request_type == "join-group":
            if approve:
                flash(f"you have approved {u.id} to be a member of {grp.label}")
            else:
                flash(f"you have denied {u.id} from becoming a member {grp.label}")
            logic.notify_user_of_join_request_outcome(approve, u, grp.label)
        else:
            if approve:
                flash(f"you have approved {u.id} as a technologist")
            else:
                flash(f"you have denied technologist access for {u.id}")
            logic.notify_user_of_tech_join_request_outcome(approve, u)
        if had_failed_notification:
            logic.log_email_issue_resolution(
                issue_key=issue_key,
                actor=g.user.id if g.user is not None else "unknown",
                where=f"/join/{action_label}/{grp.id}",
                how="join-request-review",
                details=f"group={grp.id}, requester={u.id}, outcome={action_label}",
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
        "user_id": u.id,
        "group_label": grp.label,
        "action_url": my_url(),
        "cancel_url": url_for("home"),
        **breadcrumb("join request review"),
    }
