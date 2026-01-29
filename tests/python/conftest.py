# tests/python/conftest.py
import os
from pathlib import Path
from urllib.parse import quote

import psycopg2
import pytest
from dotenv import load_dotenv
from flask import Flask
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Explicitly load .env from project root before importing scheduler
project_root = Path(__file__).parent.parent.parent
load_dotenv(project_root / '.env')

# Import scheduler config
from scheduler import model
from scheduler.config import app_config


def create_test_database():
    """Create test database if it doesn't exist"""
    # Use a separate test database, never the production database
    test_db = "fmrif_scheduler_test"

    # Get database connection parameters from environment
    # These are loaded from .env at module level via load_dotenv()
    pghost = os.getenv("PGHOST", "localhost")
    pgport = int(os.getenv("PGPORT", "5444"))  # Default if not in .env
    pguser = os.getenv("PGUSER", "postgres")
    pgpassword = os.getenv("PGPASSWORD", "password")

    try:
        # Connect to PostgreSQL to create test database
        conn = psycopg2.connect(
            host=pghost,
            port=pgport,
            user=pguser,
            password=pgpassword,
            database="postgres",
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()

        # Check if test database exists
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (test_db,))
        exists = cur.fetchone()

        if not exists:
            cur.execute(f"CREATE DATABASE {test_db}")

        cur.close()
        conn.close()
    except psycopg2.OperationalError as e:
        # If we can't connect to create the database, tests will fail at runtime
        # This is expected in CI environments without PostgreSQL
        print(f"Warning: Could not create test database: {e}")


@pytest.fixture
def app():
    # Create test database if it doesn't exist
    create_test_database()

    app = Flask(__name__)
    test_config = dict(app_config)

    # Always use a separate test database for all test environments
    test_db_name = "fmrif_scheduler_test"
    pghost = os.getenv("PGHOST", "localhost")
    pgport = int(os.getenv("PGPORT", "5444"))  # Matches .env file
    pguser = os.getenv("PGUSER", "postgres")
    pgpassword = os.getenv("PGPASSWORD", "password")

    # Build test database URI with proper URL encoding for special characters
    test_config["SQLALCHEMY_DATABASE_URI"] = (
        f"postgresql+psycopg2://{quote(pguser)}:{quote(pgpassword)}@"
        f"{pghost}:{pgport}/{test_db_name}"
    )

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
        # Create all tables needed for tests
        model.db.session.begin_nested()
        model.db.create_all()
        yield app
        # Rollback the transaction after test
        model.db.session.rollback()
        model.db.session.remove()
