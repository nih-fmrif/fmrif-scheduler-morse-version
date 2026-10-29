# tests/unit/conftest.py
import hashlib
import os
import subprocess
from pathlib import Path
from urllib.parse import quote

import psycopg2
import pytest
from dotenv import load_dotenv
from flask import Flask
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Explicitly load .env from project root before importing scheduler
project_root = Path(__file__).parent.parent.parent
load_dotenv(project_root / ".env")

# Safety guard: all unit/route tests must use the dedicated test database.
TEST_DB_NAME = "fmrif_scheduler_test"
TEST_DB_TEMPLATE_NAME = f"{TEST_DB_NAME}_template"
os.environ["PGDATABASE"] = TEST_DB_NAME
os.environ.setdefault("AUTH_TEST__ENABLED", "true")
os.environ.setdefault("AUTH_TEST__SHARED_SECRET", "unit-test-secret")

# Import scheduler config
from scheduler import model  # noqa: E402
from scheduler.config import app_config  # noqa: E402

_ROUTE_DB_BOOTSTRAPPED = False


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
            "Timed out bootstrapping route-test database via sql/000-init.sh\n"
            f"Timeout: {timeout_seconds}s\n"
            f"{output}"
        ) from exc

    if proc.returncode != 0:
        output = "\n".join(part for part in (proc.stdout, proc.stderr) if part).strip()
        raise RuntimeError(
            "Failed to bootstrap route-test database via sql/000-init.sh\n"
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


def _database_comment(conn: psycopg2.extensions.connection, db_name: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = %s",
            (db_name,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def _drop_database(conn: psycopg2.extensions.connection, db_name: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT datistemplate FROM pg_database WHERE datname = %s",
            (db_name,),
        )
        row = cur.fetchone()
        if row is None:
            return

        cur.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = %s
            AND pid <> pg_backend_pid()
            """,
            (db_name,),
        )
        if row[0]:
            cur.execute(
                sql.SQL("ALTER DATABASE {} WITH IS_TEMPLATE false").format(
                    sql.Identifier(db_name)
                )
            )
        cur.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(db_name)))


def _create_database_from_template(
    conn: psycopg2.extensions.connection, db_name: str, template_db: str
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(db_name), sql.Identifier(template_db)
            )
        )


def _mark_as_route_template(
    conn: psycopg2.extensions.connection, db_name: str, marker: str
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("ALTER DATABASE {} WITH IS_TEMPLATE true").format(
                sql.Identifier(db_name)
            )
        )
        cur.execute(
            sql.SQL("COMMENT ON DATABASE {} IS %s").format(sql.Identifier(db_name)),
            (marker,),
        )


def _seed_file_signatures(env: dict[str, str]) -> list[str]:
    sql_dir = project_root / "sql"
    seed_paths = [
        Path(env.get("SQL_SEED_DUMP_FILE", str(sql_dir / "003-import-data.sql"))),
        Path(env.get("SQL_USER_DEPT_CSV", str(sql_dir / "user-dept.sample.csv"))),
        Path(env.get("SQL_DEV_DEPT_CSV", str(sql_dir / "dev-dept.sample.csv"))),
        Path(env.get("SQL_DEVPERM_CSV", str(sql_dir / "devperm.sample.csv"))),
    ]

    signatures = []
    for path in seed_paths:
        stat = path.stat()
        signatures.append(f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}")
    return signatures


def _route_template_fingerprint(env: dict[str, str]) -> str:
    sql_dir = project_root / "sql"
    migration_signatures = []
    for path in sorted(sql_dir.glob("[0-9][0-9][0-9]-*.sql")):
        stat = path.stat()
        migration_signatures.append(
            f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"
        )

    init_script = sql_dir / "000-init.sh"
    init_stat = init_script.stat()
    payload = "\n".join(
        [
            f"{init_script.resolve()}:{init_stat.st_size}:{init_stat.st_mtime_ns}",
            *migration_signatures,
            *_seed_file_signatures(env),
            f"additive_layers:{env.get('SQL_ADDITIVE_LAYER_FILES', '')}",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _ensure_route_template_database(init_script: Path) -> str:
    template_db_name = os.getenv("ROUTE_DB_TEMPLATE_NAME", TEST_DB_TEMPLATE_NAME)
    if template_db_name == TEST_DB_NAME:
        raise RuntimeError(
            "ROUTE_DB_TEMPLATE_NAME must differ from fmrif_scheduler_test"
        )

    template_env = _build_bootstrap_env(template_db_name)
    template_marker = f"route-template:{_route_template_fingerprint(template_env)}"
    rebuild_requested = (
        os.getenv("ROUTE_DB_REBUILD_TEMPLATE", "false").strip().lower() == "true"
    )

    conn = _admin_connection()
    try:
        exists = _database_exists(conn, template_db_name)
        comment = _database_comment(conn, template_db_name) if exists else None
        if rebuild_requested or comment != template_marker:
            if exists:
                _drop_database(conn, template_db_name)
            _run_sql_bootstrap(init_script, template_env)
            _mark_as_route_template(conn, template_db_name, template_marker)
        else:
            _mark_as_route_template(conn, template_db_name, template_marker)
    finally:
        conn.close()

    return template_db_name


def _refresh_test_database_from_template(template_db_name: str) -> None:
    conn = _admin_connection()
    try:
        _drop_database(conn, TEST_DB_NAME)
        _create_database_from_template(conn, TEST_DB_NAME, template_db_name)
    finally:
        conn.close()


def _bootstrap_test_database_from_sql() -> None:
    """Initialize the route-test database from a canonical seeded template clone."""
    init_script = project_root / "sql" / "000-init.sh"
    if not init_script.exists():
        raise RuntimeError(f"Missing SQL bootstrap script: {init_script}")

    use_template = os.getenv("ROUTE_DB_USE_TEMPLATE", "true").strip().lower() != "false"
    if not use_template:
        _run_sql_bootstrap(init_script, _build_bootstrap_env(TEST_DB_NAME))
        return

    template_db_name = _ensure_route_template_database(init_script)
    _refresh_test_database_from_template(template_db_name)


@pytest.fixture(scope="session", autouse=True)
def route_db_bootstrap(request):
    """Ensure route tests run against SQL-bootstrap schema, not ORM create_all output."""
    global _ROUTE_DB_BOOTSTRAPPED
    has_route_tests = any(
        item.get_closest_marker("route") is not None for item in request.session.items
    )
    if not has_route_tests:
        return
    if _ROUTE_DB_BOOTSTRAPPED:
        return
    _bootstrap_test_database_from_sql()
    _ROUTE_DB_BOOTSTRAPPED = True


def create_test_database():
    """Create test database if it doesn't exist"""
    # Use a separate test database, never the production database
    test_db = TEST_DB_NAME

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
    test_db_name = TEST_DB_NAME
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
def app_context(app, request):
    with app.app_context():
        model.db.session.begin_nested()
        if request.node.get_closest_marker("route") is None:
            # Non-route unit tests can rely on ORM-created tables.
            model.db.create_all()
        yield app
        # Rollback the transaction after test
        model.db.session.rollback()
        model.db.session.remove()
