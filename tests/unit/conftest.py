# tests/unit/conftest.py
import hashlib
import os
import subprocess
from pathlib import Path

import psycopg2
import pytest
from dotenv import load_dotenv
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Explicitly load .env from project root before importing scheduler
project_root = Path(__file__).parent.parent.parent
load_dotenv(project_root / ".env")


def _normalize_pg_identifier(raw: str) -> str:
    max_len = 63
    if len(raw) <= max_len:
        return raw

    suffix = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    prefix_len = max_len - 1 - len(suffix)
    if prefix_len < 1:
        return suffix[:max_len]
    return f"{raw[:prefix_len]}-{suffix}"


def _derive_test_db_name() -> str:
    base_name = os.getenv("SCHEDULER_TEST_DB_NAME", "fmrif_scheduler_test")
    worker_id = os.getenv("PYTEST_XDIST_WORKER")
    if not worker_id:
        return base_name

    # xdist workers each need their own bootstrap target DB.
    return _normalize_pg_identifier(f"{base_name}_{worker_id}")


# Safety guard: all unit/route tests must use a dedicated test database.
TEST_DB_NAME = _derive_test_db_name()
os.environ["SCHEDULER_TEST_DB_NAME"] = TEST_DB_NAME
os.environ["PGDATABASE"] = TEST_DB_NAME
os.environ.setdefault("AUTH_TEST__ENABLED", "true")
os.environ.setdefault("AUTH_TEST__SHARED_SECRET", "unit-test-secret")
os.environ.setdefault("APP_ENV", "development")

# Import scheduler config
from scheduler import model  # noqa: E402

_ISOLATION_FIXTURES = {
    "app",
    "app_context",
    "client",
    "runner",
    "route_app",
    "route_app_context",
    "route_client",
}


def _parse_positive_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value) if value is not None else default
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _build_bootstrap_env(target_database: str) -> dict[str, str]:
    env = os.environ.copy()
    env["PGDATABASE"] = target_database
    env["DROP_DB"] = "true"
    env.setdefault(
        "SQL_ADDITIVE_LAYER_FILES",
        str(project_root / "sql" / "900-import-new-data.sql"),
    )
    env.setdefault("PGHOST", "localhost")
    env.setdefault("PGPORT", "5444")
    env.setdefault("PGUSER", "postgres")
    env.setdefault("PGPASSWORD", "password")
    return env


def _run_sql_bootstrap(init_script: Path, env: dict[str, str]) -> None:
    timeout_seconds = _parse_positive_int(
        os.getenv("ROUTE_DB_BOOTSTRAP_TIMEOUT_SECONDS"), 900
    )
    try:
        proc = subprocess.run(
            ["bash", str(init_script)],
            cwd=project_root,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        output = "\n".join(
            part for part in ((exc.stdout or ""), (exc.stderr or "")) if part
        ).strip()
        raise RuntimeError(
            "Timed out bootstrapping test database via sql/000-init.sh\n"
            f"Timeout: {timeout_seconds}s\n"
            f"{output}"
        ) from exc

    if proc.returncode != 0:
        output = "\n".join(part for part in (proc.stdout, proc.stderr) if part).strip()
        raise RuntimeError(
            "Failed to bootstrap test database via sql/000-init.sh\n"
            f"Exit code: {proc.returncode}\n"
            f"{output}"
        )


def _admin_connection() -> psycopg2.extensions.connection:
    conn = psycopg2.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5444")),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", "password"),
        database="postgres",
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    conn.autocommit = True
    return conn


def _database_exists(conn: psycopg2.extensions.connection, db_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
        return cur.fetchone() is not None


def _drop_database(conn: psycopg2.extensions.connection, db_name: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = %s
            AND pid <> pg_backend_pid()
            """,
            (db_name,),
        )
        cur.execute(
            sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(db_name))
        )


def _reset_test_database() -> None:
    conn = _admin_connection()
    try:
        if _database_exists(conn, TEST_DB_NAME):
            _drop_database(conn, TEST_DB_NAME)
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB_NAME))
            )
    finally:
        conn.close()


def _create_app():
    from scheduler.app import create_app

    app = create_app()
    app_port = os.getenv("APP_PORT", "5051")
    app.config["SERVER_NAME"] = f"localhost.localdomain:{app_port}"
    return app


def _bootstrap_route_test_database() -> None:
    init_script = project_root / "sql" / "000-init.sh"
    if not init_script.exists():
        raise RuntimeError(f"Missing SQL bootstrap script: {init_script}")

    _run_sql_bootstrap(init_script, _build_bootstrap_env(TEST_DB_NAME))

    # Flask-Session creates its table lazily during app init. Prime that once
    # outside per-test transactions so route tests share a stable baseline.
    app = _create_app()
    with app.app_context():
        pass


def _bootstrap_unit_test_database() -> None:
    _reset_test_database()
    app = _create_app()
    with app.app_context():
        model.db.drop_all()
        model.db.create_all()


@pytest.fixture(scope="session", autouse=True)
def suite_db_bootstrap(request):
    has_route_tests = any(
        item.get_closest_marker("route") is not None for item in request.session.items
    )
    has_non_route_tests = any(
        item.get_closest_marker("route") is None for item in request.session.items
    )

    if has_route_tests and has_non_route_tests:
        raise RuntimeError(
            "Mixed route and non-route selections are not supported in one pytest "
            "session. Use pixi run test-unit or pixi run test-routes."
        )

    if has_route_tests:
        _bootstrap_route_test_database()
    elif has_non_route_tests:
        _bootstrap_unit_test_database()


@pytest.fixture(autouse=True)
def db_test_isolation(request):
    fixtureinfo = getattr(request.node, "_fixtureinfo", None)
    direct_fixtures = set(getattr(fixtureinfo, "argnames", ()))
    is_route_test = request.node.get_closest_marker("route") is not None
    uses_isolation_fixture = bool(_ISOLATION_FIXTURES & direct_fixtures)

    if not (is_route_test or uses_isolation_fixture):
        yield
        return

    app = request.getfixturevalue("app")
    app_ctx = app.app_context()
    app_ctx.push()

    connection = model.db.engine.connect()
    transaction = connection.begin()

    previous_default_engine = model.db.engines[None]

    # Rebind the existing Flask-SQLAlchemy scoped session with public
    # SQLAlchemy APIs rather than relying on Flask-SQLAlchemy's private
    # _make_scoped_session() helper.
    model.db.session.remove()
    model.db.session.configure(
        bind=connection,
        binds={},
        join_transaction_mode="create_savepoint",
    )
    model.db.engines[None] = connection

    try:
        yield
    finally:
        model.db.session.remove()
        model.db.engines[None] = previous_default_engine
        model.db.session.configure(
            bind=previous_default_engine,
            binds={},
            join_transaction_mode="conditional_savepoint",
        )
        transaction.rollback()
        connection.close()
        app_ctx.pop()


@pytest.fixture
def app():
    return _create_app()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def runner(app):
    return app.test_cli_runner()


@pytest.fixture
def route_app(app):
    return app


@pytest.fixture
def route_client(route_app):
    return route_app.test_client()


@pytest.fixture
def route_app_context(route_app):
    return route_app


@pytest.fixture
def app_context(app):
    return app
