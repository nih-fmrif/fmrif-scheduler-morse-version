import hashlib
import os
import re
import secrets
import subprocess
import traceback
import uuid
from datetime import timedelta
from functools import wraps
from typing import Any, Dict, List, Optional, Tuple, Union

import click
from flask import (
    Flask,
    Response,
    abort,
    current_app,
    g,
    got_request_exception,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_session import Session
from itsdangerous.url_safe import URLSafeSerializer
from markupsafe import Markup, escape
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException

import scheduler.logic.app_error_events as app_error_logic
import scheduler.logic.core as logic
import scheduler.logic.csp_violation_events as csp_logic
from scheduler.auth.session import (
    authenticate_bearer_token,
    get_user_from_session,
    require_jwt,
)
from scheduler.auth.views import auth

from . import message, model
from .config import app_config, normalize_app_env, settings
from .logging import configure_app_logging, redact_string, redact_value
from .routes import core_routes as core_route_handlers
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


_SHARED_SESSION_INTERFACE = None
_APP_ERROR_REFERENCE_PREFIX = "APP-ERR"
_APP_ERROR_BODY_PREVIEW_CHARS = 4096
_APP_ERROR_HEADER_NAMES = ("Accept", "Content-Type", "Referer")
_CSP_REPORT_TEXT_LIMIT = 2048
_CSP_REPORTING_GROUP = "csp-endpoint"
_STATIC_ASSET_VERSION: Optional[str] = None

_cached_memberships = core_route_handlers._cached_memberships
_request_bool_cache = core_route_handlers._request_bool_cache
_cached_show_tech_join_form = core_route_handlers._cached_show_tech_join_form
_cached_is_admin = core_route_handlers._cached_is_admin
_home_device_permissions = core_route_handlers._home_device_permissions
_rbac_user_is_group_pi = core_route_handlers._rbac_user_is_group_pi
_rbac_user_can_access = core_route_handlers._rbac_user_can_access
inject_template_context = core_route_handlers.inject_template_context
robots = core_route_handlers.robots
home = core_route_handlers.home
mailing_lists = core_route_handlers.mailing_lists
join_form_subnav = core_route_handlers.join_form_subnav
join_form_breadcrumb = core_route_handlers.join_form_breadcrumb
join_form = core_route_handlers.join_form
join_form_tech = core_route_handlers.join_form_tech
handle_join_group = core_route_handlers.handle_join_group
register_core_routes = core_route_handlers.register_core_routes


def proxy_fix(app):
    counts = settings.get_proxy_count()
    if counts is not None:
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, **counts)


def _resolve_static_asset_version() -> str:
    global _STATIC_ASSET_VERSION
    if _STATIC_ASSET_VERSION is not None:
        return _STATIC_ASSET_VERSION

    for name in (
        "STATIC_ASSET_VERSION",
        "GIT_SHA",
        "SOURCE_VERSION",
        "GITHUB_SHA",
    ):
        value = str(os.environ.get(name, "") or "").strip()
        if value != "":
            _STATIC_ASSET_VERSION = value[:12]
            return _STATIC_ASSET_VERSION

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        _STATIC_ASSET_VERSION = completed.stdout.strip()
    except (FileNotFoundError, PermissionError, subprocess.SubprocessError):
        _STATIC_ASSET_VERSION = ""
    return _STATIC_ASSET_VERSION


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
    app.config["STATIC_ASSET_VERSION"] = _resolve_static_asset_version()

    if app_env == "development":
        os.environ.setdefault("FLASK_DEBUG", "1")
        os.environ.setdefault("FLASK_RUN_RELOAD", "1")
        app.config["DEBUG"] = True
        app.config["TEMPLATES_AUTO_RELOAD"] = True

    if not app.config.get("SESSION_COOKIE_PATH"):
        app.config["SESSION_COOKIE_PATH"] = "/"

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
    register_core_app_features(app)
    app.add_url_rule(
        "/csp-report", endpoint="csp_report", view_func=csp_report, methods=["POST"]
    )
    register_core_routes(
        app,
        active_user_required=active_user_required,
        login_required=login_required,
        render_to=render_to,
        my_url_fn=my_url,
        to_fn=to,
        breadcrumb_fn=breadcrumb,
        subpage_nav_fn=subpage_nav,
        audit_rbac_action_fn=audit_rbac_action,
    )

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

    @got_request_exception.connect_via(app)
    def _capture_request_exception(
        sender: Flask, exception: BaseException, **_extra: object
    ) -> None:
        _ = sender
        _capture_unhandled_app_exception(exception)

    return app


