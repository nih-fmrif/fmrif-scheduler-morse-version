# tests/python/conftest.py
import os

import psycopg2
import pytest
from flask import Flask
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

from scheduler import model
from scheduler.config import app_config


def create_test_database():
    """Create test database if it doesn't exist"""
    test_db = os.getenv("PGDATABASE", "scheduler_test")
    conn = psycopg2.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5444"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", "password"),
        database="postgres",
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()

    # Check if database exists
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (test_db,))
    exists = cur.fetchone()

    if not exists:
        cur.execute(f"CREATE DATABASE {test_db}")

    cur.close()
    conn.close()


@pytest.fixture
def app():
    # Create test database if it doesn't exist
    create_test_database()

    app = Flask(__name__)
    test_config = dict(app_config)

    # Support both Docker and standalone testing
    # If PGHOST is set, use it directly (standalone mode)
    # Otherwise use the default Docker setup
    if os.getenv("PGHOST"):
        # Use environment variables for database connection
        test_config["SQLALCHEMY_DATABASE_URI"] = (
            f"postgresql+psycopg2://{os.getenv('PGUSER', 'postgres')}:"
            f"{os.getenv('PGPASSWORD', 'password')}@"
            f"{os.getenv('PGHOST')}:{os.getenv('PGPORT', '5444')}/"
            f"{os.getenv('PGDATABASE', 'scheduler_test')}"
        )
    else:
        # Default Docker setup
        test_config["SQLALCHEMY_DATABASE_URI"] = test_config[
            "SQLALCHEMY_DATABASE_URI"
        ].replace("postgres:5432", "localhost:5444")
        # Update password in Docker setup as well
        test_config["SQLALCHEMY_DATABASE_URI"] = test_config[
            "SQLALCHEMY_DATABASE_URI"
        ].replace(":postgres@", ":password@")
        # Update database name in Docker setup
        test_config["SQLALCHEMY_DATABASE_URI"] = test_config[
            "SQLALCHEMY_DATABASE_URI"
        ].replace("/scheduler", "/scheduler_test")

    test_config["SERVER_NAME"] = "localhost.localdomain:5051"
    app.config.update(**test_config)
    model.db.init_app(app)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def runner(app):
    return app.test_cli_runner()


@pytest.fixture
def app_context(app):
    with app.app_context():
        # Start a transaction
        model.db.session.begin_nested()
        model.db.create_all()
        yield app
        # Rollback the transaction after test
        model.db.session.rollback()
        model.db.session.remove()
