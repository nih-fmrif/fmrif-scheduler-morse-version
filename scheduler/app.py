import ipaddress
import json
import os
import re
from functools import wraps
from typing import Dict, List, Tuple, Union

import click
from flask import Flask, abort, g, redirect, request, session
from flask.helpers import flash, url_for
from flask.templating import render_template
from flask_mail import Mail
from flask_session import Session
from itsdangerous.url_safe import URLSafeSerializer

import logic
from model import create_reset_token_for, db, get_user, get_user_from_token, upsert_user

## Configuration

app = Flask(__name__)


def env(s: str) -> str:
    return os.environ[s]


def env_or(s: str, default: str) -> str:
    return os.environ.get(s, default)


def bool_env(s: str) -> bool:
    return env_or(s, "").lower() not in ("", "false")


app.config.update(
    SERVER_NAME=env("MMSCHED_SERVER_NAME"),
    # config for Flask-Mail
    MAIL_SERVER=env_or("MMSCHED_MAIL_SERVER", "localhost"),
    MAIL_PORT=int(env_or("MMSCHED_MAIL_PORT", "25")),
    MAIL_USE_TLS=bool_env("MMSCHED_MAIL_USE_TLS"),
    MAIL_USE_SSL=bool_env("MMSCHED_MAIL_USE_SSL"),
    MAIL_USERNAME=env("MMSCHED_MAIL_USERNAME"),
    MAIL_PASSWORD=env("MMSCHED_MAIL_PASSWORD"),
    # config for Flask-SQLAlchemy
    SQLALCHEMY_DATABASE_URI=env("MMSCHED_DB_URL"),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    # config for Flask-Session
    SESSION_COOKIE_NAME="dsid",
    PERMANENT_SESSION_LIFETIME=8 * 60 * 60,  # 8 hours in seconds
    SESSION_TYPE="sqlalchemy",
    SESSION_USE_SIGNER=True,
    SESSION_SQLALCHEMY_TABLE="site_sessions",
)


def do_url_fix():
    root = env_or("MMSCHED_APPLICATION_ROOT", "")
    if root != "":
        app.config["APPLICATION_ROOT"] = root


do_url_fix()


if app.debug:
    app.config.update(
        SQLALCHEMY_ECHO=True,
        MAIL_SUPPRESS_SEND=True,
    )
else:
    app.config.update(
        SESSION_COOKIE_SECURE=True,  # no https on dev server
        PREFERRED_URL_SCHEME="https",
    )


def do_proxy_fix():
    # load info about proxies so we can get correct remote addr
    # see: https://werkzeug.palletsprojects.com/en/2.0.x/middleware/proxy_fix/

    total, count = 0, {
        "For": 0,
        "Proto": 0,
        "Host": 0,
        "Port": 0,
        "Prefix": 0,
    }

    for ev in count.keys():
        nm = f"MMSCHED_X_FORWARDED_{ev.upper()}"
        n = int(os.environ.get(nm, 0))
        if n < 0:
            raise Exception(f"{nm} must be nonnegative integer")
        total += n
        count[ev] = n

    if total > 0:
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=count["For"],
            x_proto=count["Proto"],
            x_host=count["Host"],
            x_port=count["Port"],
            x_prefix=count["Prefix"],
        )


do_proxy_fix()


def load_user_settings(app):
    # we let any error here crash the app as these all must be set
    out = {}
    with app.open_resource("config.json", "r") as f:
        cfg = json.loads(f.read())
        if not isinstance(cfg, dict):
            raise Exception("config.json needs to be {}")
        if len(cfg) != 6:
            raise Exception("config.json unexpected number of keys, must be 6")

        key = cfg["secret_key"]
        if not isinstance(key, str):
            raise Exception("config.json: secret_key must be string")
        if key == "":
            raise Exception("config.json: secret key must not be empty")
        out["SECRET_KEY"] = key

        # get NIH subnets for checking that remote addr is in the network
        netspec = cfg["nih_networks"]
        if not isinstance(netspec, list):
            raise Exception("config.json: nih_networks needs to be []")
        if len(netspec) == 0:
            raise Exception("config.json: nih_network cannot be empty")
        out["nih_networks"] = [ipaddress.ip_network(sn) for sn in netspec]
        if app.debug:  # allow localhost in debug mode
            out["nih_networks"].append(ipaddress.ip_network("127.0.0.1"))

        login_prefix = cfg["siteminder_login_url_prefix"]
        if not isinstance(login_prefix, str):
            raise Exception("config.json: siteminder_login_url_prefix must be string")
        out["SM_LOGIN_URL_PREFIX"] = login_prefix

        sender = cfg["site_default_sender"]
        if not isinstance(sender, str):
            raise Exception("config.json: site_default_sender must be string")
        if "@" not in sender:
            raise Exception(
                "config.json: site_default_sender must be valid email address"
            )
        out["MAIL_DEFAULT_SENDER"] = sender

        ls_addr = cfg["listserv"]
        if not isinstance(ls_addr, str):
            raise Exception("config.json: listserv must be string")
        if "@" not in ls_addr:
            raise Exception("config.json: listserv must be valid email address")
        out["nih_listserv"] = ls_addr

        ml = cfg["mailing_lists"]
        if not isinstance(ml, dict):
            raise Exception("config.js: mailing_lists must be {}")
        for v in ml.values():
            if not isinstance(v, str):
                raise Exception(
                    'config.js: mailing_list entries must be "name": "description" pairs'
                )
        out["nih_mailing_lists"] = ml

    return out


