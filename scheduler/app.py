import json
import re
import secrets
from datetime import timedelta
from functools import wraps
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from urllib.parse import parse_qs, urlparse

import click
from flask import Flask, abort, g, jsonify, redirect, request
from flask.helpers import flash, url_for
from flask.templating import render_template
from flask.wrappers import Response
from flask_session import Session
from itsdangerous.url_safe import URLSafeSerializer
from sqlalchemy import text as sql_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import func

from scheduler.auth.session import (
    authenticate_bearer_token,
    get_user_from_session,
    require_jwt,
)
from scheduler.auth.views import auth

from . import logic, message, model
from .config import app_config, settings
from .logging import configure_app_logging


def css_token(value: str) -> str:
    token = re.sub(r"[^a-z0-9_-]+", "-", (value or "").strip().lower()).strip("-")
    return token or "none"


def current_csp_nonce() -> str:
    """Return request-scoped CSP nonce for templates, if available."""
    try:
        return getattr(g, "csp_nonce", "")
    except RuntimeError:
        return ""


## Configuration
app = Flask(__name__)

# Load configuration from settings
app.config.update(**app_config)
configure_app_logging(app)

# Ensure cookie path is always valid, even when APPLICATION_ROOT is empty
if not app.config.get("SESSION_COOKIE_PATH"):
    app.config["SESSION_COOKIE_PATH"] = app.config.get("APPLICATION_ROOT") or "/"

# Add session security settings
app.config.update(
    SESSION_COOKIE_SECURE=settings.session.cookie_secure,
    SESSION_COOKIE_HTTPONLY=settings.session.cookie_httponly,
    SESSION_COOKIE_SAMESITE=settings.session.cookie_samesite,
    PERMANENT_SESSION_LIFETIME=timedelta(seconds=settings.session.permanent_lifetime),
)


def proxy_fix(app):
    counts = settings.get_proxy_count()
    if counts is not None:
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, **counts)


proxy_fix(app)

# Initialize extensions
model.db.init_app(app)
# Ensure Flask-Session uses the same SQLAlchemy instance as the app models
app.config.setdefault("SESSION_SQLALCHEMY", model.db)
Session(app)
message.mailer.init_app(app)
signer = URLSafeSerializer(app.config["SECRET_KEY"], salt="nih-scheduler")
app.config["URL_SIGNER"] = signer

# Register blueprints
app.register_blueprint(auth, url_prefix="/auth")

## Authentication


@app.before_request
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


def _rbac_user_is_group_pi(user: model.User) -> bool:
    if not user.active:
        return False

    M = model.Membership
    q = M.query
    q = q.filter(M.user == user.id)
    q = q.filter(M.user_active)
    q = q.filter(M.approved)
    q = q.filter(M.pi)
    q = q.filter(M.group_active)
    return q.first() is not None


def _rbac_user_can_access(user: Optional[model.User]) -> bool:
    if user is None or not user.active:
        return False
    if logic.is_admin(user):
        return True
    return _rbac_user_is_group_pi(user)


@app.context_processor
def inject_template_context():
    """Provide shared template context values."""

    user = getattr(g, "user", None)
    menu_links: List[Tuple[str, str, str]] = []

    if user is not None:
        menu_links.append(("email", url_for("mailing_lists"), "email"))
        if user.active:
            menu_links.insert(0, ("join form", url_for("join_form"), "join"))
            if logic.show_tech_join_form(user):
                menu_links.append(
                    ("technologist join form", url_for("join_form_tech"), "tech")
                )
        if _rbac_user_can_access(user):
            menu_links.append(("RBAC", url_for("rbac"), "lock"))
        if logic.is_admin(g.user):
            menu_links.append(("Potential issues", url_for("app_issues"), "warning"))

    return {
        "logout_form": logic.CsrfOnlyForm(),
        "csp_nonce": getattr(g, "csp_nonce", ""),
        "user_menu_links": menu_links,
    }


@app.after_request
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


app.jinja_env.filters["css_token"] = css_token
# Keep nonce access import-mode agnostic: macros imported without context
# can still read the request-scoped CSP nonce through this helper.
app.jinja_env.globals["current_csp_nonce"] = current_csp_nonce


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
        if not (g.user is not None and g.user.active and logic.is_admin(g.user)):
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


@app.errorhandler(401)
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


