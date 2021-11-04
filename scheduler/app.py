import ipaddress
import json
import os
import re
from functools import wraps
from typing import Tuple

from flask import Flask, abort, g, request, session
from flask.templating import render_template
from flask_session import Session

from model import db, get_user, upsert_user

app = Flask(__name__)


def env(s: str) -> str:
    return os.environ[s]


app.config.update(
    SECRET_KEY=env("SECRET_KEY"),
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

if app.debug:
    app.config.update(
        SQLALCHEMY_ECHO=True,
    )
else:
    app.config.update(
        SESSION_COOKIE_SECURE=True,  # no https on dev server
    )


def load_user_settings(app):
    # we let any error here crash the app as these all must be set
    out = {}
    with app.open_resource("config.json", "r") as f:
        cfg = json.loads(f.read())
        if not isinstance(cfg, dict):
            raise Exception("config.json needs to be {}")
        if len(cfg) != 3:
            raise Exception("config.json unexpected number of keys, must be 3")

        # load info about proxies so we can get correct remote addr
        # see: https://werkzeug.palletsprojects.com/en/2.0.x/middleware/proxy_fix/
        proxy_info = cfg["num_proxies"]
        if not isinstance(proxy_info, dict):
            raise Exception("config.json: num_proxies must be {}")
        if len(proxy_info) != 5:
            raise Exception("config.json: num_proxies must contain 5 entries")
        # ensure all the correct keys exist
        for key in (
            "X-Forwarded-For",
            "X-Forwarded-Proto",
            "X-Forwarded-Host",
            "X-Forwarded-Port",
            "X-Forwarded-Prefix",
        ):
            proxy_info[key]
        proxy_info_parsed = {}
        total_proxies = 0
        for k, v in proxy_info.items():
            n = int(v)
            if n < 0:
                raise Exception("config.json: num_proxies entries must be nonnegative")
            total_proxies += n
            proxy_info_parsed[k] = n
        if total_proxies > 0:
            from werkzeug.middleware.proxy_fix import ProxyFix

            app.wsgi_app = ProxyFix(
                app.wsgi_app,
                x_for=proxy_info_parsed["X-Forwarded-For"],
                x_proto=proxy_info_parsed["X-Forwarded-Proto"],
                x_host=proxy_info_parsed["X-Forwarded-Host"],
                x_port=proxy_info_parsed["X-Forwarded-Port"],
                x_prefix=proxy_info_parsed["X-Forwarded-Prefix"],
            )

        # get NIH subnets for checking that remote addr is in the network
        netspec = cfg["nih_networks"]
        if not isinstance(netspec, list):
            raise Exception("config.json: nih_networks needs to be []")
        if len(netspec) == 0:
            raise Exception("config.json: nih_network cannot be empty")
        out["nih_networks"] = [ipaddress.ip_network(sn) for sn in netspec]

    return out


app.config.update(**load_user_settings(app))

db.init_app(app)
app.config["SESSION_SQL_ALCHEMY"] = db
Session(app)


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


@app.route("/")
@login_required
@render_to("page")
def hello_world():
    if g.user is not None:
        return {"content": "hello " + g.user.label}
    return {"content": "hello world"}
