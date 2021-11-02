from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_session import Session

import os

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

db = SQLAlchemy(app)
app.config["SESSION_SQL_ALCHEMY"] = db
Session(app)


@app.route("/")
def hello_world():
    return "hello world"