@app.errorhandler(403)
def access_denied(e):
    # Redirect to login page if user is not authenticated
    if g.user is None:
        return redirect(url_for("auth.login"))
    app.logger.warning(
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


@app.errorhandler(404)
def not_found(e):
    return render_error_page(
        404,
        "Page Not Found",
        "The page you requested could not be found.",
        show_login=g.user is None,
    )


## CLI commands


@app.cli.command("deactivate-user")
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


@app.cli.command("activate-user")
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


@app.cli.command("add-admin")
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


def sr_only_tag(s: str) -> str:
    """replace " [" with "<sr-only>" and "]" with "</sr-only>",
    allowing more compact representation of common pattern."""
    return s.replace(" [", "<sr-only> ").replace("]", "</sr-only>")


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


@app.route("/robots.txt")
def robots():
    return Response("User-agent: *\nDisallow: /", mimetype="text/plain")


@app.route("/")
@login_required
@render_to("index")
def home():
    devices = logic.get_devices(active=True)
    groups: List[model.Group] = []
    show_groups = g.user.active

    if show_groups:
        memberships = logic.get_memberships(g.user)
        is_admin = "admin" in memberships
        if is_admin:
            groups = logic.get_all_groups_with_members(active=True)
        else:
            groups = logic.get_groups(memberships)

    return {
        "devices": devices,
        "groups": groups,
        "show_groups": show_groups,
        **breadcrumb(),
    }


@app.route("/mailing-lists", methods=["GET", "POST"])
@login_required
@render_to("mailing-lists")
def mailing_lists():
    form = logic.get_mailing_list_form(name=g.user.label, addr=g.user.addr)
    if form.validate_on_submit():
        logic.process_mailing_list_form_submissions(form)
        flash("your mailing list subscription status has been updated")
        return to("home")
    return {
        "form": form,
        "action": my_url(),
        **breadcrumb("email"),
    }


def join_form_subnav(user: model.User) -> Subpage_links:
    return subpage_nav(
        "show [which form]",
        [
            (True, "join form", url_for("join_form")),
            (
                logic.show_tech_join_form(g.user),
                "technologist join form",
                url_for("join_form_tech"),
            ),
        ],
    )


def join_form_breadcrumb() -> Breadcrumb_links:
    return breadcrumb(("join form", url_for("join_form")))


@app.route("/join", methods=["GET", "POST"])
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
            _audit_rbac_action(
                action="group.join.request",
                where=f"/join/{form.group.data}",
                how="email",
                what=f"group={form.group.data}",
            )
            logic.notify_group_pi_of_join_form(g.user, form.group.data)
            flash("your membership request is being processed")
            return to("home")
    return {
        "form": form,
        "action": my_url(),
        "no_departments": no_departments,
        **join_form_subnav(g.user),
        **join_form_breadcrumb(),
    }


@app.route("/join/tech", methods=["GET", "POST"])
@active_user_required
@render_to("join_tech")
def join_form_tech():
    if not logic.show_tech_join_form(g.user):
        abort(
            403,
            "Only DEV members who have not become technologists already may access this form",
        )
    form = logic.CsrfOnlyForm()
    # we only need to show the form on GET and there's nothing to validate on post:
    # if the browser allowed the form to be submitted, it's good
    if form.validate_on_submit():
        logic.record_tech_join(g.user)
        model.db.session.commit()
        logic.notify_dev_pi_of_tech_join_form(g.user)
        _audit_rbac_action(
            action="group.join.tech",
            where="/join/tech",
            how="email",
            what=f"user={g.user.id}, group=DEV",
        )
        flash("your technologist application has been submitted for review")
        return to("home")
    return {
        "form": form,
        **join_form_subnav(g.user),
        **join_form_breadcrumb(),
    }


@app.route(
    "/join/approve/<token>", methods=["GET", "POST"], endpoint="join-group-approve"
)
@app.route("/join/deny/<token>", methods=["GET", "POST"], endpoint="join-group-deny")
@active_user_required
@render_to("join_group_decision")
def handle_join_group(token):
    req = logic.read_signed_message(token)

    # make sure token is a real token
    if req is None or len(req) != 3 or req[0] != "join-group":
        abort(400)

    # get the user and group from the token data
    _, uid, gid = req
    u = logic.get_user(uid)
    if u is None or not u.active:
        abort(400)
    grp = logic.get_group(gid)
    if grp is None or not grp.active:
        abort(400)

    # make sure the request is unprocessed
    req = logic.get_join_request(u, grp)
    if req is None:
        flash("this request was previously denied")
        return to("home")

    if req.approved is not None:
        flash("this request was previously approved")
        return to("home")

    # make sure current user is PI of g
    pi = logic.pi_of_group(gid)
    if pi != g.user.id:
        abort(403, f"only the PI of {grp.label} can approve or deny this request")

    approve = request.endpoint == "join-group-approve"
    form = logic.CsrfOnlyForm()

    if request.method == "POST":
        if not form.validate_on_submit():
            abort(400, "invalid form submission")

        logic.handle_join_request(approve, req)
        model.db.session.commit()
        action_label = "approve" if approve else "deny"
        _audit_rbac_action(
            action=f"group.join.{action_label}",
            where=f"/join/{action_label}/{grp.id}",
            how="email",
            what=f"group={grp.id}, requester={u.id}",
        )

        if approve:
            flash(f"you have approved {u.id} to be a member of {grp.label}")
        else:
            flash(f"you have denied {u.id} from becoming a member {grp.label}")
        logic.notify_user_of_join_request_outcome(approve, u, grp.label)
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


def groups_subpage_nav(_is_admin: bool) -> Subpage_links:
    return subpage_nav(
        "show [which groups]",
        [
            (True, "active [groups]", url_for("groups")),
        ],
    )


def groups_breadcrumb() -> Breadcrumb_links:
    return breadcrumb(("groups", url_for("groups")))


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


def _audit_rbac_action(
    action: str,
    where: str,
    how: str,
    what: str,
) -> None:
    _record_rbac_action(action=action, where=where, how=how, what=what)
    try:
        model.db.session.commit()
    except Exception:
        model.db.session.rollback()
        app.logger.exception("Failed to commit RBAC audit record")


_RBAC_SCOPE_LABELS: Dict[str, str] = {
    "group": "groups",
    "device": "devices",
    "user": "users",
}
_RBAC_AUDIT_SCOPE_LABELS: Dict[str, str] = {
    "all": "all",
    **_RBAC_SCOPE_LABELS,
}
_RBAC_GRAPH_NODE_LIMIT = 12
_RBAC_TABLE_ROW_LIMIT = 250
_RBAC_MATRIX_ROW_LIMIT = 500


def _rbac_actor(user: Optional[model.User]) -> Dict[str, Any]:
    actor: Dict[str, Any] = {
        "id": user.id if user is not None else "",
        "is_admin": False,
        "is_dev_pi": False,
        "managed_groups": set(),
        "allowed_scopes": [],
        "can_access": False,
    }
    if user is None or not user.active:
        return actor

    is_admin = logic.is_admin(user)
    managed_groups: Set[str] = set()
    if not is_admin:
        M = model.Membership
        q = M.query
        q = q.filter(M.user == user.id)
        q = q.filter(M.user_active)
        q = q.filter(M.approved)
        q = q.filter(M.pi)
        q = q.filter(M.group_active)
        managed_groups = {row.group for row in q.all()}
    else:
        managed_groups = {
            row.group
            for row in model.Membership.query.filter(model.Membership.user == user.id)
            .filter(model.Membership.pi)
            .all()
        }

    is_dev_pi = "DEV" in managed_groups

    allowed_scopes: List[str] = []
    if is_admin:
        allowed_scopes = [scope for scope in _RBAC_SCOPE_LABELS.keys()]
    else:
        if len(managed_groups) > 0:
            allowed_scopes.append("group")
        if is_dev_pi:
            allowed_scopes.append("device")

    actor.update(
        {
            "is_admin": is_admin,
            "is_dev_pi": is_dev_pi,
            "managed_groups": managed_groups,
            "allowed_scopes": allowed_scopes,
            "can_access": bool(is_admin or len(managed_groups) > 0),
        }
    )
    return actor


def _rbac_actor_scope_labels(actor: Dict[str, Any]) -> Dict[str, str]:
    allowed = actor.get("allowed_scopes", [])
    if not isinstance(allowed, list) or len(allowed) == 0:
        return {}
    return {
        scope: _RBAC_SCOPE_LABELS[scope]
        for scope in allowed
        if scope in _RBAC_SCOPE_LABELS
    }


def _rbac_actor_allows_scope(actor: Dict[str, Any], scope: str) -> bool:
    allowed = actor.get("allowed_scopes", [])
    if not isinstance(allowed, list):
        return False
    return scope in allowed


def _rbac_actor_managed_groups(actor: Dict[str, Any]) -> Set[str]:
    groups = actor.get("managed_groups", set())
    if isinstance(groups, set):
        return groups
    return set()


def _rbac_href_allowed_for_actor(href: str, actor: Dict[str, Any]) -> bool:
    target = (href or "").strip()
    if target == "":
        return True
    parsed = urlparse(target)
    if parsed.path.rstrip("/") != "/rbac":
        return True
    scope = parse_qs(parsed.query).get("scope", ["group"])[0].strip().lower()
    if scope not in _RBAC_SCOPE_LABELS:
        return False
    return _rbac_actor_allows_scope(actor, scope)


def _rbac_badge(value: bool) -> str:
    return "yes" if value else "no"


def _rbac_state(value: bool) -> str:
    return "active" if value else "inactive"


def _rbac_device_label(device: model.Device) -> str:
    if device.label and device.label != device.id:
        return f"{device.label} ({device.id})"
    return device.id


def _rbac_group_label(group: model.Group) -> str:
    if group.label and group.label != group.id:
        return f"{group.label} ({group.id})"
    return group.id


def _rbac_user_label(user: model.User) -> str:
    if user.label and user.label != user.id:
        return f"{user.label} ({user.id})"
    return user.id


def _rbac_slice_graph_nodes(
    entries: List[Dict[str, str]],
    *,
    limit: int = _RBAC_GRAPH_NODE_LIMIT,
) -> Tuple[List[Dict[str, str]], int]:
    if len(entries) <= limit:
        return entries, 0
    return entries[:limit], len(entries) - limit


def _rbac_limit_rows(
    rows: List[Dict[str, Any]],
    *,
    limit: int = _RBAC_TABLE_ROW_LIMIT,
) -> Tuple[List[Dict[str, Any]], int]:
    if len(rows) <= limit:
        return rows, 0
    return rows[:limit], len(rows) - limit


def _rbac_scopes(*, allowed_scopes: Optional[List[str]] = None) -> List[Dict[str, str]]:
    if allowed_scopes is None:
        allowed_scopes = [scope for scope in _RBAC_SCOPE_LABELS.keys()]
    return [
        {"id": scope_id, "label": label}
        for scope_id, label in _RBAC_SCOPE_LABELS.items()
        if scope_id in allowed_scopes
    ]


def _rbac_entities(
    scope: str,
    *,
    include_inactive: bool = False,
) -> List[Dict[str, Any]]:
    if scope == "group":
        query = model.Group.query.order_by(model.Group.label, model.Group.id)
        if not include_inactive:
            query = query.filter(model.Group.active)
        groups = query.all()
        return [
            {
                "id": group.id,
                "label": _rbac_group_label(group),
                "active": bool(group.active),
            }
            for group in groups
        ]

    if scope == "device":
        query = model.Device.query.order_by(model.Device.label, model.Device.id)
        if not include_inactive:
            query = query.filter(model.Device.active)
        devices = query.all()
        return [
            {
                "id": device.id,
                "label": _rbac_device_label(device),
                "active": bool(device.active),
            }
            for device in devices
        ]

    if scope == "user":
        query = model.User.query.order_by(model.User.active.desc(), model.User.id)
        if not include_inactive:
            query = query.filter(model.User.active)
        users = query.all()
        return [
            {
                "id": user.id,
                "label": _rbac_user_label(user),
                "active": bool(user.active),
            }
            for user in users
        ]

    return []


def _rbac_entities_for_actor(
    scope: str,
    actor: Dict[str, Any],
    *,
    include_inactive: bool = False,
) -> List[Dict[str, Any]]:
    if not _rbac_actor_allows_scope(actor, scope):
        return []

    if bool(actor.get("is_admin")):
        return _rbac_entities(scope, include_inactive=include_inactive)

    if scope == "group":
        managed_groups = sorted(_rbac_actor_managed_groups(actor))
        if len(managed_groups) == 0:
            return []
        q = model.Group.query.filter(model.Group.id.in_(managed_groups)).order_by(
            model.Group.label, model.Group.id
        )
        if not include_inactive:
            q = q.filter(model.Group.active)
        groups = q.all()
        return [
            {
                "id": group.id,
                "label": _rbac_group_label(group),
                "active": bool(group.active),
            }
            for group in groups
        ]

    if scope == "device":
        if not bool(actor.get("is_dev_pi")):
            return []
        q = model.Device.query.order_by(model.Device.label, model.Device.id)
        if not include_inactive:
            q = q.filter(model.Device.active)
        devices = q.all()
        return [
            {
                "id": device.id,
                "label": _rbac_device_label(device),
                "active": bool(device.active),
            }
            for device in devices
        ]

    return []


def _rbac_entity_visible(scope: str, entity: str, *, include_inactive: bool) -> bool:
    if entity == "":
        return False
    if scope == "group":
        group = logic.get_group(entity)
        if group is None:
            return False
        return include_inactive or bool(group.active)
    if scope == "device":
        device = logic.get_device(entity)
        if device is None:
            return False
        return include_inactive or bool(device.active)
    if scope == "user":
        user = logic.get_user(entity)
        if user is None:
            return False
        return include_inactive or bool(user.active)
    return False


def _rbac_entity_visible_for_actor(
    scope: str,
    entity: str,
    actor: Dict[str, Any],
    *,
    include_inactive: bool,
) -> bool:
    if not _rbac_actor_allows_scope(actor, scope):
        return False
    if bool(actor.get("is_admin")):
        return _rbac_entity_visible(scope, entity, include_inactive=include_inactive)

    if scope == "group":
        if entity not in _rbac_actor_managed_groups(actor):
            return False
        group = logic.get_group(entity)
        if group is None:
            return False
        return include_inactive or bool(group.active)

    if scope == "device":
        if not bool(actor.get("is_dev_pi")):
            return False
        device = logic.get_device(entity)
        if device is None:
            return False
        return include_inactive or bool(device.active)

    return False


def _rbac_permission_flags(ud: model.UserDevice) -> str:
    flags = []
    if ud.templates:
        flags.append("templates")
    if ud.slot:
        flags.append("slot")
    if ud.tech:
        flags.append("tech")
    if ud.medical:
        flags.append("medical")
    if ud.training:
        flags.append("training")
    return ", ".join(flags) if flags else "none"


def _rbac_select_option(
    value: str,
    label: str,
    *,
    meta: str = "",
) -> Dict[str, str]:
    return {"value": value, "label": label, "meta": meta}


def _rbac_group_detail(
    group: model.Group,
    *,
    include_inactive: bool = False,
) -> Dict[str, Any]:
    memberships_query = model.Membership.query.filter(
        model.Membership.group == group.id
    ).order_by(model.Membership.user)
    if not include_inactive:
        memberships_query = memberships_query.filter(model.Membership.user_active)
    memberships = memberships_query.all()
    devices_query = (
        model.Device.query.join(
            model.DeviceGroup, model.DeviceGroup.device == model.Device.id
        )
        .filter(model.DeviceGroup.group == group.id)
        .order_by(model.Device.label, model.Device.id)
    )
    if not include_inactive:
        devices_query = devices_query.filter(model.Device.active)
    devices = devices_query.all()
    membership_by_user = {row.user: row for row in memberships}
    linked_device_ids = {device.id for device in devices}

    member_nodes: List[Dict[str, str]] = []
    member_rows: List[Dict[str, Any]] = []
    for row in memberships:
        status = "approved" if row.approved else "pending"
        tags = [status]
        if row.pi:
            tags.append("PI")
        if not row.user_active:
            tags.append("inactive user")
        if not row.group_active:
            tags.append("inactive group")
        meta = ", ".join(tags)
        member_nodes.append(
            {
                "label": row.user,
                "meta": meta,
                "href": url_for("rbac", scope="user", entity=row.user),
            }
        )
        member_rows.append(
            {
                "cells": {
                    "user": row.user,
                    "status": status,
                    "pi": _rbac_badge(bool(row.pi)),
                    "user_state": _rbac_state(bool(row.user_active)),
                },
                "actions": [
                    {
                        "label": "inspect user",
                        "href": url_for("rbac", scope="user", entity=row.user),
                    }
                ],
            }
        )

    device_nodes: List[Dict[str, str]] = []
    device_rows: List[Dict[str, Any]] = []
    for device in devices:
        device_nodes.append(
            {
                "label": _rbac_device_label(device),
                "meta": _rbac_state(bool(device.active)),
                "href": url_for("rbac", scope="device", entity=device.id),
            }
        )
        device_rows.append(
            {
                "cells": {
                    "device": _rbac_device_label(device),
                    "status": _rbac_state(bool(device.active)),
                },
                "actions": [
                    {
                        "label": "inspect device",
                        "href": url_for("rbac", scope="device", entity=device.id),
                    },
                ],
            }
        )

    all_devices_query = model.Device.query.order_by(model.Device.label, model.Device.id)
    if not include_inactive:
        all_devices_query = all_devices_query.filter(model.Device.active)
    all_devices = all_devices_query.all()
    device_matrix_rows_ranked: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    for device in all_devices:
        linked = device.id in linked_device_ids
        can_link = bool(group.active) and (linked or bool(group.department))
        row = {
            "id": device.id,
            "search": (
                f"{device.id} {_rbac_device_label(device)} "
                f"{_rbac_state(bool(device.active))}"
            ),
            "cells": {
                "device": _rbac_device_label(device),
                "device_state": _rbac_state(bool(device.active)),
            },
            "values": {"linked": linked},
            "editable": {"linked": can_link},
            "operation": {
                "kind": "device.group.set",
                "group": group.id,
                "device": device.id,
            },
        }
        rank = (
            0 if linked else 1,
            0 if device.active else 1,
            (device.label or "").lower(),
            device.id.lower(),
        )
        device_matrix_rows_ranked.append((rank, row))
    device_matrix_rows_ranked.sort(key=lambda entry: entry[0])
    device_matrix_rows = [row for _, row in device_matrix_rows_ranked]
    device_matrix_rows, device_matrix_more = _rbac_limit_rows(
        device_matrix_rows, limit=_RBAC_MATRIX_ROW_LIMIT
    )

    all_users_query = model.User.query.order_by(model.User.label, model.User.id)
    if not include_inactive:
        all_users_query = all_users_query.filter(model.User.active)
    all_users = all_users_query.all()
    current_pi_user = next((row.user for row in memberships if row.pi), "")
    eligible_pi_user_ids = sorted(
        {row.user for row in memberships if row.approved and row.user_active}
    )
    pi_option_ids = list(eligible_pi_user_ids)
    if current_pi_user != "" and current_pi_user not in pi_option_ids:
        pi_option_ids.append(current_pi_user)
    pi_options = []
    for user_id in pi_option_ids:
        label = user_id
        if user_id == current_pi_user and user_id not in eligible_pi_user_ids:
            label = f"{user_id} [current, not eligible]"
        pi_options.append({"value": user_id, "label": label})

    membership_matrix_rows_ranked: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    for user in all_users:
        membership = membership_by_user.get(user.id)
        if membership is None and not user.active:
            continue
        is_member = membership is not None
        approved = bool(membership.approved) if membership is not None else False
        pi = bool(membership.pi) if membership is not None else False
        status = "not member"
        if is_member:
            status = "approved" if approved else "pending"
        row = {
            "id": user.id,
            "search": (
                f"{user.id} {_rbac_user_label(user)} {status} "
                f"{_rbac_state(bool(user.active))}"
            ),
            "cells": {
                "user": _rbac_user_label(user),
                "user_state": _rbac_state(bool(user.active)),
                "pi": _rbac_badge(pi),
            },
            "values": {
                "member": is_member,
                "approved": approved,
            },
            "editable": {
                "member": bool(group.active and (user.active or is_member)),
                "approved": bool(group.active and user.active and is_member),
            },
            "operation": {
                "kind": "group.membership.set",
                "group": group.id,
                "user": user.id,
            },
        }
        rank = (
            0 if is_member else 1,
            0 if approved else 1,
            0 if user.active else 1,
            (user.label or "").lower(),
            user.id.lower(),
        )
        membership_matrix_rows_ranked.append((rank, row))
    membership_matrix_rows_ranked.sort(key=lambda entry: entry[0])
    membership_matrix_rows = [row for _, row in membership_matrix_rows_ranked]
    membership_matrix_rows, membership_matrix_more = _rbac_limit_rows(
        membership_matrix_rows, limit=_RBAC_MATRIX_ROW_LIMIT
    )

    left_nodes, left_more = _rbac_slice_graph_nodes(member_nodes)
    right_nodes, right_more = _rbac_slice_graph_nodes(device_nodes)
    member_rows, member_more = _rbac_limit_rows(member_rows)
    device_rows, device_more = _rbac_limit_rows(device_rows)

    special_group = group.id in {"admin", "DEV"}
    can_toggle_active = not special_group
    status_note = "Edit group metadata, PI assignment, and active state in one row."
    if not can_toggle_active:
        status_note = "Special groups are always active and cannot be deactivated."
    institutes = model.Inst.query.order_by(model.Inst.label, model.Inst.id).all()
    inst_options = [{"value": "", "label": "none"}]
    for inst in institutes:
        label = inst.label
        if label != inst.id:
            label = f"{inst.label} ({inst.id})"
        if not inst.active:
            label = f"{label} [inactive]"
        inst_options.append({"value": inst.id, "label": label})

    return {
        "summary": {
            "title": _rbac_group_label(group),
            "subtitle": "group",
            "badges": [
                _rbac_state(bool(group.active)),
                "membership-enabled" if group.has_membership else "membership-disabled",
                "joinable" if group.is_joinable else "not-joinable",
            ],
        },
        "links": [],
        "graph": {
            "source_title": "members",
            "target_title": "linked devices",
            "focus": {
                "label": _rbac_group_label(group),
                "href": "",
            },
            "sources": left_nodes,
            "targets": right_nodes,
            "source_more": left_more,
            "target_more": right_more,
        },
        "tables": [
            {
                "title": "members",
                "empty": "No members found for this group.",
                "more": member_more,
                "columns": [
                    {"key": "user", "label": "user"},
                    {"key": "status", "label": "status"},
                    {"key": "pi", "label": "pi"},
                    {"key": "user_state", "label": "user state"},
                ],
                "rows": member_rows,
            },
            {
                "title": "device links",
                "empty": "No devices linked to this group.",
                "more": device_more,
                "columns": [
                    {"key": "device", "label": "device"},
                    {"key": "status", "label": "device status"},
                ],
                "rows": device_rows,
            },
        ],
        "matrices": [
            {
                "id": "group-metadata-matrix",
                "title": "group settings",
                "description": status_note,
                "empty": "Group metadata unavailable.",
                "apply_label": "apply group settings",
                "confirm": f"Apply metadata updates for {group.id}?",
                "more": 0,
                "filter": False,
                "layout": "keyvalue",
                "rows": [
                    {
                        "id": f"{group.id}-label",
                        "search": f"{group.id} label {_rbac_group_label(group)}",
                        "label": "short label",
                        "kind": "input",
                        "input_type": "text",
                        "max_length": 20,
                        "field": "label",
                        "value": group.label or "",
                        "editable": True,
                        "operation": {"kind": "group.meta.set", "group": group.id},
                    },
                    {
                        "id": f"{group.id}-description",
                        "search": f"{group.id} description {_rbac_group_label(group)}",
                        "label": "long label",
                        "kind": "input",
                        "input_type": "text",
                        "max_length": 75,
                        "field": "description",
                        "value": group.description or "",
                        "editable": True,
                        "operation": {"kind": "group.meta.set", "group": group.id},
                    },
                    {
                        "id": f"{group.id}-addr",
                        "search": f"{group.id} email {_rbac_group_label(group)}",
                        "label": "email",
                        "kind": "input",
                        "input_type": "text",
                        "field": "addr",
                        "value": group.addr or "",
                        "editable": True,
                        "operation": {"kind": "group.meta.set", "group": group.id},
                    },
                    {
                        "id": f"{group.id}-link",
                        "search": f"{group.id} link {_rbac_group_label(group)}",
                        "label": "link",
                        "kind": "input",
                        "input_type": "url",
                        "field": "link",
                        "value": group.link or "",
                        "editable": True,
                        "operation": {"kind": "group.meta.set", "group": group.id},
                    },
                    {
                        "id": f"{group.id}-color",
                        "search": f"{group.id} color {_rbac_group_label(group)}",
                        "label": "legend color",
                        "kind": "input",
                        "input_type": "color",
                        "field": "color",
                        "value": group.color or "#000000",
                        "editable": not special_group,
                        "operation": {"kind": "group.meta.set", "group": group.id},
                    },
                    {
                        "id": f"{group.id}-inst",
                        "search": f"{group.id} institute {_rbac_group_label(group)}",
                        "label": "institute",
                        "kind": "select",
                        "field": "inst",
                        "value": group.inst or "",
                        "options": inst_options,
                        "editable": not special_group,
                        "operation": {"kind": "group.meta.set", "group": group.id},
                    },
                    {
                        "id": f"{group.id}-pi",
                        "search": f"{group.id} pi {_rbac_group_label(group)}",
                        "label": "PI user",
                        "kind": "select",
                        "field": "user",
                        "value": current_pi_user,
                        "options": pi_options,
                        "editable": bool(
                            group.active and len(eligible_pi_user_ids) > 0
                        ),
                        "operation": {
                            "kind": "group.pi.set",
                            "group": group.id,
                            "expected_current_pi": current_pi_user,
                        },
                    },
                    {
                        "id": f"{group.id}-active",
                        "search": f"{group.id} active {_rbac_group_label(group)}",
                        "label": "active",
                        "kind": "checkbox",
                        "field": "active",
                        "value": bool(group.active),
                        "editable": can_toggle_active,
                        "operation": {"kind": "group.meta.set", "group": group.id},
                    },
                    {
                        "id": f"{group.id}-membership-enabled",
                        "search": f"{group.id} membership-enabled {_rbac_group_label(group)}",
                        "label": "membership-enabled",
                        "kind": "checkbox",
                        "value": bool(group.has_membership),
                        "editable": False,
                    },
                    {
                        "id": f"{group.id}-joinable",
                        "search": f"{group.id} joinable {_rbac_group_label(group)}",
                        "label": "joinable",
                        "kind": "checkbox",
                        "value": bool(group.is_joinable),
                        "editable": False,
                    },
                ],
            },
            {
                "id": "group-membership-matrix",
                "title": "membership state",
                "description": (
                    "Edit member and approval state. "
                    "PI assignment is managed in group settings."
                ),
                "empty": "No users found for this group.",
                "apply_label": "apply membership updates",
                "confirm": f"Apply membership updates for {group.id}?",
                "more": membership_matrix_more,
                "columns": [
                    {"key": "user", "label": "user", "kind": "text"},
                    {"key": "user_state", "label": "user state", "kind": "text"},
                    {"key": "member", "label": "member", "kind": "checkbox"},
                    {"key": "approved", "label": "approved", "kind": "checkbox"},
                    {"key": "pi", "label": "PI", "kind": "text"},
                ],
                "rows": membership_matrix_rows,
                "behavior": "group-membership",
            },
            {
                "id": "group-device-links-matrix",
                "title": "linked devices",
                "description": (
                    "Tick devices that should remain linked to this group."
                ),
                "empty": "No devices found.",
                "apply_label": "apply device links",
                "confirm": f"Apply device link updates for {group.id}?",
                "more": device_matrix_more,
                "columns": [
                    {"key": "device", "label": "device", "kind": "text"},
                    {
                        "key": "device_state",
                        "label": "device state",
                        "kind": "text",
                    },
                    {"key": "linked", "label": "linked", "kind": "checkbox"},
                ],
                "rows": device_matrix_rows,
            },
        ],
        "mutations": [],
    }


def _rbac_device_detail(
    device: model.Device,
    *,
    include_inactive: bool = False,
) -> Dict[str, Any]:
    groups_query = (
        model.Group.query.join(
            model.DeviceGroup, model.DeviceGroup.group == model.Group.id
        )
        .filter(model.DeviceGroup.device == device.id)
        .order_by(model.Group.label, model.Group.id)
    )
    if not include_inactive:
        groups_query = groups_query.filter(model.Group.active)
    groups = groups_query.all()
    user_perms_query = (
        model.db.session.query(model.UserDevice, model.User)
        .join(model.User, model.User.id == model.UserDevice.user)
        .filter(model.UserDevice.device == device.id)
        .order_by(model.User.id)
    )
    if not include_inactive:
        user_perms_query = user_perms_query.filter(model.User.active)
    user_perms = user_perms_query.all()

    source_nodes: List[Dict[str, str]] = []
    group_rows: List[Dict[str, Any]] = []
    for group in groups:
        source_nodes.append(
            {
                "label": _rbac_group_label(group),
                "meta": _rbac_state(bool(group.active)),
                "href": url_for("rbac", scope="group", entity=group.id),
            }
        )
        group_rows.append(
            {
                "cells": {
                    "group": _rbac_group_label(group),
                    "status": _rbac_state(bool(group.active)),
                },
                "actions": [
                    {
                        "label": "inspect group",
                        "href": url_for("rbac", scope="group", entity=group.id),
                    },
                ],
            }
        )

    target_nodes: List[Dict[str, str]] = []
    special_rows: List[Dict[str, Any]] = []
    for ud, user in user_perms:
        flags = _rbac_permission_flags(ud)
        target_nodes.append(
            {
                "label": _rbac_user_label(user),
                "meta": flags,
                "href": url_for("rbac", scope="user", entity=user.id),
            }
        )
        actions = [
            {
                "label": "inspect user",
                "href": url_for("rbac", scope="user", entity=user.id),
            }
        ]
        special_rows.append(
            {
                "cells": {
                    "user": _rbac_user_label(user),
                    "user_state": _rbac_state(bool(user.active)),
                    "permissions": flags,
                },
                "actions": actions,
            }
        )

    linked_group_ids = {group.id for group in groups}
    all_groups_query = model.Group.query.order_by(model.Group.label, model.Group.id)
    if not include_inactive:
        all_groups_query = all_groups_query.filter(model.Group.active)
    all_groups = all_groups_query.all()
    group_matrix_rows_ranked: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    for group in all_groups:
        linked = group.id in linked_group_ids
        can_link = linked or (group.active and bool(group.department))
        row = {
            "id": group.id,
            "search": (
                f"{group.id} {_rbac_group_label(group)} "
                f"{_rbac_state(bool(group.active))}"
            ),
            "cells": {
                "group": _rbac_group_label(group),
                "group_state": _rbac_state(bool(group.active)),
            },
            "values": {"linked": linked},
            "editable": {"linked": bool(can_link)},
            "operation": {
                "kind": "device.group.set",
                "group": group.id,
                "device": device.id,
            },
        }
        rank = (
            0 if linked else 1,
            0 if group.active else 1,
            (group.label or "").lower(),
            group.id.lower(),
        )
        group_matrix_rows_ranked.append((rank, row))
    group_matrix_rows_ranked.sort(key=lambda entry: entry[0])
    group_matrix_rows = [row for _, row in group_matrix_rows_ranked]
    group_matrix_rows, group_matrix_more = _rbac_limit_rows(
        group_matrix_rows, limit=_RBAC_MATRIX_ROW_LIMIT
    )

    dev_users_query = (
        model.User.query.join(model.Membership, model.Membership.user == model.User.id)
        .filter(model.Membership.group == "DEV")
        .filter(model.Membership.approved)
        .order_by(model.User.id)
    )
    if not include_inactive:
        dev_users_query = dev_users_query.filter(model.Membership.user_active).filter(
            model.User.active
        )
    dev_users = dev_users_query.all()
    dev_user_ids = {user.id for user in dev_users}
    tech_user_ids = {entry.user for entry in model.Technologist.query.all()}
    user_overrides = {ud.user: ud for ud, _ in user_perms}
    user_matrix_ids = sorted(set(dev_user_ids).union(set(user_overrides.keys())))
    users_by_id_query = model.User.query.filter(model.User.id.in_(user_matrix_ids))
    if not include_inactive:
        users_by_id_query = users_by_id_query.filter(model.User.active)
    users_by_id = {user.id: user for user in users_by_id_query.all()}
    user_matrix_rows_ranked: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    for user_id in user_matrix_ids:
        user = users_by_id.get(user_id)
        if user is None:
            continue
        override = user_overrides.get(user_id)
        dev_member = user_id in dev_user_ids
        is_technologist = user_id in tech_user_ids
        templates = bool(override.templates) if override is not None else False
        slot = bool(override.slot) if override is not None else False
        tech = bool(override.tech) if override is not None else False
        medical = bool(override.medical) if override is not None else False
        training = bool(override.training) if override is not None else False
        has_override = any((templates, slot, tech, medical, training))
        can_assign = bool(user.active and dev_member)
        row = {
            "id": user.id,
            "search": (
                f"{user.id} {_rbac_user_label(user)} "
                f"{'dev-member' if dev_member else 'non-dev'} "
                f"{'technologist' if is_technologist else 'non-technologist'}"
            ),
            "cells": {
                "user": _rbac_user_label(user),
                "user_state": _rbac_state(bool(user.active)),
                "dev_member": _rbac_badge(bool(dev_member)),
                "technologist": _rbac_badge(bool(is_technologist)),
            },
            "values": {
                "templates": templates,
                "slot": slot,
                "tech": tech,
                "medical": medical,
                "training": training,
            },
            "editable": {
                "templates": bool(can_assign or templates),
                "slot": bool(can_assign or slot),
                "tech": bool((can_assign and is_technologist) or tech),
                "medical": bool(can_assign or medical),
                "training": bool(can_assign or training),
            },
            "operation": {
                "kind": "user.device.set",
                "device": device.id,
                "user": user.id,
            },
        }
        rank = (
            0 if has_override else 1,
            0 if dev_member else 1,
            0 if user.active else 1,
            (user.label or "").lower(),
            user.id.lower(),
        )
        user_matrix_rows_ranked.append((rank, row))
    user_matrix_rows_ranked.sort(key=lambda entry: entry[0])
    user_matrix_rows = [row for _, row in user_matrix_rows_ranked]
    user_matrix_rows, user_matrix_more = _rbac_limit_rows(
        user_matrix_rows, limit=_RBAC_MATRIX_ROW_LIMIT
    )
    quick_add_user_options = []
    for dev_user in sorted(dev_users, key=lambda row: row.id.lower()):
        if not dev_user.active:
            continue
        suffix = "technologist" if dev_user.id in tech_user_ids else "DEV member"
        quick_add_user_options.append(
            {
                "value": dev_user.id,
                "label": _rbac_user_label(dev_user),
                "meta": suffix,
            }
        )
    quick_add_config: Optional[Dict[str, Any]] = None
    if len(quick_add_user_options) > 0:
        quick_add_config = {
            "label": "+ add DEV user",
            "title": f"Add DEV user permissions for {device.id}",
            "submit_label": "add permissions",
            "scope": "device",
            "entity": device.id,
            "operation": {
                "kind": "user.device.set",
                "device": device.id,
                "expected_templates": False,
                "expected_slot": False,
                "expected_tech": False,
                "expected_medical": False,
                "expected_training": False,
            },
            "fields": [
                {
                    "name": "user",
                    "label": "DEV user",
                    "type": "select",
                    "required": True,
                    "options": quick_add_user_options,
                },
                {
                    "name": "templates",
                    "label": "templates",
                    "type": "checkbox",
                },
                {"name": "slot", "label": "edit any", "type": "checkbox"},
                {"name": "tech", "label": "tech", "type": "checkbox"},
                {"name": "medical", "label": "medical", "type": "checkbox"},
                {
                    "name": "training",
                    "label": "training",
                    "type": "checkbox",
                },
            ],
        }

    left_nodes, left_more = _rbac_slice_graph_nodes(source_nodes)
    right_nodes, right_more = _rbac_slice_graph_nodes(target_nodes)
    group_rows, group_more = _rbac_limit_rows(group_rows)
    special_rows, special_more = _rbac_limit_rows(special_rows)

    return {
        "summary": {
            "title": _rbac_device_label(device),
            "subtitle": "device",
            "badges": [_rbac_state(bool(device.active))],
        },
        "links": [],
        "graph": {
            "source_title": "linked groups",
            "target_title": "user-specific device permissions",
            "focus": {
                "label": _rbac_device_label(device),
                "href": "",
            },
            "sources": left_nodes,
            "targets": right_nodes,
            "source_more": left_more,
            "target_more": right_more,
        },
        "tables": [
            {
                "title": "group links",
                "empty": "No groups linked to this device.",
                "more": group_more,
                "columns": [
                    {"key": "group", "label": "group"},
                    {"key": "status", "label": "group status"},
                ],
                "rows": group_rows,
            },
            {
                "title": "device-specific user permissions",
                "empty": "No device-specific user permissions found.",
                "more": special_more,
                "columns": [
                    {"key": "user", "label": "user"},
                    {"key": "user_state", "label": "user state"},
                    {"key": "permissions", "label": "permissions"},
                ],
                "rows": special_rows,
            },
        ],
        "matrices": [
            {
                "id": "device-metadata-matrix",
                "title": "device settings",
                "description": "Edit device metadata and active state inline.",
                "empty": "Device metadata unavailable.",
                "apply_label": "apply device settings",
                "confirm": f"Apply metadata updates for {device.id}?",
                "more": 0,
                "filter": False,
                "layout": "keyvalue",
                "rows": [
                    {
                        "id": f"{device.id}-label",
                        "search": f"{device.id} label {_rbac_device_label(device)}",
                        "label": "label",
                        "kind": "input",
                        "input_type": "text",
                        "max_length": 25,
                        "field": "label",
                        "value": device.label or "",
                        "editable": True,
                        "operation": {"kind": "device.meta.set", "device": device.id},
                    },
                    {
                        "id": f"{device.id}-description",
                        "search": f"{device.id} description {_rbac_device_label(device)}",
                        "label": "description",
                        "kind": "input",
                        "input_type": "text",
                        "field": "description",
                        "value": device.description or "",
                        "editable": True,
                        "operation": {"kind": "device.meta.set", "device": device.id},
                    },
                    {
                        "id": f"{device.id}-addr",
                        "search": f"{device.id} email {_rbac_device_label(device)}",
                        "label": "email",
                        "kind": "input",
                        "input_type": "text",
                        "field": "addr",
                        "value": device.addr or "",
                        "editable": True,
                        "operation": {"kind": "device.meta.set", "device": device.id},
                    },
                    {
                        "id": f"{device.id}-tech-addr",
                        "search": f"{device.id} tech email {_rbac_device_label(device)}",
                        "label": "tech email",
                        "kind": "input",
                        "input_type": "text",
                        "field": "tech_addr",
                        "value": device.tech_addr or "",
                        "editable": True,
                        "operation": {"kind": "device.meta.set", "device": device.id},
                    },
                    {
                        "id": f"{device.id}-medical-addr",
                        "search": f"{device.id} medical email {_rbac_device_label(device)}",
                        "label": "medical email",
                        "kind": "input",
                        "input_type": "text",
                        "field": "med_addr",
                        "value": device.med_addr or "",
                        "editable": True,
                        "operation": {"kind": "device.meta.set", "device": device.id},
                    },
                    {
                        "id": f"{device.id}-training-addr",
                        "search": f"{device.id} training email {_rbac_device_label(device)}",
                        "label": "training email",
                        "kind": "input",
                        "input_type": "text",
                        "field": "train_addr",
                        "value": device.train_addr or "",
                        "editable": True,
                        "operation": {"kind": "device.meta.set", "device": device.id},
                    },
                    {
                        "id": f"{device.id}-active",
                        "search": f"{device.id} active {_rbac_device_label(device)}",
                        "label": "active",
                        "kind": "checkbox",
                        "field": "active",
                        "value": bool(device.active),
                        "editable": True,
                        "operation": {"kind": "device.meta.set", "device": device.id},
                    },
                ],
            },
            {
                "id": "device-group-links-matrix",
                "title": "group links",
                "description": (
                    "Tick groups that should remain linked to this device."
                ),
                "empty": "No groups found.",
                "apply_label": "apply group links",
                "confirm": f"Apply group link updates for {device.id}?",
                "more": group_matrix_more,
                "columns": [
                    {"key": "group", "label": "group", "kind": "text"},
                    {"key": "group_state", "label": "group state", "kind": "text"},
                    {"key": "linked", "label": "linked", "kind": "checkbox"},
                ],
                "rows": group_matrix_rows,
            },
            {
                "id": "device-user-permissions-matrix",
                "title": "DEV user permissions",
                "description": (
                    "Edit per-user device flags directly. "
                    "Stale legacy overrides can be cleared here."
                ),
                "empty": "No DEV users or overrides found.",
                "apply_label": "apply permission updates",
                "confirm": f"Apply user permission updates for {device.id}?",
                "more": user_matrix_more,
                "quick_add": quick_add_config,
                "columns": [
                    {"key": "user", "label": "user", "kind": "text"},
                    {"key": "user_state", "label": "user state", "kind": "text"},
                    {"key": "dev_member", "label": "DEV member", "kind": "text"},
                    {
                        "key": "technologist",
                        "label": "technologist",
                        "kind": "text",
                    },
                    {"key": "templates", "label": "templates", "kind": "checkbox"},
                    {"key": "slot", "label": "edit any", "kind": "checkbox"},
                    {"key": "tech", "label": "tech", "kind": "checkbox"},
                    {"key": "medical", "label": "medical", "kind": "checkbox"},
                    {"key": "training", "label": "training", "kind": "checkbox"},
                ],
                "rows": user_matrix_rows,
            },
        ],
        "mutations": [],
    }


def _rbac_user_detail(
    user: model.User,
    *,
    include_inactive: bool = False,
) -> Dict[str, Any]:
    memberships_query = model.Membership.query.filter(
        model.Membership.user == user.id
    ).order_by(model.Membership.group)
    if not include_inactive:
        memberships_query = memberships_query.filter(model.Membership.group_active)
    memberships = memberships_query.all()
    user_perms_query = (
        model.db.session.query(model.UserDevice, model.Device)
        .join(model.Device, model.Device.id == model.UserDevice.device)
        .filter(model.UserDevice.user == user.id)
        .order_by(model.Device.label, model.Device.id)
    )
    if not include_inactive:
        user_perms_query = user_perms_query.filter(model.Device.active)
    user_perms = user_perms_query.all()
    device_groups: Dict[str, set[str]] = {}
    for row in model.DeviceGroup.query.all():
        device_groups.setdefault(row.device, set()).add(row.group)
    user_perms_by_device = {ud.device: ud for ud, _ in user_perms}
    memberships_by_group = {row.group: row for row in memberships}

    is_admin = logic.is_admin(user)
    is_dev_pi = (
        model.Membership.query.filter(model.Membership.user == user.id)
        .filter(model.Membership.group == "DEV")
        .filter(model.Membership.pi)
        .filter(model.Membership.user_active)
        .filter(model.Membership.approved)
        .first()
        is not None
    )
    is_technologist = model.Technologist.query.get(user.id) is not None
    is_dev_member, _ = logic.get_dev_tech_status(user)
    approved_groups = {
        row.group
        for row in memberships
        if row.user_active and row.group_active and row.approved
    }

    source_nodes: List[Dict[str, str]] = []
    membership_rows: List[Dict[str, Any]] = []
    for row in memberships:
        status = "approved" if row.approved else "pending"
        group_state = _rbac_state(bool(row.group_active))
        tags = [status, group_state]
        if row.pi:
            tags.append("PI")
        source_nodes.append(
            {
                "label": row.group,
                "meta": ", ".join(tags),
                "href": url_for("rbac", scope="group", entity=row.group),
            }
        )
        actions = [
            {
                "label": "inspect group",
                "href": url_for("rbac", scope="group", entity=row.group),
            }
        ]
        membership_rows.append(
            {
                "cells": {
                    "group": row.group,
                    "status": status,
                    "pi": _rbac_badge(bool(row.pi)),
                    "group_state": group_state,
                },
                "actions": actions,
            }
        )

    target_nodes: List[Dict[str, str]] = []
    special_rows: List[Dict[str, Any]] = []
    for ud, device in user_perms:
        flags = _rbac_permission_flags(ud)
        target_nodes.append(
            {
                "label": _rbac_device_label(device),
                "meta": flags,
                "href": url_for("rbac", scope="device", entity=device.id),
            }
        )
        actions = [
            {
                "label": "inspect device",
                "href": url_for("rbac", scope="device", entity=device.id),
            }
        ]
        special_rows.append(
            {
                "cells": {
                    "device": _rbac_device_label(device),
                    "status": _rbac_state(bool(device.active)),
                    "permissions": flags,
                },
                "actions": actions,
            }
        )

    all_groups_query = model.Group.query.order_by(model.Group.label, model.Group.id)
    if not include_inactive:
        all_groups_query = all_groups_query.filter(model.Group.active)
    all_groups = all_groups_query.all()
    membership_matrix_rows_ranked: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    for group in all_groups:
        membership = memberships_by_group.get(group.id)
        is_member = membership is not None
        approved = bool(membership.approved) if membership is not None else False
        pi = bool(membership.pi) if membership is not None else False
        membership_enabled = bool(group.has_membership)
        can_edit_membership = bool(group.active and (membership_enabled or is_member))
        row = {
            "id": group.id,
            "search": (
                f"{group.id} {_rbac_group_label(group)} "
                f"{_rbac_state(bool(group.active))}"
            ),
            "cells": {
                "group": _rbac_group_label(group),
                "group_state": _rbac_state(bool(group.active)),
                "membership_enabled": _rbac_badge(membership_enabled),
                "pi": _rbac_badge(pi),
            },
            "values": {
                "member": is_member,
                "approved": approved,
            },
            "editable": {
                "member": can_edit_membership,
                "approved": bool(can_edit_membership and is_member and user.active),
            },
            "operation": {
                "kind": "group.membership.set",
                "group": group.id,
                "user": user.id,
            },
        }
        rank = (
            0 if is_member else 1,
            0 if group.active else 1,
            (group.label or "").lower(),
            group.id.lower(),
        )
        membership_matrix_rows_ranked.append((rank, row))
    membership_matrix_rows_ranked.sort(key=lambda entry: entry[0])
    membership_matrix_rows = [row for _, row in membership_matrix_rows_ranked]
    membership_matrix_rows, membership_matrix_more = _rbac_limit_rows(
        membership_matrix_rows, limit=_RBAC_MATRIX_ROW_LIMIT
    )

    all_devices_query = model.Device.query.order_by(model.Device.label, model.Device.id)
    if not include_inactive:
        all_devices_query = all_devices_query.filter(model.Device.active)
    all_devices = all_devices_query.all()
    permission_matrix_rows_ranked: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    for device in all_devices:
        override = user_perms_by_device.get(device.id)
        templates = bool(override.templates) if override is not None else False
        slot = bool(override.slot) if override is not None else False
        tech = bool(override.tech) if override is not None else False
        medical = bool(override.medical) if override is not None else False
        training = bool(override.training) if override is not None else False
        has_override = any((templates, slot, tech, medical, training))
        inherited_edit = bool(
            approved_groups.intersection(device_groups.get(device.id, set()))
        )
        can_assign = bool(user.active and is_dev_member)
        row = {
            "id": device.id,
            "search": (
                f"{device.id} {_rbac_device_label(device)} "
                f"{_rbac_state(bool(device.active))}"
            ),
            "cells": {
                "device": _rbac_device_label(device),
                "device_state": _rbac_state(bool(device.active)),
                "group_edit": _rbac_badge(inherited_edit),
            },
            "values": {
                "templates": templates,
                "slot": slot,
                "tech": tech,
                "medical": medical,
                "training": training,
            },
            "editable": {
                "templates": bool(can_assign or templates),
                "slot": bool(can_assign or slot),
                "tech": bool((can_assign and is_technologist) or tech),
                "medical": bool(can_assign or medical),
                "training": bool(can_assign or training),
            },
            "operation": {
                "kind": "user.device.set",
                "user": user.id,
                "device": device.id,
            },
        }
        rank = (
            0 if has_override else 1,
            0 if inherited_edit else 1,
            0 if device.active else 1,
            (device.label or "").lower(),
            device.id.lower(),
        )
        permission_matrix_rows_ranked.append((rank, row))
    permission_matrix_rows_ranked.sort(key=lambda entry: entry[0])
    permission_matrix_rows = [row for _, row in permission_matrix_rows_ranked]
    permission_matrix_rows, permission_matrix_more = _rbac_limit_rows(
        permission_matrix_rows, limit=_RBAC_MATRIX_ROW_LIMIT
    )

    left_nodes, left_more = _rbac_slice_graph_nodes(source_nodes)
    right_nodes, right_more = _rbac_slice_graph_nodes(target_nodes)
    membership_rows, membership_more = _rbac_limit_rows(membership_rows)
    special_rows, special_more = _rbac_limit_rows(special_rows)

    badges = [_rbac_state(bool(user.active))]
    if is_admin:
        badges.append("admin")
    if is_dev_pi:
        badges.append("DEV PI")
    if is_technologist:
        badges.append("technologist")

    return {
        "summary": {
            "title": _rbac_user_label(user),
            "subtitle": "user",
            "badges": badges,
        },
        "links": [],
        "graph": {
            "source_title": "group memberships",
            "target_title": "device-specific permissions",
            "focus": {"label": _rbac_user_label(user), "href": ""},
            "sources": left_nodes,
            "targets": right_nodes,
            "source_more": left_more,
            "target_more": right_more,
        },
        "tables": [
            {
                "title": "group memberships",
                "empty": "No group memberships found for this user.",
                "more": membership_more,
                "columns": [
                    {"key": "group", "label": "group"},
                    {"key": "status", "label": "status"},
                    {"key": "pi", "label": "pi"},
                    {"key": "group_state", "label": "group state"},
                ],
                "rows": membership_rows,
            },
            {
                "title": "device-specific permissions",
                "empty": "No userdevice permissions found for this user.",
                "more": special_more,
                "columns": [
                    {"key": "device", "label": "device"},
                    {"key": "status", "label": "device state"},
                    {"key": "permissions", "label": "permissions"},
                ],
                "rows": special_rows,
            },
            {
                "title": "effective access guidance",
                "empty": "No additional guidance available.",
                "more": 0,
                "columns": [
                    {"key": "note", "label": "note"},
                ],
                "rows": [
                    {
                        "cells": {
                            "note": (
                                "Use the checkboxes below to edit explicit permissions. "
                                "Group-linked access remains implicit."
                            )
                        },
                        "actions": [],
                    }
                ],
            },
        ],
        "matrices": [
            {
                "id": "user-settings-matrix",
                "title": "user settings",
                "description": "Edit active state and review role flags for this user.",
                "empty": "User settings unavailable.",
                "apply_label": "apply user settings",
                "confirm": f"Apply user settings updates for {user.id}?",
                "more": 0,
                "filter": False,
                "layout": "keyvalue",
                "rows": [
                    {
                        "id": f"{user.id}-active",
                        "search": f"{user.id} active {_rbac_user_label(user)}",
                        "label": "active",
                        "kind": "checkbox",
                        "field": "active",
                        "value": bool(user.active),
                        "editable": True,
                        "operation": {"kind": "user.active.set", "user": user.id},
                    },
                    {
                        "id": f"{user.id}-admin",
                        "search": f"{user.id} admin {_rbac_user_label(user)}",
                        "label": "admin",
                        "kind": "checkbox",
                        "value": bool(is_admin),
                        "editable": False,
                    },
                    {
                        "id": f"{user.id}-dev-pi",
                        "search": f"{user.id} dev pi {_rbac_user_label(user)}",
                        "label": "DEV PI",
                        "kind": "checkbox",
                        "value": bool(is_dev_pi),
                        "editable": False,
                    },
                    {
                        "id": f"{user.id}-technologist",
                        "search": f"{user.id} technologist {_rbac_user_label(user)}",
                        "label": "technologist",
                        "kind": "checkbox",
                        "value": bool(is_technologist),
                        "editable": False,
                    },
                ],
            },
            {
                "id": "user-group-memberships-matrix",
                "title": "group memberships",
                "description": "Review and update membership and approval state across groups.",
                "empty": "No groups found.",
                "apply_label": "apply membership updates",
                "confirm": f"Apply membership updates for {user.id}?",
                "more": membership_matrix_more,
                "columns": [
                    {"key": "group", "label": "group", "kind": "text"},
                    {"key": "group_state", "label": "group state", "kind": "text"},
                    {
                        "key": "membership_enabled",
                        "label": "membership-enabled",
                        "kind": "text",
                    },
                    {"key": "member", "label": "member", "kind": "checkbox"},
                    {"key": "approved", "label": "approved", "kind": "checkbox"},
                    {"key": "pi", "label": "PI", "kind": "text"},
                ],
                "rows": membership_matrix_rows,
                "behavior": "group-membership",
            },
            {
                "id": "user-device-permissions-matrix",
                "title": "device-specific permissions",
                "description": (
                    "Tick explicit device flags. Group-linked edit access is shown in "
                    '"group edit" for context.'
                ),
                "empty": "No devices found.",
                "apply_label": "apply permission updates",
                "confirm": f"Apply device permission updates for {user.id}?",
                "more": permission_matrix_more,
                "columns": [
                    {"key": "device", "label": "device", "kind": "text"},
                    {"key": "device_state", "label": "device state", "kind": "text"},
                    {"key": "group_edit", "label": "group edit", "kind": "text"},
                    {"key": "templates", "label": "templates", "kind": "checkbox"},
                    {"key": "slot", "label": "edit any", "kind": "checkbox"},
                    {"key": "tech", "label": "tech", "kind": "checkbox"},
                    {"key": "medical", "label": "medical", "kind": "checkbox"},
                    {"key": "training", "label": "training", "kind": "checkbox"},
                ],
                "rows": permission_matrix_rows,
            },
        ],
        "mutations": [],
    }


def _rbac_empty_detail(scope: str) -> Dict[str, Any]:
    label = _RBAC_SCOPE_LABELS.get(scope, "items")
    return {
        "summary": {
            "title": f"No {label} found",
            "subtitle": "RBAC explorer",
            "badges": [],
        },
        "links": [],
        "graph": {
            "source_title": "source",
            "target_title": "target",
            "focus": {"label": "Nothing selected", "href": ""},
            "sources": [],
            "targets": [],
            "source_more": 0,
            "target_more": 0,
        },
        "tables": [],
        "matrices": [],
        "mutations": [],
    }


def _rbac_detail(
    scope: str,
    entity: str,
    *,
    include_inactive: bool = False,
) -> Dict[str, Any]:
    if scope == "group":
        group = logic.get_group(entity)
        if group is None:
            abort(404, f"group not found: {entity}")
        if not include_inactive and not group.active:
            abort(404, f"group not found: {entity}")
        return _rbac_group_detail(group, include_inactive=include_inactive)

    if scope == "device":
        device = logic.get_device(entity)
        if device is None:
            abort(404, f"device not found: {entity}")
        if not include_inactive and not device.active:
            abort(404, f"device not found: {entity}")
        return _rbac_device_detail(device, include_inactive=include_inactive)

    if scope == "user":
        user = logic.get_user(entity)
        if user is None:
            abort(404, f"user not found: {entity}")
        if not include_inactive and not user.active:
            abort(404, f"user not found: {entity}")
        return _rbac_user_detail(user, include_inactive=include_inactive)

    abort(400, f"invalid scope: {scope}")


def _rbac_restrict_detail_for_actor(
    scope: str,
    detail: Dict[str, Any],
    actor: Dict[str, Any],
) -> Dict[str, Any]:
    if bool(actor.get("is_admin")):
        return detail

    matrices = detail.get("matrices", [])
    if not isinstance(matrices, list):
        return detail

    restricted: List[Dict[str, Any]] = []
    for matrix in matrices:
        if not isinstance(matrix, dict):
            continue
        matrix_id = str(matrix.get("id", ""))

        if scope == "group":
            if matrix_id == "group-device-links-matrix":
                # Device linkage remains a DEV PI/admin capability.
                continue
            if matrix_id == "group-metadata-matrix":
                rows = matrix.get("rows", [])
                if isinstance(rows, list):
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        field = str(row.get("field", ""))
                        if field in {"inst", "active"}:
                            row["editable"] = False
            restricted.append(matrix)
            continue

        if scope == "device":
            if matrix_id == "device-metadata-matrix":
                rows = matrix.get("rows", [])
                if isinstance(rows, list):
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        if str(row.get("field", "")) == "active":
                            row["editable"] = False
            restricted.append(matrix)
            continue

        restricted.append(matrix)

    detail["matrices"] = restricted

    graph = detail.get("graph", {})
    if isinstance(graph, dict):
        focus = graph.get("focus", {})
        if isinstance(focus, dict):
            href = str(focus.get("href", ""))
            if not _rbac_href_allowed_for_actor(href, actor):
                focus["href"] = ""
        for side in ("sources", "targets"):
            nodes = graph.get(side, [])
            if not isinstance(nodes, list):
                continue
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                href = str(node.get("href", ""))
                if not _rbac_href_allowed_for_actor(href, actor):
                    node["href"] = ""

    tables = detail.get("tables", [])
    if isinstance(tables, list):
        for table in tables:
            if not isinstance(table, dict):
                continue
            rows = table.get("rows", [])
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                actions = row.get("actions", [])
                if not isinstance(actions, list):
                    continue
                filtered_actions = []
                for action in actions:
                    if not isinstance(action, dict):
                        continue
                    href = str(action.get("href", ""))
                    if _rbac_href_allowed_for_actor(href, actor):
                        filtered_actions.append(action)
                row["actions"] = filtered_actions

    return detail


def _rbac_audit_limit() -> int:
    raw_limit = request.args.get("limit", "40").strip()
    if not raw_limit.isdigit():
        abort(400, f"invalid limit: {raw_limit}")
    limit = int(raw_limit)
    if limit < 1 or limit > 200:
        abort(400, "limit must be between 1 and 200")
    return limit


def _rbac_include_inactive_from_request(default: bool = False) -> bool:
    raw = request.args.get("active")
    if raw is None:
        return default
    token = raw.strip().lower()
    return token in {"1", "true", "yes", "on", "all", "inactive"}


def _rbac_audit_rows(
    scope: str,
    entity: str,
    *,
    limit: int,
) -> List[Dict[str, Any]]:
    where = ""
    params: Dict[str, Any] = {"limit": limit}
    if scope != "all" and entity != "":
        params["entity"] = entity
        if scope == "group":
            where = "where deptcode = :entity"
        elif scope == "device":
            where = "where scannercode = :entity"
        elif scope == "user":
            where = (
                "where (researchercode = :entity or requestercode = :entity "
                "or actor = :entity)"
            )
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


def _rbac_required_form_value(name: str) -> str:
    value = request.form.get(name, "").strip()
    if value == "":
        abort(400, f"missing field: {name}")
    return value


def _rbac_json_bool(raw: Any, *, field: str) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)) and raw in (0, 1):
        return bool(raw)
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    raise ValueError(f"invalid boolean value for {field}")


