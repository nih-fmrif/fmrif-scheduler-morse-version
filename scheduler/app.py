import os
from functools import wraps
from typing import Dict, Tuple, Union

from flask import Flask
from flask.templating import render_template
from flask_session import Session
from model import db, User

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


def render_error_page(code: int, msg: str, show_login: bool = False) -> Tuple[str, int]:
    data = {
        "code": code,
        "msg": msg,
        "show_login": show_login,
    }
    return render_template("error.html", **data), code


@app.errorhandler(403)
def access_denied(e):
    # TODO set show_login based on whether they're logged in
    show_login = False
    return render_error_page(403, "Access denied", show_login=show_login)


@app.errorhandler(404)
def not_found(e):
    return render_error_page(404, "Not found")


@app.route("/")
@render_to("page")
def hello_world():
    return {"content": "hello world"}