app.config.update(**load_user_settings(app))

db.init_app(app)
app.config["SESSION_SQL_ALCHEMY"] = db
Session(app)
mail = Mail(app)
app.config["SESSION_MAILER"] = mail
signer = URLSafeSerializer(app.config["SECRET_KEY"], salt="nih-scheduler")
app.config["URL_SIGNER"] = signer

## Authentication


@app.before_request
def setup_user():
    # user already loaded
    if "user" in g:
        return

    # add a null user so we can exit early and ensure something is always set
    g.user = None

    # we don't need to bother to do anything special for static assets
    if request.endpoint == "static":
        return

    # the logged in user to this site or ""
    user_name = session.get("user_name", "")
    # the logged in user to AD or ""
    sm_user_name = request.headers.get("HTTP_SM_USER", "")

    if sm_user_name == "" and user_name == "":
        # there is no user to load
        return

    # the user to login as, if needed
    login_as = ""

    if sm_user_name != "" and user_name != "":
        # if the SM user name is different than the user we have on file,
        # we log out the old user and log the new one in;
        # otherwise we're still logged in
        if user_name != sm_user_name:
            login_as = sm_user_name
    elif sm_user_name != "" and user_name == "":
        # we're not logged into the site but we are logged into AD
        # so login to the site
        login_as = sm_user_name
    elif sm_user_name == "" and user_name != "":
        # we're logged into the site but AD credentials have gone away.
        # we want to stay logged in, so there's nothing to do here
        # except to continue and load user_name
        pass

    if login_as != "":
        mail = request.headers.get("HTTP_USER_EMAIL", "")
        name = request.headers.get("HTTP_NIH_DISPLAYNAME", "")
        # display name has some cruft after the name part, trim off
        name = re.sub(" [([].*$", "", name)
        session["user_name"] = login_as
        g.user = upsert_user(login_as, mail, name)
        db.session.commit()  # ensure these changes even if the rest of the request fails
        app.logger.info("new login for user: %s", login_as)
    else:
        # we are an existing login, just fetch the user object
        g.user = get_user(user_name)
        # it's possible that this can fail if the user record
        # gets deleted while the session is ongoing but then
        # this would return None so it would be the same as being
        # logged out, still avoid inconsistent state by
        # cleaning up the session.
        if g.user is None:
            del session["user_name"]


def login_required(f):
    @wraps(f)
    def protect(*args, **kwargs):
        if g.user is None:
            abort(403, "Access denied: AD login required")
        return f(*args, **kwargs)

    return protect


def in_network_required(f):
    @wraps(f)
    def protect(*args, **kwargs):
        ip = ipaddress.ip_address(request.access_route[-1])
        if not any(ip in addr for addr in app.config["nih_networks"]):
            abort(403, "Access denied: this page is limited to the NIH network")
        return f(*args, **kwargs)

    return protect


## Error handlers


def render_error_page(code: int, msg: str, show_login: bool = False) -> Tuple[str, int]:
    data = {
        "code": code,
        "msg": msg,
        "show_login": show_login,
        "login_url_prefix": app.config["SM_LOGIN_URL_PREFIX"],
    }
    return render_template("error.html", **data), code


@app.errorhandler(403)
def access_denied(e):
    # show login if no user object loaded
    show_login = g.user is None
    return render_error_page(403, e.description, show_login=show_login)


@app.errorhandler(404)
def not_found(e):
    return render_error_page(404, "Not found")


## CLI commands


@app.cli.command("force-login")
@click.argument("user")
def force_login_cli(user):
    """Create a login link for USER"""
    u = get_user(user)
    if u is None:
        click.echo(f"no such user {user}")
        return
    token = create_reset_token_for(user)
    click.echo(url_for("force_login", token=token))


@app.cli.command("deactivate-user")
@click.argument("user")
def deactivate_user(user):
    """mark USER as no longer active"""
    u = get_user(user)
    if u is None:
        click.echo(f"no such user {user}")
        return
    u.active = False
    db.session.add(u)
    db.session.commit()
    click.echo(f"{user} is now inactive")


@app.cli.command("activate-user")
@click.argument("user")
def activate_user(user):
    """mark USER as active"""
    u = get_user(user)
    if u is None:
        click.echo(f"no such user {user}")
        return
    u.active = True
    db.session.add(u)
    db.session.commit()
    click.echo(f"{user} is now active")


## Route helpers


def my_url() -> str:
    route = request.endpoint
    if not isinstance(route, str):
        abort(500)
    kwargs = request.view_args or {}
    return url_for(route, **kwargs)