def _rbac_optional_json_bool(
    operation: Dict[str, Any],
    *,
    field: str,
) -> Optional[bool]:
    if field not in operation or operation.get(field) is None:
        return None
    return _rbac_json_bool(operation.get(field), field=field)


def _rbac_optional_json_string(
    operation: Dict[str, Any],
    *,
    field: str,
    max_length: Optional[int] = None,
) -> Optional[str]:
    if field not in operation or operation.get(field) is None:
        return None
    return _rbac_json_string(operation.get(field), field=field, max_length=max_length)


def _rbac_json_string(
    raw: Any,
    *,
    field: str,
    required: bool = False,
    max_length: Optional[int] = None,
) -> str:
    if raw is None:
        value = ""
    elif isinstance(raw, (str, int, float, bool)):
        value = str(raw)
    else:
        raise ValueError(f"invalid value for {field}")
    value = value.strip()
    if required and value == "":
        raise ValueError(f"{field} is required")
    if max_length is not None and len(value) > max_length:
        raise ValueError(f"{field} must be {max_length} characters or fewer")
    return value


def _rbac_validate_optional_url(value: str, *, field: str) -> None:
    if value == "":
        return
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.netloc == "":
        raise ValueError(f"invalid URL for {field}")


def _rbac_audit_preview(value: Any) -> str:
    text_value = str(value if value is not None else "").strip()
    if text_value == "":
        return "none"
    compact = re.sub(r"\s+", " ", text_value).replace(",", ";")
    if len(compact) > 80:
        return f"{compact[:77]}..."
    return compact


