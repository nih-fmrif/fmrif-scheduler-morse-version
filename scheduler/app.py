import os
import re
from functools import wraps
from typing import Tuple

from flask import Flask, abort, g, request, session
from flask.templating import render_template
from flask_session import Session

from model import User, db, upsert_user

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
    else:
        # we are an existing login, just fetch the user object
        g.user = User.query.get(user_name)
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
            abort(403)
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
    return render_error_page(403, "Access denied", show_login=show_login)


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