def breadcrumb(
    *routes: Union[str, Tuple[str, str]]
) -> Dict[str, List[Tuple[str, str]]]:
    trail = [("home", url_for("home"))]
    if len(routes) > 0:
        routes, last = routes[:-1], routes[-1]
        for r in routes:
            assert not isinstance(r, str)
            trail.append(r)
        assert isinstance(last, str)
        trail.append((last, my_url()))
    return {"breadcrumb": trail}


def sr_only_tag(s: str) -> str:
    """replace " [" with "<sr-only>" and "]" with "</sr-only>",
    allowing more compact representation of common pattern."""
    return s.replace(" [", "<sr-only> ").replace("]", "</sr-only>")


def subpage_nav(
    title: str, links: List[Tuple[bool, str, str]]
) -> Dict[str, Dict[str, Union[str, List[Tuple[str, str]]]]]:
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


@app.route("/force-login/<token>", methods=["GET"])
def force_login(token):
    user = get_user_from_token(token)
    if user is None:
        abort(400)
    session["user_name"] = user.id
    g.user = user
    return redirect("/")


@app.route("/", methods=["GET"])
@login_required
@render_to("index")
def home():
    routes = []
    routes.append(("devices", url_for("devices")))

    memberships = logic.get_memberships(g.user)
    if len(memberships) > 0:
        routes.append(("groups", url_for("groups")))

    routes.append(("join form", url_for("join_form")))
    routes.append(("list action form", url_for("mailing_lists")))

    return {
        "routes": routes,
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
        return redirect(url_for("home"))
    return {
        "form": form,
        "action": url_for("mailing_lists"),
        **breadcrumb("list action form"),
    }


@app.route("/join", methods=["GET", "POST"])
@login_required
@in_network_required
@render_to("join")
def join_form():
    if not g.user.active:
        abort(
            403,
            "Your account is inactive: you must be re-authorized by a site admin before you may use the join form",
        )
    is_dev = "DEV" in logic.get_memberships(g.user)
    departments = logic.get_departments_for_join_form(db, g.user)
    form = logic.JoinForm(departments)
    no_departments = False
    if len(departments) == 0:
        no_departments = True
    if form.validate_on_submit():
        # TODO process request
        flash("your membership request is being processed")
        return redirect(url_for("home"))
    return {
        "form": form,
        "action": my_url(),
        "no_departments": no_departments,
        **subpage_nav(
            "Show [which form]",
            [
                (True, "join form", url_for("join_form")),
                (is_dev, "technologist join form", url_for("join_form_tech")),
            ],
        ),
        **breadcrumb("join form"),
    }


@app.route("/join/tech", methods=["GET", "POST"])
@login_required
@in_network_required
@render_to("join_tech")
def join_form_tech():
    if not g.user.active:
        abort(
            403,
            "Your account is inactive: you must be re-authorized by a site admin before you may use the join form",
        )
    if "DEV" not in logic.get_memberships(g.user):
        abort(403, "Only DEV members may access this form")
    # TODO form
    return {**breadcrumb(("join form", url_for("join_form")), "technologist join form")}


@app.route("/devices", methods=["GET"])
@app.route("/devices/inactive", endpoint="devices-inactive", methods=["GET"])
@login_required
@render_to("devices")
def devices():
    title = "devices"
    is_admin = logic.is_admin(g.user)
    active = request.endpoint == "devices"
    if not active:
        if not is_admin:
            abort(403, "access denied")
        title += " (inactive)"
    devices = logic.get_devices(active)
    return {
        "title": title,
        "devices": devices,
        **subpage_nav(
            "Show [which devices]",
            [
                (True, "active [devices]", url_for("devices")),
                (
                    is_admin,
                    "inactive [devices]",
                    url_for("devices-inactive"),
                ),
            ],
        ),
        **breadcrumb(title),
    }


@app.route("/groups", methods=["GET"])
@app.route("/groups/inactive", endpoint="groups-inactive", methods=["GET"])
@login_required
@render_to("groups")
def groups():
    title = "groups"
    memberships = logic.get_memberships(g.user)
    is_admin = "admin" in memberships
    active = request.endpoint == "groups"
    if not active:
        if not is_admin:
            abort(403, "access denied")
        title += " (inactive)"

    groups = []
    if is_admin:
        # admin see all groups with members
        groups = logic.get_all_groups_with_members(active)
    else:
        # nonadmins only see groups they're in
        groups = logic.get_groups(memberships)

    return {
        "title": title,
        "groups": groups,
        **subpage_nav(
            "Show [which groups]",
            [
                (True, "active [groups]", url_for("groups")),
                (
                    is_admin,
                    "inactive [groups]",
                    url_for("groups-inactive"),
                ),
            ],
        ),
        **breadcrumb(title),
    }


@app.route("/device/<device>")
@login_required
@render_to("device")
def device(device):
    # TODO just need this placeholder route
    return {}


@app.route("/group/<group>")
@login_required
@render_to("group")
def group(group):
    # TODO just need this placeholder route
    return {}