class _RBACConflictError(ValueError):
    pass


def _rbac_parse_batch_operations() -> List[Dict[str, Any]]:
    raw = _rbac_required_form_value("operations")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as ex:
        raise ValueError(f"invalid operations payload: {ex.msg}") from ex
    if not isinstance(parsed, list):
        raise ValueError("operations payload must be a list")
    if len(parsed) == 0:
        return []
    if len(parsed) > 1000:
        raise ValueError("operations payload may include at most 1000 changes")
    out: List[Dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            raise ValueError("each operation must be an object")
        out.append(item)
    return out


def _rbac_validate_operation_scope(
    *,
    scope: str,
    entity: str,
    kind: str,
    group_id: str,
    device_id: str,
    user_id: str,
) -> None:
    if scope == "group":
        if group_id != entity:
            raise ValueError(f"{kind} must target selected group {entity}")
        return
    if scope == "device":
        if device_id != entity:
            raise ValueError(f"{kind} must target selected device {entity}")
        return
    if scope == "user":
        if user_id != entity:
            raise ValueError(f"{kind} must target selected user {entity}")
        return
    raise ValueError(f"invalid scope for batch mutation: {scope}")


def _rbac_validate_batch_operation(
    operation: Dict[str, Any],
    *,
    scope: str,
    entity: str,
) -> Dict[str, Any]:
    kind = str(operation.get("kind", "")).strip()
    if kind == "":
        raise ValueError("operation kind is required")

    if kind == "group.active.set":
        group_id = str(operation.get("group", "")).strip()
        if group_id == "":
            raise ValueError("group.active.set requires group")
        _rbac_validate_operation_scope(
            scope=scope,
            entity=entity,
            kind=kind,
            group_id=group_id,
            device_id="",
            user_id="",
        )
        group = logic.get_group(group_id)
        if group is None:
            raise ValueError(f"group not found: {group_id}")
        active = _rbac_json_bool(operation.get("active", True), field="active")
        expected_active = _rbac_optional_json_bool(operation, field="expected_active")
        if group.id in {"admin", "DEV"} and not active:
            raise ValueError(f"special group cannot be deactivated: {group.id}")
        return {
            "kind": kind,
            "group": group,
            "active": active,
            "expected_active": (
                bool(expected_active) if expected_active is not None else False
            ),
            "has_expected_active": expected_active is not None,
        }

    if kind == "device.active.set":
        device_id = str(operation.get("device", "")).strip()
        if device_id == "":
            raise ValueError("device.active.set requires device")
        _rbac_validate_operation_scope(
            scope=scope,
            entity=entity,
            kind=kind,
            group_id="",
            device_id=device_id,
            user_id="",
        )
        device = logic.get_device(device_id)
        if device is None:
            raise ValueError(f"device not found: {device_id}")
        active = _rbac_json_bool(operation.get("active", True), field="active")
        expected_active = _rbac_optional_json_bool(operation, field="expected_active")
        return {
            "kind": kind,
            "device": device,
            "active": active,
            "expected_active": (
                bool(expected_active) if expected_active is not None else False
            ),
            "has_expected_active": expected_active is not None,
        }

    if kind == "user.active.set":
        user_id = str(operation.get("user", "")).strip()
        if user_id == "":
            raise ValueError("user.active.set requires user")
        _rbac_validate_operation_scope(
            scope=scope,
            entity=entity,
            kind=kind,
            group_id="",
            device_id="",
            user_id=user_id,
        )
        user = logic.get_user(user_id)
        if user is None:
            raise ValueError(f"user not found: {user_id}")
        active = _rbac_json_bool(operation.get("active", True), field="active")
        expected_active = _rbac_optional_json_bool(operation, field="expected_active")
        return {
            "kind": kind,
            "user": user,
            "active": active,
            "expected_active": (
                bool(expected_active) if expected_active is not None else False
            ),
            "has_expected_active": expected_active is not None,
        }

    if kind == "group.create":
        if scope != "group":
            raise ValueError("group.create must use group scope")
        group_id = _rbac_json_string(
            operation.get("group", ""),
            field="group",
            required=True,
            max_length=10,
        )
        if group_id in {"admin", "DEV"}:
            raise ValueError(f"group id is reserved: {group_id}")
        if logic.get_group(group_id) is not None:
            raise ValueError(f"group already exists: {group_id}")

        label = _rbac_json_string(
            operation.get("label", ""),
            field="label",
            required=True,
            max_length=20,
        )
        existing_short = model.Group.query.filter(model.Group.label == label).first()
        if existing_short is not None:
            raise ValueError(f"group short label already in use: {label}")

        description = _rbac_json_string(
            operation.get("description", ""),
            field="description",
            required=True,
            max_length=75,
        )
        existing_long = model.Group.query.filter(
            model.Group.description == description
        ).first()
        if existing_long is not None:
            raise ValueError(f"group description already in use: {description}")

        pi_id = _rbac_json_string(
            operation.get("pi", ""),
            field="pi",
            required=True,
            max_length=20,
        )
        pi_user = logic.get_user(pi_id)
        if pi_user is None:
            raise ValueError(f"user not found: {pi_id}")
        if not pi_user.active:
            raise ValueError(f"only active users may be PI: {pi_id}")

        addr = _rbac_json_string(operation.get("addr", ""), field="addr")
        link = _rbac_json_string(operation.get("link", ""), field="link")
        _rbac_validate_optional_url(link, field="link")

        color = _rbac_json_string(
            operation.get("color", "#000000"),
            field="color",
            required=True,
            max_length=7,
        )
        if re.fullmatch(r"#[0-9a-fA-F]{6}", color) is None:
            raise ValueError("color must be a hex value like #1a2b3c")

        inst = _rbac_json_string(
            operation.get("inst", ""),
            field="inst",
            max_length=7,
        )
        if inst != "" and model.Inst.query.get(inst) is None:
            raise ValueError(f"institute not found: {inst}")

        active = _rbac_json_bool(operation.get("active", True), field="active")
        return {
            "kind": kind,
            "group_id": group_id,
            "label": label,
            "description": description,
            "pi_user": pi_user,
            "addr": addr,
            "link": link,
            "color": color,
            "inst": inst,
            "active": active,
        }

    if kind == "device.create":
        if scope != "device":
            raise ValueError("device.create must use device scope")
        device_id = _rbac_json_string(
            operation.get("device", ""),
            field="device",
            required=True,
            max_length=5,
        )
        if logic.get_device(device_id) is not None:
            raise ValueError(f"device already exists: {device_id}")

        label = _rbac_json_string(
            operation.get("label", ""),
            field="label",
            required=True,
            max_length=25,
        )
        existing_label = model.Device.query.filter(model.Device.label == label).first()
        if existing_label is not None:
            raise ValueError(f"device label already in use: {label}")

        description = _rbac_json_string(
            operation.get("description", ""),
            field="description",
        )
        addr = _rbac_json_string(operation.get("addr", ""), field="addr")
        tech_addr = _rbac_json_string(
            operation.get("tech_addr", ""),
            field="tech_addr",
        )
        med_addr = _rbac_json_string(
            operation.get("med_addr", ""),
            field="med_addr",
        )
        train_addr = _rbac_json_string(
            operation.get("train_addr", ""),
            field="train_addr",
        )
        active = _rbac_json_bool(operation.get("active", True), field="active")
        return {
            "kind": kind,
            "device_id": device_id,
            "label": label,
            "description": description,
            "addr": addr,
            "tech_addr": tech_addr,
            "med_addr": med_addr,
            "train_addr": train_addr,
            "active": active,
        }

    if kind == "group.meta.set":
        group_id = str(operation.get("group", "")).strip()
        if group_id == "":
            raise ValueError("group.meta.set requires group")
        _rbac_validate_operation_scope(
            scope=scope,
            entity=entity,
            kind=kind,
            group_id=group_id,
            device_id="",
            user_id="",
        )
        group = logic.get_group(group_id)
        if group is None:
            raise ValueError(f"group not found: {group_id}")
        set_label = "label" in operation
        set_description = "description" in operation
        set_addr = "addr" in operation
        set_link = "link" in operation
        set_color = "color" in operation
        set_inst = "inst" in operation
        set_active = "active" in operation

        label = _rbac_json_string(
            operation.get("label", group.label),
            field="label",
            required=True,
            max_length=20,
        )
        description = _rbac_json_string(
            operation.get("description", group.description),
            field="description",
            required=True,
            max_length=75,
        )
        addr = _rbac_json_string(
            operation.get("addr", group.addr),
            field="addr",
        )
        link = _rbac_json_string(
            operation.get("link", group.link),
            field="link",
        )
        _rbac_validate_optional_url(link, field="link")

        color = _rbac_json_string(
            operation.get("color", group.color),
            field="color",
            max_length=7,
        )
        if color != "" and re.fullmatch(r"#[0-9a-fA-F]{6}", color) is None:
            raise ValueError("color must be a hex value like #1a2b3c")

        inst = _rbac_json_string(
            operation.get("inst", group.inst or ""),
            field="inst",
            max_length=7,
        )
        if inst != "" and model.Inst.query.get(inst) is None:
            raise ValueError(f"institute not found: {inst}")
        active = _rbac_json_bool(operation.get("active", group.active), field="active")

        special_group = group.id in {"admin", "DEV"}
        if special_group and not active:
            raise ValueError(f"special group cannot be deactivated: {group.id}")
        if special_group:
            color = group.color or "#000000"
            inst = group.inst or ""

        expected_label = _rbac_optional_json_string(
            operation,
            field="expected_label",
            max_length=20,
        )
        expected_description = _rbac_optional_json_string(
            operation,
            field="expected_description",
            max_length=75,
        )
        expected_addr = _rbac_optional_json_string(operation, field="expected_addr")
        expected_link = _rbac_optional_json_string(operation, field="expected_link")
        expected_color = _rbac_optional_json_string(
            operation,
            field="expected_color",
            max_length=7,
        )
        expected_inst = _rbac_optional_json_string(
            operation,
            field="expected_inst",
            max_length=7,
        )
        expected_active = _rbac_optional_json_bool(operation, field="expected_active")

        return {
            "kind": kind,
            "group": group,
            "label": label,
            "description": description,
            "addr": addr,
            "link": link,
            "color": color,
            "inst": inst,
            "active": active,
            "special_group": special_group,
            "set_label": set_label,
            "set_description": set_description,
            "set_addr": set_addr,
            "set_link": set_link,
            "set_color": set_color,
            "set_inst": set_inst,
            "set_active": set_active,
            "expected_label": expected_label if expected_label is not None else "",
            "has_expected_label": expected_label is not None,
            "expected_description": (
                expected_description if expected_description is not None else ""
            ),
            "has_expected_description": expected_description is not None,
            "expected_addr": expected_addr if expected_addr is not None else "",
            "has_expected_addr": expected_addr is not None,
            "expected_link": expected_link if expected_link is not None else "",
            "has_expected_link": expected_link is not None,
            "expected_color": expected_color if expected_color is not None else "",
            "has_expected_color": expected_color is not None,
            "expected_inst": expected_inst if expected_inst is not None else "",
            "has_expected_inst": expected_inst is not None,
            "expected_active": (
                bool(expected_active) if expected_active is not None else False
            ),
            "has_expected_active": expected_active is not None,
        }

    if kind == "device.meta.set":
        device_id = str(operation.get("device", "")).strip()
        if device_id == "":
            raise ValueError("device.meta.set requires device")
        _rbac_validate_operation_scope(
            scope=scope,
            entity=entity,
            kind=kind,
            group_id="",
            device_id=device_id,
            user_id="",
        )
        device = logic.get_device(device_id)
        if device is None:
            raise ValueError(f"device not found: {device_id}")
        set_label = "label" in operation
        set_description = "description" in operation
        set_addr = "addr" in operation
        set_tech_addr = "tech_addr" in operation
        set_med_addr = "med_addr" in operation
        set_train_addr = "train_addr" in operation
        set_active = "active" in operation

        label = _rbac_json_string(
            operation.get("label", device.label),
            field="label",
            required=True,
            max_length=25,
        )
        description = _rbac_json_string(
            operation.get("description", device.description),
            field="description",
        )
        addr = _rbac_json_string(
            operation.get("addr", device.addr),
            field="addr",
        )
        tech_addr = _rbac_json_string(
            operation.get("tech_addr", device.tech_addr),
            field="tech_addr",
        )
        med_addr = _rbac_json_string(
            operation.get("med_addr", device.med_addr),
            field="med_addr",
        )
        train_addr = _rbac_json_string(
            operation.get("train_addr", device.train_addr),
            field="train_addr",
        )
        active = _rbac_json_bool(operation.get("active", device.active), field="active")
        expected_label = _rbac_optional_json_string(
            operation,
            field="expected_label",
            max_length=25,
        )
        expected_description = _rbac_optional_json_string(
            operation,
            field="expected_description",
        )
        expected_addr = _rbac_optional_json_string(operation, field="expected_addr")
        expected_tech_addr = _rbac_optional_json_string(
            operation,
            field="expected_tech_addr",
        )
        expected_med_addr = _rbac_optional_json_string(
            operation,
            field="expected_med_addr",
        )
        expected_train_addr = _rbac_optional_json_string(
            operation,
            field="expected_train_addr",
        )
        expected_active = _rbac_optional_json_bool(operation, field="expected_active")

        return {
            "kind": kind,
            "device": device,
            "label": label,
            "description": description,
            "addr": addr,
            "tech_addr": tech_addr,
            "med_addr": med_addr,
            "train_addr": train_addr,
            "active": active,
            "set_label": set_label,
            "set_description": set_description,
            "set_addr": set_addr,
            "set_tech_addr": set_tech_addr,
            "set_med_addr": set_med_addr,
            "set_train_addr": set_train_addr,
            "set_active": set_active,
            "expected_label": expected_label if expected_label is not None else "",
            "has_expected_label": expected_label is not None,
            "expected_description": (
                expected_description if expected_description is not None else ""
            ),
            "has_expected_description": expected_description is not None,
            "expected_addr": expected_addr if expected_addr is not None else "",
            "has_expected_addr": expected_addr is not None,
            "expected_tech_addr": (
                expected_tech_addr if expected_tech_addr is not None else ""
            ),
            "has_expected_tech_addr": expected_tech_addr is not None,
            "expected_med_addr": expected_med_addr
            if expected_med_addr is not None
            else "",
            "has_expected_med_addr": expected_med_addr is not None,
            "expected_train_addr": (
                expected_train_addr if expected_train_addr is not None else ""
            ),
            "has_expected_train_addr": expected_train_addr is not None,
            "expected_active": (
                bool(expected_active) if expected_active is not None else False
            ),
            "has_expected_active": expected_active is not None,
        }

    if kind == "device.group.set":
        group_id = str(operation.get("group", "")).strip()
        device_id = str(operation.get("device", "")).strip()
        if group_id == "" or device_id == "":
            raise ValueError("device.group.set requires group and device")
        _rbac_validate_operation_scope(
            scope=scope,
            entity=entity,
            kind=kind,
            group_id=group_id,
            device_id=device_id,
            user_id="",
        )
        linked = _rbac_json_bool(operation.get("linked", False), field="linked")
        group = logic.get_group(group_id)
        if group is None:
            raise ValueError(f"group not found: {group_id}")
        device = logic.get_device(device_id)
        if device is None:
            raise ValueError(f"device not found: {device_id}")
        existing = model.DeviceGroup.query.get((device.id, group.id)) is not None
        expected_linked = _rbac_optional_json_bool(operation, field="expected_linked")
        if linked and not existing and (not group.active or not bool(group.department)):
            raise ValueError(f"group cannot be linked to devices: {group.id}")
        return {
            "kind": kind,
            "group": group,
            "device": device,
            "linked": linked,
            "existing": existing,
            "expected_linked": (
                bool(expected_linked) if expected_linked is not None else False
            ),
            "has_expected_linked": expected_linked is not None,
        }

    if kind == "user.device.set":
        user_id = str(operation.get("user", "")).strip()
        device_id = str(operation.get("device", "")).strip()
        if user_id == "" or device_id == "":
            raise ValueError("user.device.set requires user and device")
        _rbac_validate_operation_scope(
            scope=scope,
            entity=entity,
            kind=kind,
            group_id="",
            device_id=device_id,
            user_id=user_id,
        )
        user = logic.get_user(user_id)
        if user is None:
            raise ValueError(f"user not found: {user_id}")
        device = logic.get_device(device_id)
        if device is None:
            raise ValueError(f"device not found: {device_id}")

        templates = _rbac_json_bool(
            operation.get("templates", False), field="templates"
        )
        slot = _rbac_json_bool(operation.get("slot", False), field="slot")
        tech = _rbac_json_bool(operation.get("tech", False), field="tech")
        medical = _rbac_json_bool(operation.get("medical", False), field="medical")
        training = _rbac_json_bool(operation.get("training", False), field="training")
        is_dev_member, is_technologist = logic.get_dev_tech_status(user)
        has_any_permission = any((templates, slot, tech, medical, training))
        expected_templates = _rbac_optional_json_bool(
            operation,
            field="expected_templates",
        )
        expected_slot = _rbac_optional_json_bool(operation, field="expected_slot")
        expected_tech = _rbac_optional_json_bool(operation, field="expected_tech")
        expected_medical = _rbac_optional_json_bool(operation, field="expected_medical")
        expected_training = _rbac_optional_json_bool(
            operation,
            field="expected_training",
        )
        expected_state_flags = (
            expected_templates is not None,
            expected_slot is not None,
            expected_tech is not None,
            expected_medical is not None,
            expected_training is not None,
        )
        has_any_expected_permission = any(expected_state_flags)
        has_full_expected_permission = all(expected_state_flags)
        if has_any_expected_permission and not has_full_expected_permission:
            raise ValueError(
                "expected_templates, expected_slot, expected_tech, "
                "expected_medical, and expected_training must all be provided"
            )

        if has_any_permission:
            if not user.active:
                raise ValueError(f"active user not found: {user.id}")
            if not is_dev_member:
                raise ValueError(f"user is not an active DEV member: {user.id}")
            if tech and not is_technologist:
                raise ValueError(f"user is not a technologist: {user.id}")

        return {
            "kind": kind,
            "user": user,
            "device": device,
            "templates": templates,
            "slot": slot,
            "tech": tech,
            "medical": medical,
            "training": training,
            "has_any_permission": has_any_permission,
            "is_technologist": is_technologist,
            "expected_templates": (
                bool(expected_templates) if expected_templates is not None else False
            ),
            "expected_slot": bool(expected_slot)
            if expected_slot is not None
            else False,
            "expected_tech": bool(expected_tech)
            if expected_tech is not None
            else False,
            "expected_medical": (
                bool(expected_medical) if expected_medical is not None else False
            ),
            "expected_training": (
                bool(expected_training) if expected_training is not None else False
            ),
            "has_expected_permissions": has_full_expected_permission,
        }

    if kind == "group.membership.set":
        group_id = str(operation.get("group", "")).strip()
        user_id = str(operation.get("user", "")).strip()
        if group_id == "" or user_id == "":
            raise ValueError("group.membership.set requires group and user")
        if "pi" in operation:
            raise ValueError(
                "group.membership.set no longer accepts pi; use group.pi.set"
            )
        _rbac_validate_operation_scope(
            scope=scope,
            entity=entity,
            kind=kind,
            group_id=group_id,
            device_id="",
            user_id=user_id,
        )
        group = logic.get_group(group_id)
        if group is None:
            raise ValueError(f"group not found: {group_id}")
        if not group.active:
            raise ValueError(f"group is inactive: {group_id}")
        user = logic.get_user(user_id)
        if user is None:
            raise ValueError(f"user not found: {user_id}")
        member = _rbac_json_bool(operation.get("member", False), field="member")
        approved = _rbac_json_bool(operation.get("approved", False), field="approved")
        expected_member = _rbac_optional_json_bool(
            operation,
            field="expected_member",
        )
        expected_approved = _rbac_optional_json_bool(
            operation,
            field="expected_approved",
        )
        if member and not user.active:
            raise ValueError(f"only active users may be assigned membership: {user.id}")
        if not member and approved:
            raise ValueError("non-members cannot be approved")
        has_expected_member = expected_member is not None
        has_expected_approved = expected_approved is not None
        if has_expected_member != has_expected_approved:
            raise ValueError(
                "expected_member and expected_approved must both be provided"
            )
        if expected_member is False and expected_approved:
            raise ValueError("expected non-members cannot be approved")
        return {
            "kind": kind,
            "group": group,
            "user": user,
            "member": member,
            "approved": approved,
            "expected_member": bool(expected_member) if has_expected_member else False,
            "expected_approved": (
                bool(expected_approved) if has_expected_approved else False
            ),
            "has_expected_state": has_expected_member and has_expected_approved,
        }

    if kind == "group.pi.set":
        group_id = str(operation.get("group", "")).strip()
        user_id = str(operation.get("user", "")).strip()
        if group_id == "":
            raise ValueError("group.pi.set requires group")
        if user_id == "":
            raise ValueError("group.pi.set requires user")
        _rbac_validate_operation_scope(
            scope=scope,
            entity=entity,
            kind=kind,
            group_id=group_id,
            device_id="",
            user_id="",
        )
        group = logic.get_group(group_id)
        if group is None:
            raise ValueError(f"group not found: {group_id}")
        if not group.active:
            raise ValueError(f"group is inactive: {group_id}")
        user = logic.get_user(user_id)
        if user is None:
            raise ValueError(f"user not found: {user_id}")
        if not user.active:
            raise ValueError(f"only active users may be PI: {user.id}")
        expected_current_pi = _rbac_optional_json_string(
            operation,
            field="expected_current_pi",
            max_length=20,
        )
        if expected_current_pi is None:
            expected_current_pi = _rbac_optional_json_string(
                operation,
                field="expected_user",
                max_length=20,
            )
        has_expected_current_pi = expected_current_pi is not None
        return {
            "kind": kind,
            "group": group,
            "user": user,
            "expected_current_pi": expected_current_pi or "",
            "has_expected_current_pi": has_expected_current_pi,
        }

    raise ValueError(f"unsupported operation kind: {kind}")


def _rbac_apply_batch_operation(
    validated: Dict[str, Any],
    *,
    source_ip: str,
) -> Tuple[str, bool]:
    kind = str(validated["kind"])

    if kind == "group.create":
        group_id = validated["group_id"]
        pi_user = validated["pi_user"]
        group = model.Group(
            id=group_id,
            label=validated["label"],
            description=validated["description"],
            color=validated["color"],
            addr=validated["addr"],
            link=validated["link"],
            active=bool(validated["active"]),
            inst=validated["inst"] or None,
        )
        model.db.session.add(group)
        model.db.session.add(
            model.GroupMember(user=pi_user.id, group=group.id, approved=func.now())
        )
        model.db.session.add(model.PrimaryGroupMember(user=pi_user.id, group=group.id))
        _record_rbac_action(
            action="group.create",
            where=f"/group/{group.id}",
            how="rbac-explorer-batch",
            what=(
                f"group={group.id}, label={_rbac_audit_preview(group.label)}, "
                f"pi={pi_user.id}, active={_rbac_badge(bool(group.active))}"
            ),
            source_ip=source_ip,
        )
        return (f"Created group {group.id}.", True)

    if kind == "device.create":
        device = model.Device(
            id=validated["device_id"],
            label=validated["label"],
            description=validated["description"],
            addr=validated["addr"],
            tech_addr=validated["tech_addr"],
            med_addr=validated["med_addr"],
            train_addr=validated["train_addr"],
            active=bool(validated["active"]),
        )
        model.db.session.add(device)
        _record_rbac_action(
            action="device.create",
            where=f"/device/{device.id}",
            how="rbac-explorer-batch",
            what=(
                f"device={device.id}, label={_rbac_audit_preview(device.label)}, "
                f"active={_rbac_badge(bool(device.active))}"
            ),
            source_ip=source_ip,
        )
        return (f"Created device {device.id}.", True)

    if kind == "group.active.set":
        group = validated["group"]
        active = bool(validated["active"])
        current_active = bool(group.active)
        if bool(validated.get("has_expected_active")):
            expected_active = bool(validated.get("expected_active"))
            if current_active != expected_active:
                raise _RBACConflictError(
                    "group active-state changed before apply for "
                    f"{group.id}: expected {_rbac_badge(expected_active)}, "
                    f"current {_rbac_badge(current_active)}"
                )
        if current_active == active:
            return (f"{group.id} is already {_rbac_state(active)}.", False)
        previous = current_active
        group.active = active
        model.db.session.add(group)
        _record_rbac_action(
            action="group.update",
            where=f"/group/{group.id}/edit",
            how="rbac-explorer-batch",
            what=(
                f"group={group.id}, "
                f"active={_rbac_badge(previous)}->{_rbac_badge(active)}"
            ),
            source_ip=source_ip,
        )
        return (f"Set {group.id} to {_rbac_state(active)}.", True)

    if kind == "device.active.set":
        device = validated["device"]
        active = bool(validated["active"])
        current_active = bool(device.active)
        if bool(validated.get("has_expected_active")):
            expected_active = bool(validated.get("expected_active"))
            if current_active != expected_active:
                raise _RBACConflictError(
                    "device active-state changed before apply for "
                    f"{device.id}: expected {_rbac_badge(expected_active)}, "
                    f"current {_rbac_badge(current_active)}"
                )
        if current_active == active:
            return (f"{device.id} is already {_rbac_state(active)}.", False)
        previous = current_active
        device.active = active
        model.db.session.add(device)
        _record_rbac_action(
            action="device.update",
            where=f"/device/{device.id}/edit",
            how="rbac-explorer-batch",
            what=(
                f"device={device.id}, "
                f"active={_rbac_badge(previous)}->{_rbac_badge(active)}"
            ),
            source_ip=source_ip,
        )
        return (f"Set {device.id} to {_rbac_state(active)}.", True)

    if kind == "user.active.set":
        user = validated["user"]
        active = bool(validated["active"])
        current_active = bool(user.active)
        if bool(validated.get("has_expected_active")):
            expected_active = bool(validated.get("expected_active"))
            if current_active != expected_active:
                raise _RBACConflictError(
                    "user active-state changed before apply for "
                    f"{user.id}: expected {_rbac_badge(expected_active)}, "
                    f"current {_rbac_badge(current_active)}"
                )
        if current_active == active:
            return (f"{user.id} is already {_rbac_state(active)}.", False)
        previous = current_active
        user.active = active
        model.db.session.add(user)
        _record_rbac_action(
            action="user.update",
            where=f"/rbac?scope=user&entity={user.id}",
            how="rbac-explorer-batch",
            what=(
                f"user={user.id}, active={_rbac_badge(previous)}->{_rbac_badge(active)}"
            ),
            source_ip=source_ip,
        )
        return (f"Set {user.id} to {_rbac_state(active)}.", True)

    if kind == "group.meta.set":
        group = validated["group"]
        if bool(validated.get("has_expected_label")):
            expected_label = str(validated.get("expected_label", ""))
            current_label = group.label or ""
            if current_label != expected_label:
                raise _RBACConflictError(
                    "group metadata changed before apply for "
                    f"{group.id} field label: "
                    f"expected {_rbac_audit_preview(expected_label)}, "
                    f"current {_rbac_audit_preview(current_label)}"
                )
        if bool(validated.get("has_expected_description")):
            expected_description = str(validated.get("expected_description", ""))
            current_description = group.description or ""
            if current_description != expected_description:
                raise _RBACConflictError(
                    "group metadata changed before apply for "
                    f"{group.id} field description: "
                    f"expected {_rbac_audit_preview(expected_description)}, "
                    f"current {_rbac_audit_preview(current_description)}"
                )
        if bool(validated.get("has_expected_addr")):
            expected_addr = str(validated.get("expected_addr", ""))
            current_addr = group.addr or ""
            if current_addr != expected_addr:
                raise _RBACConflictError(
                    "group metadata changed before apply for "
                    f"{group.id} field addr: "
                    f"expected {_rbac_audit_preview(expected_addr)}, "
                    f"current {_rbac_audit_preview(current_addr)}"
                )
        if bool(validated.get("has_expected_link")):
            expected_link = str(validated.get("expected_link", ""))
            current_link = group.link or ""
            if current_link != expected_link:
                raise _RBACConflictError(
                    "group metadata changed before apply for "
                    f"{group.id} field link: "
                    f"expected {_rbac_audit_preview(expected_link)}, "
                    f"current {_rbac_audit_preview(current_link)}"
                )
        if bool(validated.get("has_expected_color")):
            expected_color = str(validated.get("expected_color", ""))
            current_color = group.color or ""
            if current_color != expected_color:
                raise _RBACConflictError(
                    "group metadata changed before apply for "
                    f"{group.id} field color: "
                    f"expected {_rbac_audit_preview(expected_color)}, "
                    f"current {_rbac_audit_preview(current_color)}"
                )
        if bool(validated.get("has_expected_inst")):
            expected_inst = str(validated.get("expected_inst", ""))
            current_inst = group.inst or ""
            if current_inst != expected_inst:
                raise _RBACConflictError(
                    "group metadata changed before apply for "
                    f"{group.id} field inst: "
                    f"expected {_rbac_audit_preview(expected_inst)}, "
                    f"current {_rbac_audit_preview(current_inst)}"
                )
        if bool(validated.get("has_expected_active")):
            expected_active = bool(validated.get("expected_active"))
            current_active = bool(group.active)
            if current_active != expected_active:
                raise _RBACConflictError(
                    "group metadata changed before apply for "
                    f"{group.id} field active: "
                    f"expected {_rbac_badge(expected_active)}, "
                    f"current {_rbac_badge(current_active)}"
                )

        changes: List[str] = []
        if bool(validated.get("set_label")):
            label = validated["label"]
            if group.label != label:
                changes.append(
                    f"label={_rbac_audit_preview(group.label)}->{_rbac_audit_preview(label)}"
                )
                group.label = label
        if bool(validated.get("set_description")):
            description = validated["description"]
            if group.description != description:
                changes.append(
                    "description="
                    f"{_rbac_audit_preview(group.description)}->"
                    f"{_rbac_audit_preview(description)}"
                )
                group.description = description
        if bool(validated.get("set_addr")):
            addr = validated["addr"]
            if group.addr != addr:
                changes.append(
                    f"addr={_rbac_audit_preview(group.addr)}->{_rbac_audit_preview(addr)}"
                )
                group.addr = addr
        if bool(validated.get("set_link")):
            link = validated["link"]
            if group.link != link:
                changes.append(
                    f"link={_rbac_audit_preview(group.link)}->{_rbac_audit_preview(link)}"
                )
                group.link = link
        if bool(validated.get("set_color")):
            color = validated["color"]
            if group.color != color:
                changes.append(
                    f"color={_rbac_audit_preview(group.color)}->{_rbac_audit_preview(color)}"
                )
                group.color = color
        if bool(validated.get("set_inst")):
            inst = validated["inst"]
            next_inst = inst or None
            if group.inst != next_inst:
                changes.append(
                    f"inst={_rbac_audit_preview(group.inst)}->{_rbac_audit_preview(next_inst)}"
                )
                group.inst = next_inst
        if bool(validated.get("set_active")):
            active = bool(validated["active"])
            if group.active != active:
                changes.append(
                    f"active={_rbac_badge(bool(group.active))}->{_rbac_badge(active)}"
                )
                group.active = active

        if len(changes) == 0:
            return (f"Metadata for {group.id} already matches requested state.", False)

        model.db.session.add(group)
        _record_rbac_action(
            action="group.update",
            where=f"/group/{group.id}/edit",
            how="rbac-explorer-batch",
            what=f"group={group.id}, {'; '.join(changes)}",
            source_ip=source_ip,
        )
        return (f"Updated metadata for {group.id}.", True)

    if kind == "device.meta.set":
        device = validated["device"]
        if bool(validated.get("has_expected_label")):
            expected_label = str(validated.get("expected_label", ""))
            current_label = device.label or ""
            if current_label != expected_label:
                raise _RBACConflictError(
                    "device metadata changed before apply for "
                    f"{device.id} field label: "
                    f"expected {_rbac_audit_preview(expected_label)}, "
                    f"current {_rbac_audit_preview(current_label)}"
                )
        if bool(validated.get("has_expected_description")):
            expected_description = str(validated.get("expected_description", ""))
            current_description = device.description or ""
            if current_description != expected_description:
                raise _RBACConflictError(
                    "device metadata changed before apply for "
                    f"{device.id} field description: "
                    f"expected {_rbac_audit_preview(expected_description)}, "
                    f"current {_rbac_audit_preview(current_description)}"
                )
        if bool(validated.get("has_expected_addr")):
            expected_addr = str(validated.get("expected_addr", ""))
            current_addr = device.addr or ""
            if current_addr != expected_addr:
                raise _RBACConflictError(
                    "device metadata changed before apply for "
                    f"{device.id} field addr: "
                    f"expected {_rbac_audit_preview(expected_addr)}, "
                    f"current {_rbac_audit_preview(current_addr)}"
                )
        if bool(validated.get("has_expected_tech_addr")):
            expected_tech_addr = str(validated.get("expected_tech_addr", ""))
            current_tech_addr = device.tech_addr or ""
            if current_tech_addr != expected_tech_addr:
                raise _RBACConflictError(
                    "device metadata changed before apply for "
                    f"{device.id} field tech_addr: "
                    f"expected {_rbac_audit_preview(expected_tech_addr)}, "
                    f"current {_rbac_audit_preview(current_tech_addr)}"
                )
        if bool(validated.get("has_expected_med_addr")):
            expected_med_addr = str(validated.get("expected_med_addr", ""))
            current_med_addr = device.med_addr or ""
            if current_med_addr != expected_med_addr:
                raise _RBACConflictError(
                    "device metadata changed before apply for "
                    f"{device.id} field med_addr: "
                    f"expected {_rbac_audit_preview(expected_med_addr)}, "
                    f"current {_rbac_audit_preview(current_med_addr)}"
                )
        if bool(validated.get("has_expected_train_addr")):
            expected_train_addr = str(validated.get("expected_train_addr", ""))
            current_train_addr = device.train_addr or ""
            if current_train_addr != expected_train_addr:
                raise _RBACConflictError(
                    "device metadata changed before apply for "
                    f"{device.id} field train_addr: "
                    f"expected {_rbac_audit_preview(expected_train_addr)}, "
                    f"current {_rbac_audit_preview(current_train_addr)}"
                )
        if bool(validated.get("has_expected_active")):
            expected_active = bool(validated.get("expected_active"))
            current_active = bool(device.active)
            if current_active != expected_active:
                raise _RBACConflictError(
                    "device metadata changed before apply for "
                    f"{device.id} field active: "
                    f"expected {_rbac_badge(expected_active)}, "
                    f"current {_rbac_badge(current_active)}"
                )

        changes: List[str] = []
        if bool(validated.get("set_label")):
            label = validated["label"]
            if device.label != label:
                changes.append(
                    f"label={_rbac_audit_preview(device.label)}->{_rbac_audit_preview(label)}"
                )
                device.label = label
        if bool(validated.get("set_description")):
            description = validated["description"]
            if device.description != description:
                changes.append(
                    "description="
                    f"{_rbac_audit_preview(device.description)}->"
                    f"{_rbac_audit_preview(description)}"
                )
                device.description = description
        if bool(validated.get("set_addr")):
            addr = validated["addr"]
            if device.addr != addr:
                changes.append(
                    f"addr={_rbac_audit_preview(device.addr)}->{_rbac_audit_preview(addr)}"
                )
                device.addr = addr
        if bool(validated.get("set_tech_addr")):
            tech_addr = validated["tech_addr"]
            if device.tech_addr != tech_addr:
                changes.append(
                    "tech_addr="
                    f"{_rbac_audit_preview(device.tech_addr)}->"
                    f"{_rbac_audit_preview(tech_addr)}"
                )
                device.tech_addr = tech_addr
        if bool(validated.get("set_med_addr")):
            med_addr = validated["med_addr"]
            if device.med_addr != med_addr:
                changes.append(
                    "med_addr="
                    f"{_rbac_audit_preview(device.med_addr)}->"
                    f"{_rbac_audit_preview(med_addr)}"
                )
                device.med_addr = med_addr
        if bool(validated.get("set_train_addr")):
            train_addr = validated["train_addr"]
            if device.train_addr != train_addr:
                changes.append(
                    "train_addr="
                    f"{_rbac_audit_preview(device.train_addr)}->"
                    f"{_rbac_audit_preview(train_addr)}"
                )
                device.train_addr = train_addr
        if bool(validated.get("set_active")):
            active = bool(validated["active"])
            if device.active != active:
                changes.append(
                    f"active={_rbac_badge(bool(device.active))}->{_rbac_badge(active)}"
                )
                device.active = active

        if len(changes) == 0:
            return (
                f"Metadata for {device.id} already matches requested state.",
                False,
            )

        model.db.session.add(device)
        _record_rbac_action(
            action="device.update",
            where=f"/device/{device.id}/edit",
            how="rbac-explorer-batch",
            what=f"device={device.id}, {'; '.join(changes)}",
            source_ip=source_ip,
        )
        return (f"Updated metadata for {device.id}.", True)

    if kind == "device.group.set":
        group = validated["group"]
        device = validated["device"]
        linked = bool(validated["linked"])
        existing = model.DeviceGroup.query.get((device.id, group.id))
        before_linked = existing is not None
        if bool(validated.get("has_expected_linked")):
            expected_linked = bool(validated.get("expected_linked"))
            if before_linked != expected_linked:
                raise _RBACConflictError(
                    "device/group link changed before apply for "
                    f"{device.id}/{group.id}: "
                    f"expected linked={_rbac_badge(expected_linked)}, "
                    f"current linked={_rbac_badge(before_linked)}"
                )
        if linked:
            if before_linked:
                return (f"{group.id} is already linked to {device.id}.", False)
            model.db.session.add(model.DeviceGroup(group=group.id, device=device.id))
            _record_rbac_action(
                action="device.group.add",
                where=f"/device/{device.id}/groups/add",
                how="rbac-explorer-batch",
                what=f"device={device.id}, group={group.id}",
                source_ip=source_ip,
            )
            return (f"Linked {group.id} to {device.id}.", True)

        if not before_linked:
            return (f"{group.id} is not linked to {device.id}.", False)
        model.db.session.delete(existing)
        _record_rbac_action(
            action="device.group.remove",
            where=f"/device/{device.id}/groups",
            how="rbac-explorer-batch",
            what=f"device={device.id}, group={group.id}",
            source_ip=source_ip,
        )
        return (f"Unlinked {group.id} from {device.id}.", True)

    if kind == "user.device.set":
        user = validated["user"]
        device = validated["device"]
        templates = bool(validated["templates"])
        slot = bool(validated["slot"])
        tech = bool(validated["tech"]) and bool(validated["is_technologist"])
        medical = bool(validated["medical"])
        training = bool(validated["training"])
        has_any_permission = bool(validated["has_any_permission"])
        existing = model.UserDevice.query.get((user.id, device.id))
        before = (
            (
                bool(existing.templates),
                bool(existing.slot),
                bool(existing.tech),
                bool(existing.medical),
                bool(existing.training),
            )
            if existing is not None
            else (False, False, False, False, False)
        )
        if bool(validated.get("has_expected_permissions")):
            expected = (
                bool(validated.get("expected_templates")),
                bool(validated.get("expected_slot")),
                bool(validated.get("expected_tech")),
                bool(validated.get("expected_medical")),
                bool(validated.get("expected_training")),
            )
            if before != expected:
                raise _RBACConflictError(
                    "user/device permissions changed before apply for "
                    f"{user.id}/{device.id}: "
                    f"expected templates={_rbac_badge(expected[0])}, "
                    f"slot={_rbac_badge(expected[1])}, "
                    f"tech={_rbac_badge(expected[2])}, "
                    f"medical={_rbac_badge(expected[3])}, "
                    f"training={_rbac_badge(expected[4])}; "
                    f"current templates={_rbac_badge(before[0])}, "
                    f"slot={_rbac_badge(before[1])}, "
                    f"tech={_rbac_badge(before[2])}, "
                    f"medical={_rbac_badge(before[3])}, "
                    f"training={_rbac_badge(before[4])}"
                )

        if has_any_permission:
            after = (templates, slot, tech, medical, training)
            if before == after:
                return (
                    f"Permissions for {user.id} on {device.id} already match requested state.",
                    False,
                )
            row = existing
            if row is None:
                row = model.UserDevice(user=user.id, device=device.id)
            row.templates = templates
            row.slot = slot
            row.tech = tech
            row.medical = medical
            row.training = training
            model.db.session.add(row)
            _record_rbac_action(
                action="user.device.update",
                where=f"/device/{device.id}/users/{user.id}",
                how="rbac-explorer-batch",
                what=(
                    f"device={device.id}, user={user.id}, "
                    f"permissions={_rbac_permission_flags(row)}"
                ),
                source_ip=source_ip,
            )
            return (
                f"Updated device-specific permissions for {user.id} on {device.id}.",
                True,
            )

        if existing is None:
            return (
                f"{user.id} has no device-specific permissions on {device.id}.",
                False,
            )
        model.db.session.delete(existing)
        _record_rbac_action(
            action="user.device.remove",
            where=f"/device/{device.id}/users/{user.id}",
            how="rbac-explorer-batch",
            what=f"device={device.id}, user={user.id}",
            source_ip=source_ip,
        )
        return (
            f"Removed device-specific permissions for {user.id} on {device.id}.",
            True,
        )

    if kind == "group.membership.set":
        group = validated["group"]
        user = validated["user"]
        member = bool(validated["member"])
        approved = bool(validated["approved"])
        existing = model.GroupMember.query.get((group.id, user.id))
        was_member = existing is not None
        was_approved = (
            bool(existing.approved is not None) if existing is not None else False
        )
        before = (was_member, was_approved)
        after = (member, approved if member else False)
        if bool(validated.get("has_expected_state")):
            expected = (
                bool(validated.get("expected_member")),
                bool(validated.get("expected_approved")),
            )
            if expected[0] is False:
                expected = (False, False)
            if before != expected:
                raise _RBACConflictError(
                    "membership state changed before apply for "
                    f"{group.id}/{user.id}: "
                    f"expected member={_rbac_badge(expected[0])}, "
                    f"approved={_rbac_badge(expected[1])}; "
                    f"current member={_rbac_badge(before[0])}, "
                    f"approved={_rbac_badge(before[1])}"
                )

        if member:
            row = existing
            if row is None:
                row = model.GroupMember(user=user.id, group=group.id)
            if approved:
                if row.approved is None:
                    row.approved = func.now()
            else:
                row.approved = None
            model.db.session.add(row)
        elif existing is not None:
            model.db.session.delete(existing)

        if before == after:
            return (
                f"Membership for {user.id} in {group.id} already matches requested state.",
                False,
            )

        _record_rbac_action(
            action="group.membership.set",
            where=f"/group/{group.id}/membership",
            how="rbac-explorer-batch",
            what=(
                f"group={group.id}, user={user.id}, "
                f"member={_rbac_badge(member)}, "
                f"approved={_rbac_badge(approved)}"
            ),
            source_ip=source_ip,
        )
        return (f"Updated membership for {user.id} in {group.id}.", True)

    if kind == "group.pi.set":
        group = validated["group"]
        user = validated["user"]
        current_pi = (
            model.Membership.query.filter(model.Membership.group == group.id)
            .filter(model.Membership.pi)
            .first()
        )
        current_pi_user = current_pi.user if current_pi is not None else ""
        expected_current_pi = str(validated.get("expected_current_pi", "")).strip()
        if bool(validated.get("has_expected_current_pi")):
            if expected_current_pi != current_pi_user:
                raise _RBACConflictError(
                    "PI assignment changed before apply for "
                    f"{group.id}: expected {expected_current_pi or 'none'}, "
                    f"current {current_pi_user or 'none'}"
                )

        approved_members = {
            row.user
            for row in (
                model.Membership.query.filter(model.Membership.group == group.id)
                .filter(model.Membership.approved)
                .filter(model.Membership.user_active)
                .filter(model.Membership.group_active)
                .all()
            )
        }
        if user.id not in approved_members:
            raise ValueError(
                f"PI must be an approved active member of {group.id}: {user.id}"
            )
        if user.id != current_pi_user:
            logic.change_pi_of_group(group, user)
            _record_rbac_action(
                action="group.pi.update",
                where=f"/group/{group.id}/pi",
                how="rbac-explorer-batch",
                what=f"group={group.id}, from={current_pi_user or 'none'}, to={user.id}",
                source_ip=source_ip,
            )
            return (f"Updated PI for {group.id} to {user.id}.", True)
        return (f"PI for {group.id} already matches requested state.", False)

    raise ValueError(f"unsupported operation kind: {kind}")


def _rbac_authorize_batch_operation(
    validated: Dict[str, Any], actor: Dict[str, Any]
) -> None:
    if bool(actor.get("is_admin")):
        return

    kind = str(validated.get("kind", ""))
    managed_groups = _rbac_actor_managed_groups(actor)
    is_dev_pi = bool(actor.get("is_dev_pi"))

    if kind in {"group.meta.set", "group.membership.set", "group.pi.set"}:
        group = validated["group"]
        if group.id not in managed_groups:
            raise PermissionError(f"group not managed by current user: {group.id}")
        if not bool(group.active):
            raise PermissionError(f"inactive group requires admin access: {group.id}")
        if kind == "group.meta.set":
            if (validated.get("inst") or "") != (group.inst or ""):
                raise PermissionError("group institute edits require admin access")
            if bool(validated.get("active")) != bool(group.active):
                raise PermissionError("group active-state edits require admin access")
        return

    if kind in {"device.meta.set", "device.group.set", "user.device.set"}:
        if not is_dev_pi:
            raise PermissionError("device RBAC updates require DEV PI or admin access")
        device = validated["device"]
        if not bool(device.active):
            raise PermissionError(f"inactive device requires admin access: {device.id}")
        if kind == "device.meta.set" and bool(validated.get("active")) != bool(
            device.active
        ):
            raise PermissionError("device active-state edits require admin access")
        return

    raise PermissionError(f"operation requires admin access: {kind}")


def _rbac_mutate_batch(
    scope: str, entity: str, *, actor: Dict[str, Any]
) -> Tuple[Dict[str, Any], int]:
    operations = _rbac_parse_batch_operations()
    if len(operations) == 0:
        return (
            {
                "ok": True,
                "atomic": True,
                "scope": scope,
                "entity": entity,
                "applied": 0,
                "total": 0,
                "results": [],
                "message": "No changes submitted.",
            },
            200,
        )

    validated: List[Dict[str, Any]] = []
    validation_results: List[Dict[str, Any]] = []
    has_validation_error = False
    for index, operation in enumerate(operations):
        kind = str(operation.get("kind", "")).strip() or "unknown"
        try:
            normalized = _rbac_validate_batch_operation(
                operation, scope=scope, entity=entity
            )
            validated.append(normalized)
            validation_results.append(
                {"index": index, "kind": kind, "status": "pending", "message": ""}
            )
        except ValueError as ex:
            has_validation_error = True
            validation_results.append(
                {
                    "index": index,
                    "kind": kind,
                    "status": "invalid",
                    "message": str(ex),
                }
            )

    if has_validation_error:
        return (
            {
                "ok": False,
                "atomic": True,
                "scope": scope,
                "entity": entity,
                "applied": 0,
                "total": len(operations),
                "results": validation_results,
                "message": "Validation failed. No RBAC changes were applied.",
            },
            400,
        )

    has_authz_error = False
    for index, validated_operation in enumerate(validated):
        try:
            _rbac_authorize_batch_operation(validated_operation, actor)
        except PermissionError as ex:
            has_authz_error = True
            validation_results[index]["status"] = "forbidden"
            validation_results[index]["message"] = str(ex)

    if has_authz_error:
        return (
            {
                "ok": False,
                "atomic": True,
                "scope": scope,
                "entity": entity,
                "applied": 0,
                "total": len(operations),
                "results": validation_results,
                "message": "Permission denied. No RBAC changes were applied.",
            },
            403,
        )

    source_ip = _request_client_ip()
    results: List[Dict[str, Any]] = []
    try:
        for index, validated_operation in enumerate(validated):
            try:
                message, changed = _rbac_apply_batch_operation(
                    validated_operation, source_ip=source_ip
                )
            except _RBACConflictError as ex:
                results.append(
                    {
                        "index": index,
                        "kind": validated_operation["kind"],
                        "status": "conflict",
                        "message": str(ex),
                    }
                )
                raise
            results.append(
                {
                    "index": index,
                    "kind": validated_operation["kind"],
                    "status": "applied" if changed else "unchanged",
                    "message": message,
                }
            )

        model.db.session.commit()
    except _RBACConflictError as ex:
        model.db.session.rollback()
        for row in results:
            if row["status"] == "applied":
                row["status"] = "rolled_back"
        return (
            {
                "ok": False,
                "atomic": True,
                "scope": scope,
                "entity": entity,
                "applied": 0,
                "total": len(operations),
                "results": results,
                "message": str(ex),
            },
            409,
        )
    except ValueError as ex:
        model.db.session.rollback()
        for row in results:
            if row["status"] == "applied":
                row["status"] = "rolled_back"
        return (
            {
                "ok": False,
                "atomic": True,
                "scope": scope,
                "entity": entity,
                "applied": 0,
                "total": len(operations),
                "results": results,
                "message": str(ex),
            },
            400,
        )
    except IntegrityError:
        model.db.session.rollback()
        for row in results:
            if row["status"] == "applied":
                row["status"] = "rolled_back"
        return (
            {
                "ok": False,
                "atomic": True,
                "scope": scope,
                "entity": entity,
                "applied": 0,
                "total": len(operations),
                "results": results,
                "message": "RBAC data changed concurrently. No RBAC changes were applied.",
            },
            409,
        )
    except Exception:
        model.db.session.rollback()
        app.logger.exception("RBAC batch mutation failed")
        for row in results:
            if row["status"] == "applied":
                row["status"] = "rolled_back"
        return (
            {
                "ok": False,
                "atomic": True,
                "scope": scope,
                "entity": entity,
                "applied": 0,
                "total": len(operations),
                "results": results,
                "message": "Failed to apply RBAC batch updates.",
            },
            500,
        )

    applied_count = sum(1 for row in results if row["status"] == "applied")
    return (
        {
            "ok": True,
            "atomic": True,
            "scope": scope,
            "entity": entity,
            "applied": applied_count,
            "total": len(operations),
            "results": results,
            "message": (
                f"Applied {applied_count} of {len(operations)} requested RBAC changes."
            ),
        },
        200,
    )


@app.route("/json/v1/rbac/explorer")
@active_user_required
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


@app.route("/json/v1/rbac/audit")
@admin_only
def rbac_explorer_audit():
    scope = request.args.get("scope", "group").strip().lower()
    if scope not in _RBAC_AUDIT_SCOPE_LABELS:
        abort(400, f"invalid scope: {scope}")

    entity = request.args.get("entity", "").strip()
    limit = _rbac_audit_limit()
    if not logic.rbac_audit_table_available():
        return jsonify(
            {
                "scope": scope,
                "selected": entity,
                "limit": limit,
                "count": 0,
                "events": [],
            }
        )

    try:
        rows = _rbac_audit_rows(scope, entity, limit=limit)
    except Exception:
        model.db.session.rollback()
        app.logger.exception("Failed to query RBAC audit feed")
        rows = []
    events = [_rbac_audit_payload(row) for row in rows]

    return jsonify(
        {
            "scope": scope,
            "selected": entity,
            "limit": limit,
            "count": len(events),
            "events": events,
        }
    )


@app.route("/json/v1/rbac/mutate", methods=["POST"])
@active_user_required
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


@app.route("/groups")
@active_user_required
@render_to("groups")
def groups():
    memberships = logic.get_memberships(g.user)
    is_admin = "admin" in memberships
    if is_admin:
        abort(404)

    groups = logic.get_groups(memberships)

    return {
        "title": "groups",
        "groups": groups,
        **groups_subpage_nav(is_admin),
        **groups_breadcrumb(),
    }


@app.route("/rbac")
@active_user_required
@render_to("rbac")
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
        "csrf_form": logic.CsrfOnlyForm(),
        **breadcrumb("RBAC"),
    }


