import ipaddress
import json
import os
import re
from functools import wraps
from typing import Tuple

import click
from flask import Flask, abort, g, redirect, request, session
from flask.helpers import flash, url_for
from flask.templating import render_template
from flask_mail import Mail
from flask_session import Session

import views
from model import create_reset_token_for, db, get_user, get_user_from_token, upsert_user

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
        if len(cfg) != 5:
            raise Exception("config.json unexpected number of keys, must be 5")

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
            return render_template(template + ".html", **ctx)

        return decorated_function

    return decorator


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


def render_error_page(code: int, msg: str, show_login: bool = False) -> Tuple[str, int]:
    data = {
        "code": code,
        "msg": msg,
        "show_login": show_login,
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


@app.route("/force-login/<token>", methods=["GET"])
def force_login(token):
    user = get_user_from_token(token)
    if user is None:
        abort(400)
    session["user_name"] = user.id
    g.user = user
    return redirect("/")


def breadcrumb(routes):
    return {"breadcrumb": [("home", url_for("home"))] + routes}


@app.route("/", methods=["GET"])
@login_required
@render_to("index")
def home():
    return {
        **views.index(),
        **breadcrumb([]),
    }


@app.route("/mailing-lists", methods=["GET", "POST"])
@login_required
@render_to("mailing-lists")
def mailing_lists():
    form = views.get_mailing_list_form(name=g.user.label, addr=g.user.addr)
    if form.validate_on_submit():
        views.process_mailing_list_form_submissions(form)
        flash("your mailing list subscription status has been updated")
        return redirect(url_for("home"))
    return {
        "form": form,
        "action": url_for("mailing_lists"),
        **breadcrumb([("list action form", url_for("mailing_lists"))]),
    }
