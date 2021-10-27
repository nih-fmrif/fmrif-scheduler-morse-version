from flask import Flask
from flask_sqlalchemy import SQLAlchemy

import os

app = Flask(__name__)


def env(s: str) -> str:
    return os.environ[s]


app.config.update(
    SQLALCHEMY_DATABASE_URI=env("MMSCHED_DB_URL"),
)

if app.debug:
    app.config.update(
        SQLALCHEMY_ECHO=True,
    )

db = SQLAlchemy(app)


@app.route("/")
def hello_world():
    return "hello world"