def _build_potential_issues() -> List[Dict[str, str]]:
    issues: List[Dict[str, str]] = []

    if not logic.rbac_audit_table_available():
        issues.append(
            {
                "severity": "warning",
                "category": "logging",
                "title": "RBAC audit persistence is unavailable",
                "detail": (
                    "The rbac_audit_log table is missing or inaccessible. "
                    "RBAC events can still execute, but timeline history will be empty."
                ),
                "href": url_for("rbac"),
                "link_label": "open RBAC explorer",
            }
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
            issues.append(
                {
                    "severity": "warning",
                    "category": "membership workflow",
                    "title": f"Group {group.id} has no active PI configured",
                    "detail": (
                        "Join requests can be submitted but no PI can be notified to review them."
                        f"{pending_suffix}"
                    ),
                    "href": group_membership_url,
                    "link_label": "open in RBAC explorer",
                }
            )
            continue

        for pi_id in pi_ids:
            pi_user = logic.get_user(pi_id)
            if pi_user is None:
                issues.append(
                    {
                        "severity": "warning",
                        "category": "data integrity",
                        "title": f"Group {group.id} references missing PI user {pi_id}",
                        "detail": (
                            "The PI reference cannot be resolved to an active user record."
                        ),
                        "href": group_membership_url,
                        "link_label": "open in RBAC explorer",
                    }
                )
                continue
            if not pi_user.active:
                issues.append(
                    {
                        "severity": "warning",
                        "category": "membership workflow",
                        "title": f"Group {group.id} PI {pi_user.id} is inactive",
                        "detail": (
                            "Inactive PI users cannot reliably review join requests."
                        ),
                        "href": group_membership_url,
                        "link_label": "open in RBAC explorer",
                    }
                )
                continue
            if (pi_user.addr or "").strip() == "":
                issues.append(
                    {
                        "severity": "warning",
                        "category": "notifications",
                        "title": f"Group {group.id} PI {pi_user.id} has no email address",
                        "detail": (
                            "Join-request notifications cannot be delivered to this PI."
                        ),
                        "href": group_membership_url,
                        "link_label": "open in RBAC explorer",
                    }
                )

    dev_pi_ids = sorted(set(pi_by_group.get("DEV", [])))
    if len(dev_pi_ids) == 0:
        issues.append(
            {
                "severity": "warning",
                "category": "technologist workflow",
                "title": "DEV group has no active PI configured",
                "detail": (
                    "Technologist application notifications cannot be routed to a DEV PI."
                ),
                "href": url_for("rbac", scope="group", entity="DEV"),
                "link_label": "open DEV in RBAC explorer",
            }
        )
    else:
        has_dev_pi_contact = False
        for dev_pi_id in dev_pi_ids:
            dev_pi_user = logic.get_user(dev_pi_id)
            if dev_pi_user is None:
                continue
            if not dev_pi_user.active:
                continue
            if (dev_pi_user.addr or "").strip() == "":
                continue
            has_dev_pi_contact = True
            break
        if not has_dev_pi_contact:
            issues.append(
                {
                    "severity": "warning",
                    "category": "technologist workflow",
                    "title": "DEV PI notification contact is unavailable",
                    "detail": (
                        "Technologist application notifications are configured, "
                        "but no active DEV PI currently has a usable email address."
                    ),
                    "href": url_for("rbac", scope="group", entity="DEV"),
                    "link_label": "open DEV in RBAC explorer",
                }
            )

    return issues


@app.route("/app/issues")
@admin_only
@render_to("rbac_audit")
def app_issues():
    scope = request.args.get("scope", "all").strip().lower()
    if scope not in _RBAC_AUDIT_SCOPE_LABELS:
        scope = "all"
    entity = request.args.get("entity", "").strip()

    raw_limit = request.args.get("limit", "200").strip()
    if raw_limit.isdigit():
        limit = int(raw_limit)
    else:
        limit = 200
    limit = max(1, min(limit, 500))

    events: List[Dict[str, Any]] = []
    if logic.rbac_audit_table_available():
        try:
            rows = _rbac_audit_rows(scope, entity, limit=limit)
            events = [_rbac_audit_payload(row) for row in rows]
        except Exception:
            model.db.session.rollback()
            app.logger.exception("Failed to query RBAC audit page")

    potential_issues = _build_potential_issues()

    return {
        "title": "Potential issues",
        "scope": scope,
        "entity": entity,
        "limit": limit,
        "events": events,
        "potential_issues": potential_issues,
        "audit_scopes": [
            {"id": scope_id, "label": scope_label, "selected": scope == scope_id}
            for scope_id, scope_label in _RBAC_AUDIT_SCOPE_LABELS.items()
        ],
        **breadcrumb(("RBAC", url_for("rbac")), "Potential issues"),
    }


# shared subpage nav for all group pages
def group_subpage_nav(group: model.Group, su: logic.Group_leader_kind) -> Subpage_links:
    _ = su
    return subpage_nav(
        "show",
        [
            # view has further protections, but if you can see any of them you can see it
            (True, f"view [{group.label}]", url_for("group", the_group=group.id)),
        ],
    )


def group_breadcrumb(group: model.Group) -> Breadcrumb_links:
    return breadcrumb(
        ("groups", url_for("groups")),
        (group.label, url_for("group", the_group=group.id)),
    )


@app.route("/group/<the_group>")
@active_user_required
@render_to("group")
def group(the_group):
    group = logic.get_group(the_group)
    if group is None:
        abort(404)

    su = logic.get_group_leader_kind(g.user, group)
    if "admin" in su:
        abort(404)

    # inactive groups cannot be viewed from this legacy page.
    if not group.active:
        abort(403)

    members = logic.get_members_of_group(group)

    # must be admin, dev_pi, or member
    if not (len(su) > 0 or any(m == g.user.id for (m, _, _) in members)):
        abort(403)

    return {
        "group": group,
        "members": members,
        "su": su,
        **group_subpage_nav(group, su),
        **group_breadcrumb(group),
    }


@app.route("/group/<the_group>/edit", methods=["GET", "POST"])
@active_user_required
@render_to("group_edit")
def group_edit(the_group):
    _ = the_group
    abort(404)


@app.route("/group/<the_group>/membership", methods=["GET", "POST"])
@active_user_required
@render_to("group_membership")
def group_membership(the_group):
    _ = the_group
    abort(404)


@app.route("/group/<the_group>/pi", methods=["GET", "POST"])
@active_user_required
@render_to("group_pi")
def group_pi(the_group):
    _ = the_group
    abort(404)


def devices_breadcrumb() -> Breadcrumb_links:
    return breadcrumb(("devices", url_for("devices")))


def devices_subpage_nav(_is_admin: bool) -> Subpage_links:
    return subpage_nav(
        "show [which devices]",
        [
            (True, "active [devices]", url_for("devices")),
        ],
    )


@app.route("/devices")
@login_required
@render_to("devices")
def devices():
    is_admin = logic.is_admin(g.user)
    if is_admin:
        abort(404)
    devices = logic.get_devices(True)
    return {
        "title": "devices",
        "devices": devices,
        **devices_subpage_nav(is_admin),
        **devices_breadcrumb(),
    }


def device_breadcrumb(device: model.Device) -> Breadcrumb_links:
    return breadcrumb(
        ("devices", url_for("devices")),
        (device.label, url_for("device", the_device=device.id)),
    )


def schedule_window_from_request() -> tuple:
    # get the date, defaulting to today
    date = None
    the_date = request.args.get("start")
    if the_date is not None:
        date = logic.parse_date(the_date)
        if date is None:
            abort(400, f"invalid start: {the_date} (must be YYYY-MM-DD date)")
    date = logic.date_or_today(date)

    # get the number of days to show, defaulting to 7
    days = 7
    the_days = request.args.get("days")
    if the_days is not None:
        days = logic.parse_days(the_days)
        if days is None:
            abort(400, f"invalid days: {the_days} (must be in 1-31)")

    # day windows are inclusive of the start date, so subtract one day here.
    end_date = logic.end_date(date, days - 1)

    return date, days, end_date


def device_subpage_nav(device: model.Device, perms: logic.DevicePerms) -> Subpage_links:
    def can(permission: bool) -> bool:
        return perms.admin or (permission and device.active)

    id = device.id
    return subpage_nav(
        "show",
        [
            (True, "schedule", url_for("device", the_device=id)),
            (can(perms.template), "templates", url_for("device_tmpl", the_device=id)),
        ],
    )


@app.route("/device/<the_device>", methods=["GET", "POST"])
@login_required
@render_to("device")
def device(the_device):
    device = logic.get_device(the_device)
    if device is None:
        abort(404)

    perms = logic.get_dev_perms(g.user, device)

    if not (device.active or perms.admin):
        abort(403)

    date, days, end_date = schedule_window_from_request()

    min, max = logic.device_schedule_extreme_dates(device)

    fmt_start_date = logic.fmt_date(date)
    fmt_end_date = logic.fmt_date(end_date)
    fmt_min = ""
    fmt_max = ""
    if min is not None:
        fmt_min = logic.fmt_date(min)
        fmt_max = logic.fmt_date(max)

    # compute which hours to hide by default
    off_hours = logic.off_hours()
    used_hours = logic.schedule_used_hours_for(device, date, end_date)
    off_hours.difference_update(used_hours)
    off_hour_runs = logic.group_off_hours_into_runs(off_hours)
    off_hour_map = logic.convert_off_hour_runs_into_map(off_hour_runs)

    no_entries = ""
    never_entries = ""
    if not logic.schedule_exists_for(device, date, end_date):
        if min is None:
            never_entries = "this device has not yet had any entries scheduled on it"
        else:
            no_entries = f"no entries scheduled for {fmt_start_date}. All entries are between {fmt_min} and {fmt_max}"

    colors = logic.all_group_colors()

    # need to determine if user can edit this
    support = logic.SupportRequestDatalists([], [], [])
    members_of_groups = {}
    groups = []
    device_groups = logic.all_groups_of_device(device)

    # load any data user may need to edit
    if device.active and perms.edit:
        support = logic.support_request_datalists(device)

        # load all relevant group-member datalists
        if perms.edit_any:
            members_of_groups = logic.all_member_datalists_by_group(device)
            groups = device_groups
        else:
            members_of_groups = logic.member_datalists_by_group_for(device, g.user)
            groups = logic.groups_of_device_for(device, g.user)

    perms_json = {  # the permissions the js needs
        "edit": perms.edit,
        "edit_any": perms.edit_any,
        "tech": perms.tech,
        "medical": perms.medical,
        "training": perms.training,
    }
    groups_json = [id for (id, _) in groups]
    device_groups_json = [id for (id, _) in device_groups]

    top_row = [
        logic.fmt_date(date + timedelta(days=n), with_day=True) for n in range(days)
    ]

    hours = logic.fmt_hours()
    cur_date, cur_hour, cur_minute = logic.db_now()

    form = logic.JsonForm()
    if request.method == "POST":
        if not perms.edit:
            # direct request or user lost edit access between fetching page and submitting form
            abort(403)
        if not form.validate():
            # client response must specify payload
            abort(500)

        data = form.payload.data
        diffs = data["diffs"]
        send_notifications = data["notify"]
        entries = logic.schedule_for(device, date, end_date)

        xs, srs, when, errors = logic.verify_scheduler_diffs(
            diffs,
            entries,
            perms,
            support,
            cur_date,
            cur_hour,
            cur_minute,
            groups,
            members_of_groups,
            g.user,
        )
        if errors is not None:
            return jsonify({"errors": errors})

        # update models
        staged = logic.apply_scheduler_diffs(g.user, xs)
        srs_notes = logic.apply_scheduler_sr_diffs(g.user, srs)

        # prepare any notifications
        ens, sns = logic.prepare_notifications(
            send_notifications, when, diffs, srs_notes
        )
        notifications = logic.fmt_notifications(ens, sns)

        # apply the changes then send notifications once they're committed
        for s in staged:
            model.db.session.add(s)
        model.db.session.commit()
        notification_results = logic.send_scheduler_notifications(device, notifications)

        return jsonify({"saved": len(staged), "notifications": notification_results})

    return {
        "device": device,
        "perms": perms,
        "perms_json": perms_json,
        "start_date": fmt_start_date,
        "end_date": fmt_end_date,
        "days": days,
        "top_row": top_row,
        "min": fmt_min,
        "max": fmt_max,
        "never_entries": never_entries,
        "no_entries": no_entries,
        "support": support,
        "members_of_groups": members_of_groups,
        "groups": groups,
        "groups_json": groups_json,
        "device_groups_json": device_groups_json,
        "off_hours": list(off_hours),
        "off_hour_map": off_hour_map,
        "colors": colors,
        "hours": hours,
        "schedule_load_json": {
            "endpoint": url_for("device_schedule_rows", the_device=device.id),
            "start": fmt_start_date,
            "days": days,
        },
        "cur_date": cur_date,
        "cur_hour": cur_hour,
        "form": form,
        **device_breadcrumb(device),
        **device_subpage_nav(device, perms),
    }


@app.route("/json/v1/device/<the_device>/schedule-rows")
@login_required
def device_schedule_rows(the_device):
    device = logic.get_device(the_device)
    if device is None:
        abort(404)

    perms = logic.get_dev_perms(g.user, device)
    if not (device.active or perms.admin):
        abort(403)

    date, days, end_date = schedule_window_from_request()

    hour_arg = request.args.get("hours", "")
    parsed_hours = []
    for h in hour_arg.split(","):
        if h == "":
            continue
        if not re.fullmatch(r"\d{1,2}", h):
            abort(400, f"invalid hour value: {h}")
        n = int(h)
        if n < 0 or n > 23:
            abort(400, f"invalid hour value: {h}")
        parsed_hours.append(n)

    hours = sorted(set(parsed_hours))
    if len(hours) == 0:
        abort(400, "hours query parameter is required")
    if len(hours) > 12:
        abort(400, "hours query parameter may include at most 12 rows per request")

    support = logic.SupportRequestDatalists([], [], [])
    if device.active and perms.edit:
        support = logic.support_request_datalists(device)

    entries = logic.schedule_for_hours(device, date, end_date, hours)
    by_slot = {(e.hour, e.date): e for e in entries}
    days_seq = [date + timedelta(days=n) for n in range(days)]

    cur_date, cur_hour, _ = logic.db_now()

    rows = []
    for hour in hours:
        row_cells = []
        for day in days_seq:
            entry = by_slot.get((hour, day))
            if entry is None:
                row_cells.append("")
                continue
            row_cells.append(
                render_template(
                    "partials/schedule_entry_cell.html",
                    x=entry,
                    support=support,
                    cur_date=cur_date,
                    cur_hour=cur_hour,
                )
            )
        rows.append({"hour": hour, "cells": row_cells})

    return jsonify({"rows": rows})


@app.route("/json/v1/log/<id>")
@login_required
def entry_log(id):
    eid, _, templateid = id.partition("-")
    device = logic.get_device_from_schedid(eid)
    if device is None:
        abort(404)

    perms = logic.get_dev_perms(g.user, device)
    if not (device.active or perms.admin):
        abort(403)

    entries = logic.get_sched_log_entry(eid)

    template = None
    templateObject = logic.get_template_from_templateid(templateid)
    if templateObject is not None:
        template = {
            "id": templateObject.id,
            "label": templateObject.label,
            "hidden": templateObject.hidden,
        }

    return jsonify({"template": template, "entries": entries})


@app.route("/device/<the_device>/edit", methods=["GET", "POST"])
@active_user_required
@render_to("device_edit")
def device_edit(the_device):
    _ = the_device
    abort(404)


def check_device_tmpl_perms(the_device):
    device = logic.get_device(the_device)
    if device is None:
        abort(404)

    perms = logic.get_dev_perms(g.user, device)
    can_edit = perms.admin or (perms.template and device.active)
    if not can_edit:
        abort(403)

    return device, perms


@app.route("/device/<the_device>/templates", methods=["GET", "POST"])
@active_user_required
@render_to("template_apply")
def device_tmpl(the_device):
    device, _ = check_device_tmpl_perms(the_device)

    templates = logic.templates_of_device(device, archived=False)
    codes = [t.id for t in templates]
    start = logic.get_start_day_of(device)
    chg_by = f"user {g.user.id}"
    warn = ""
    if start is None:
        start = logic.next_sunday()
        warn = f"no templates have been published to {device.label} before, so the start date will be {start}"
    no_templates = ""
    if len(templates) == 0:
        no_templates = f"no templates have been created for {device.label} yet"

    form = logic.TemplateApplyForm(codes)
    if form.validate_on_submit():
        errs = logic.validate_templates_before_application(device, form.templates.data)
        if len(errs) > 0:
            for err in errs:
                flash(err, category="error")
        else:
            logic.process_template_apply(form, device, start, chg_by)
            flash("templates applied")
            return to("device", the_device=device.id, start=start)

    return {
        "title": f"apply templates to {device.label}",
        "action": my_url(),
        "form": form,
        "warn": warn,
        "templates": templates,
        "no_templates": no_templates,
        "start": start,
        **template_breadcrumb(device),
        **template_subpage_nav(device),
    }


@app.route("/device/<the_device>/groups", methods=["GET", "POST"])
@active_user_required
@render_to("device_groups")
def device_groups(the_device):
    _ = the_device
    abort(404)


@app.route("/device/<the_device>/groups/add", methods=["GET", "POST"])
@active_user_required
@render_to("device_groups_add")
def device_groups_add(the_device):
    _ = the_device
    abort(404)


@app.route("/device/<the_device>/users")
@active_user_required
@render_to("device_users")
def device_users(the_device):
    _ = the_device
    abort(404)


@app.route("/device/<the_device>/users/<the_user>", methods=["GET", "POST"])
@active_user_required
@render_to("device_user")
def device_user(the_device, the_user):
    _ = (the_device, the_user)
    abort(404)


def template_breadcrumb(
    device: model.Device, tmpl: Optional[model.Template] = None
) -> Breadcrumb_links:
    out = [
        ("devices", url_for("devices")),
        (device.label, url_for("device", the_device=device.id)),
        ("templates", url_for("device_tmpl", the_device=device.id)),
    ]
    if tmpl is not None:
        out.append(
            (
                f"edit {tmpl.label}",
                url_for(
                    "device_tmpl_schedule_edit",
                    the_device=device.id,
                    the_template=tmpl.id,
                ),
            )
        )
    return breadcrumb(*out)


def template_subpage_nav(device: model.Device) -> Subpage_links:
    def build_url(name: str) -> str:
        return url_for(f"device_tmpl{name}", the_device=device.id)

    return subpage_nav(
        "templates",
        [
            (True, "apply", build_url("")),
            (True, "active", build_url("_list")),
            (True, "inactive", build_url("_archive")),
            (True, "add template", build_url("_add")),
        ],
    )


@app.route("/device/<the_device>/templates/list")
@active_user_required
@render_to("templates_list")
def device_tmpl_list(the_device):
    device, _ = check_device_tmpl_perms(the_device)
    templates = logic.templates_of_device(device, archived=False)
    return {
        "title": f"templates of {device.label}",
        "device": device,
        "templates": templates,
        **template_breadcrumb(device),
        **template_subpage_nav(device),
    }


@app.route("/device/<the_device>/templates/archive")
@active_user_required
@render_to("templates_list")
def device_tmpl_archive(the_device):
    device, _ = check_device_tmpl_perms(the_device)
    templates = logic.templates_of_device(device, archived=True)
    return {
        "title": f"archived templates of {device.label}",
        "device": device,
        "templates": templates,
        **template_breadcrumb(device),
        **template_subpage_nav(device),
    }


@app.route("/device/<the_device>/templates/add", methods=["GET", "POST"])
@active_user_required
@render_to("templates_metadata_edit")
def device_tmpl_add(the_device):
    device, _ = check_device_tmpl_perms(the_device)

    templates = logic.all_templates_of_device(device)
    form = logic.TemplateMetadataForm(device, templates, create=True)
    if form.validate_on_submit():
        ok, id = logic.create_template(form, device)
        if ok:
            return to(
                "device_tmpl_schedule_edit",
                the_device=form.device.id,
                the_template=id,
            )

    return {
        "title": f"add template to {device.label}",
        "device": device,
        "form": form,
        "action": my_url(),
        "submit": "create",
        **template_breadcrumb(device),
        **template_subpage_nav(device),
    }


def template_single_subpage_nav(
    device: model.Device, tmpl: model.Template
) -> Subpage_links:
    def entry(label: str, url_suffix: str) -> tuple[bool, str, str]:
        return (
            True,
            label,
            url_for(
                f"device_tmpl_{url_suffix}_edit",
                the_device=device.id,
                the_template=tmpl.id,
            ),
        )

    return subpage_nav(
        "edit template",
        [
            entry("schedule", "schedule"),
            entry("metadata", "metadata"),
        ],
    )


@app.route(
    "/device/<the_device>/templates/edit/<the_template>", methods=["GET", "POST"]
)
@active_user_required
@render_to("templates")
def device_tmpl_schedule_edit(the_device, the_template):
    device, _ = check_device_tmpl_perms(the_device)
    tmpl = logic.get_template(device, the_template)
    if tmpl is None:
        abort(404)

    entries = logic.get_template_entries(device, tmpl)
    institutes = logic.get_institutes_datalist()
    members_of_groups = logic.all_member_datalists_by_group(device)
    groups = logic.all_groups_of_device(device)
    device_groups_json = [id for (id, _) in groups]
    grouped_entries = logic.group_template_entries(entries)
    colors = logic.all_group_colors()
    hours = logic.fmt_hours()

    form = logic.JsonForm()
    if request.method == "POST":
        if not form.validate():
            # client response must specify payload
            abort(500)
        diffs = form.payload.data["diffs"]

        staged, errors = logic.verify_and_prep_template_diffs(
            diffs, entries, institutes, groups, members_of_groups
        )
        if errors is not None:
            return jsonify({"errors": errors})

        for s in staged:
            model.db.session.add(s)
        model.db.session.commit()
        return jsonify({"saved": len(staged)})

    return {
        "title": f"edit template schedule {device.label}/{tmpl.label}",
        "entries": grouped_entries,
        "institutes": institutes,
        "groups": groups,
        "device_groups_json": device_groups_json,
        "members_of_groups": members_of_groups,
        "colors": colors,
        "hours": hours,
        "form": form,
        **template_breadcrumb(device, tmpl),
        **template_single_subpage_nav(device, tmpl),
    }


@app.route(
    "/device/<the_device>/templates/edit-metadata/<the_template>",
    methods=["GET", "POST"],
)
@active_user_required
@render_to("templates_metadata_edit")
def device_tmpl_metadata_edit(the_device, the_template):
    device, _ = check_device_tmpl_perms(the_device)
    tmpl = logic.get_template(device, the_template)
    if tmpl is None:
        abort(404)

    form = logic.TemplateMetadataForm(device, [], create=False, obj=tmpl)
    if form.validate_on_submit():
        if logic.process_update_template_metadata(form, tmpl):
            return to(
                "device_tmpl_schedule_edit",
                the_device=form.device.id,
                the_template=tmpl.id,
            )

    return {
        "title": f"edit template {device.label}/{tmpl.label}",
        "device": device,
        "template": tmpl,
        "form": form,
        "action": my_url(),
        "submit": "save",
        **template_breadcrumb(device, tmpl),
        **template_single_subpage_nav(device, tmpl),
    }