## Authentication


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


def _csp_policy_with_reporting(policy: str) -> str:
    normalized = (policy or "").strip()
    if normalized == "":
        return normalized
    if re.search(r"(?i)\breport-to\b", normalized):
        return normalized
    separator = "" if normalized.endswith(";") else ";"
    return f"{normalized}{separator} report-to {_CSP_REPORTING_GROUP}"


def _csp_report_entries(payload: Any) -> List[Tuple[str, Dict[str, Any]]]:
    if not isinstance(payload, list):
        return []

    entries: List[Tuple[str, Dict[str, Any]]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        report_type = str(item.get("type", "") or "").strip().lower()
        if report_type != "csp-violation":
            continue
        body = item.get("body")
        if isinstance(body, dict):
            entries.append((report_type, body))
    return entries


def _csp_report_text(
    report: Dict[str, Any], *keys: str, limit: int = _CSP_REPORT_TEXT_LIMIT
) -> str:
    for key in keys:
        value = report.get(key)
        if value is None:
            continue
        token = str(value).strip()
        if token != "":
            return token[:limit]
    return ""


def _csp_report_int(report: Dict[str, Any], *keys: str) -> Optional[int]:
    for key in keys:
        value = report.get(key)
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _csp_report_actor() -> str:
    user = getattr(g, "user", None)
    if user is None:
        return "anonymous"
    user_id = str(getattr(user, "id", "") or "").strip()
    return user_id or "anonymous"


def csp_report():
    if not csp_logic.csp_violation_event_table_available():
        return ("", 204)

    payload = request.get_json(silent=True, force=True)
    entries = _csp_report_entries(payload)
    if not entries:
        return ("", 204)

    actor = _csp_report_actor()
    ip_addr = _request_client_ip()
    user_agent = request.headers.get("User-Agent", "")

    try:
        for report_type, report in entries:
            sanitized_report = redact_value(report)
            if not isinstance(sanitized_report, dict):
                continue
            csp_logic.record_csp_violation_event(
                report_type=report_type,
                actor=actor,
                ip_addr=ip_addr,
                user_agent=user_agent,
                document_uri=_csp_report_text(
                    sanitized_report, "document-uri", "documentURL"
                ),
                referrer=_csp_report_text(sanitized_report, "referrer"),
                blocked_uri=_csp_report_text(
                    sanitized_report, "blocked-uri", "blockedURL"
                ),
                violated_directive=_csp_report_text(
                    sanitized_report,
                    "violated-directive",
                    "violatedDirective",
                ),
                effective_directive=_csp_report_text(
                    sanitized_report,
                    "effective-directive",
                    "effectiveDirective",
                ),
                original_policy=_csp_report_text(
                    sanitized_report,
                    "original-policy",
                    "originalPolicy",
                    limit=8192,
                ),
                source_file=_csp_report_text(
                    sanitized_report, "source-file", "sourceFile"
                ),
                line_number=_csp_report_int(
                    sanitized_report, "line-number", "lineNumber"
                ),
                column_number=_csp_report_int(
                    sanitized_report, "column-number", "columnNumber"
                ),
                disposition=_csp_report_text(sanitized_report, "disposition"),
                status_code=_csp_report_int(
                    sanitized_report, "status-code", "statusCode"
                ),
                script_sample=_csp_report_text(
                    sanitized_report, "script-sample", "sample", limit=512
                ),
                report_body=sanitized_report,
            )
    except SQLAlchemyError:
        model.db.session.rollback()
        current_app.logger.exception("Failed to persist CSP violation report")
    except Exception:
        current_app.logger.exception("Failed to process CSP violation report")

    return ("", 204)


def apply_security_headers(response: Response):
    """Apply baseline security headers without changing page behavior."""
    response.headers["X-Content-Type-Options"] = settings.security.content_type_options
    response.headers["X-Frame-Options"] = settings.security.frame_options
    response.headers["Referrer-Policy"] = settings.security.referrer_policy

    if settings.security.enable_csp:
        policy = _csp_policy_with_reporting(settings.security.csp_policy)
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
        response.headers["Reporting-Endpoints"] = (
            f'{_CSP_REPORTING_GROUP}="{url_for("csp_report")}"'
        )

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


def _css_token_filter(value: str) -> str:
    return css_token(value)


# Keep nonce access import-mode agnostic: macros imported without context
# can still read the request-scoped CSP nonce through this helper.
def _current_csp_nonce_global() -> str:
    return current_csp_nonce()


def _static_asset_url_global(filename: str) -> str:
    params: Dict[str, str] = {"filename": filename}
    version = str(current_app.config.get("STATIC_ASSET_VERSION", "") or "").strip()
    if version != "":
        params["v"] = version
    return url_for("static", **params)


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


def _request_prefers_json() -> bool:
    if request.path.startswith("/json/"):
        return True
    accept = request.accept_mimetypes
    if not accept:
        return False
    best = accept.best_match(["application/json", "text/html"])
    return (
        best == "application/json" and accept["application/json"] >= accept["text/html"]
    )


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


def _error_reference_id() -> str:
    return f"{_APP_ERROR_REFERENCE_PREFIX}-{uuid.uuid4().hex[:12].upper()}"


def _redacted_multidict(multi_dict) -> Dict[str, object]:
    redacted: Dict[str, object] = {}
    for key in multi_dict.keys():
        values = [str(value) for value in multi_dict.getlist(key)]
        payload: object = values[0] if len(values) == 1 else values
        masked = redact_value({str(key): payload})
        if len(values) == 1:
            redacted[str(key)] = masked[str(key)]
        else:
            redacted[str(key)] = masked[str(key)]
    return redacted


def _error_request_context_payload() -> Dict[str, object]:
    user = getattr(g, "user", None)
    payload: Dict[str, object] = {
        "actor": {
            "id": str(getattr(user, "id", "") or "").strip() or "anonymous",
            "active": bool(getattr(user, "active", False)),
        },
        "request": {
            "method": request.method,
            "path": request.path,
            "endpoint": request.endpoint or "",
            "view_args": redact_value(dict(request.view_args or {})),
            "query": _redacted_multidict(request.args),
            "form": _redacted_multidict(request.form),
            "headers": {
                key.lower().replace("-", "_"): redact_string(value.strip())
                for key in _APP_ERROR_HEADER_NAMES
                if (value := request.headers.get(key, ""))
            },
        },
    }

    try:
        json_body = request.get_json(silent=True)
    except Exception:
        json_body = None
    if json_body is not None:
        payload["request"]["json"] = redact_value(json_body)

    raw_body = ""
    try:
        raw_body = request.get_data(cache=True, as_text=True) or ""
    except Exception:
        raw_body = ""
    if raw_body != "":
        trimmed = raw_body[:_APP_ERROR_BODY_PREVIEW_CHARS]
        if len(raw_body) > _APP_ERROR_BODY_PREVIEW_CHARS:
            trimmed = f"{trimmed}..."
        payload["request"]["raw_body_preview"] = redact_string(trimmed)

    return payload


def _top_application_frame(exception: BaseException) -> str:
    frames = traceback.extract_tb(exception.__traceback__)
    if len(frames) == 0:
        return "unknown"

    for frame in reversed(frames):
        marker = f"{os.sep}scheduler{os.sep}"
        if marker in frame.filename:
            suffix = frame.filename.split(marker, 1)[1]
            return f"{suffix}:{frame.name}:{frame.lineno}"

    frame = frames[-1]
    return f"{os.path.basename(frame.filename)}:{frame.name}:{frame.lineno}"


def _app_error_fingerprint(exception: BaseException) -> str:
    raw = "|".join(
        [
            exception.__class__.__name__,
            str(request.endpoint or request.path or ""),
            _top_application_frame(exception),
        ]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"{exception.__class__.__name__}:{digest}"


def _capture_unhandled_app_exception(exception: BaseException) -> Optional[str]:
    if isinstance(exception, HTTPException):
        return None
    if getattr(g, "_app_error_captured", False):
        return getattr(g, "_app_error_reference_id", None)

    g._app_error_captured = True

    try:
        model.db.session.rollback()
    except Exception:
        pass

    if not app_error_logic.app_error_event_table_available():
        return None

    reference_id = _error_reference_id()
    stack_trace = redact_string(
        "".join(
            traceback.format_exception(
                type(exception), exception, exception.__traceback__
            )
        )
    )
    try:
        stored = app_error_logic.record_app_error_event(
            reference_id=reference_id,
            actor=str(getattr(getattr(g, "user", None), "id", "") or "anonymous"),
            ip_addr=_request_client_ip(),
            user_agent=redact_string(request.headers.get("User-Agent", "").strip()),
            method=request.method,
            where_path=request.path,
            endpoint=request.endpoint or "",
            status_code=500,
            exception_type=exception.__class__.__name__,
            exception_message=redact_string(
                str(exception) or "Unhandled application error"
            ),
            fingerprint=_app_error_fingerprint(exception),
            request_context=_error_request_context_payload(),
            stack_trace=stack_trace,
        )
    except SQLAlchemyError:
        current_app.logger.exception("Failed to persist app error event")
        return None

    if stored:
        g._app_error_reference_id = reference_id
        return reference_id
    return None


def render_error_page(
    code: int,
    title: str,
    detail: Optional[str] = None,
    show_login: bool = False,
    reference_id: str = "",
) -> Tuple[str, int]:
    data = {
        "code": code,
        "title": title,
        "detail": detail,
        "assurance": "The application administrators have been notified.",
        "show_login": show_login,
        "reference_id": reference_id,
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


def not_found(e):
    return render_error_page(
        404,
        "Page Not Found",
        "The page you requested could not be found.",
        show_login=g.user is None,
    )


def internal_server_error(e):
    _ = e
    reference_id = str(getattr(g, "_app_error_reference_id", "") or "")
    if _request_prefers_json():
        payload = {
            "error": "Internal Server Error",
            "message": "An unexpected error occurred.",
        }
        if reference_id != "":
            payload["reference_id"] = reference_id
        return jsonify(payload), 500

    detail = "An unexpected error occurred while processing your request."
    return render_error_page(
        500,
        "Internal Server Error",
        detail,
        reference_id=reference_id,
    )


## CLI commands


@click.command("deactivate-user")
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


@click.command("activate-user")
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


@click.command("add-admin")
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


def register_core_app_features(app: Flask) -> None:
    app.before_request(setup_user)
    app.context_processor(inject_template_context)
    app.after_request(apply_security_headers)
    app.add_template_filter(_css_token_filter, "css_token")
    app.add_template_global(_current_csp_nonce_global, "current_csp_nonce")
    app.add_template_global(_static_asset_url_global, "static_asset_url")
    app.register_error_handler(401, unauthorized)
    app.register_error_handler(403, access_denied)
    app.register_error_handler(404, not_found)
    app.register_error_handler(500, internal_server_error)
    app.cli.add_command(deactivate_user)
    app.cli.add_command(activate_user)
    app.cli.add_command(add_admin)
