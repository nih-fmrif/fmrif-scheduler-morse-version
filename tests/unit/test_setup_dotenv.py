from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP_DOTENV_ENV_KEYS_TO_CLEAR = (
    "APP_PORT",
    "AUTH_TEST__SHARED_SECRET",
    "COMPOSE_PROJECT_NAME",
    "FMRIF_RUNTIME_SCOPE",
    "MAILPIT__PORT",
    "MAILPIT__SMTP_PORT",
    "MAIL__DEFAULT_SENDER",
    "PGDATABASE",
    "PGHOST",
    "PGPASSWORD",
    "PGPORT",
    "PGUSER",
    "RUNTIME_SCOPE_DIR",
    "SCHEDULER_TEST_DB_NAME",
    "SECURITY__AUTH_RATE_LIMIT_MAX_REQUESTS",
    "SETUP_DOTENV_PROFILE",
    "SESSION__COOKIE_NAME",
    "SESSION__COOKIE_SECURE",
)


def _prepare_setup_dotenv_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    scripts_dir = workspace / "scripts"
    scripts_dir.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "setup-dotenv.sh", workspace / "setup-dotenv.sh")
    shutil.copy2(REPO_ROOT / ".env.sample.local", workspace / ".env.sample.local")
    shutil.copy2(
        REPO_ROOT / "scripts" / "runtime-scope.sh", scripts_dir / "runtime-scope.sh"
    )
    return workspace


def _build_setup_dotenv_env(runtime_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    for key in SETUP_DOTENV_ENV_KEYS_TO_CLEAR:
        env.pop(key, None)
    env["PATH"] = os.environ["PATH"]
    env["HOME"] = os.environ.get("HOME", str(runtime_dir))
    env["RUNTIME_SCOPE_DIR"] = str(runtime_dir)
    return env


def test_setup_dotenv_host_local_postgres_profile_uses_native_db_defaults(
    tmp_path: Path,
) -> None:
    workspace = _prepare_setup_dotenv_workspace(tmp_path)
    runtime_dir = tmp_path / "runtime"
    env = _build_setup_dotenv_env(runtime_dir)

    result = subprocess.run(
        ["bash", "setup-dotenv.sh", "--profile", "host-local-postgres"],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    env_text = (workspace / ".env").read_text(encoding="utf-8")
    assert "PGHOST=127.0.0.1" in env_text
    assert "PGPORT=5432" in env_text
    assert (
        "Generated .env from .env.sample.local for scope=default profile=host-local-postgres"
        in result.stdout
    )


def test_setup_dotenv_host_local_postgres_profile_preserves_explicit_pgport(
    tmp_path: Path,
) -> None:
    workspace = _prepare_setup_dotenv_workspace(tmp_path)
    runtime_dir = tmp_path / "runtime"
    env = _build_setup_dotenv_env(runtime_dir)
    env["PGPORT"] = "6543"

    result = subprocess.run(
        ["bash", "setup-dotenv.sh", "--profile", "host-local-postgres"],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    env_text = (workspace / ".env").read_text(encoding="utf-8")
    assert "PGPORT=6543" in env_text


def test_setup_dotenv_host_local_postgres_profile_resets_copied_managed_values(
    tmp_path: Path,
) -> None:
    workspace = _prepare_setup_dotenv_workspace(tmp_path)
    runtime_dir = tmp_path / "runtime"
    env = _build_setup_dotenv_env(runtime_dir)
    (workspace / ".env").write_text(
        "\n".join(
            [
                "APP_PORT=25357",
                "PGHOST=localhost",
                "PGPORT=61626",
                "COMPOSE_PROJECT_NAME=scheduler-stale",
                "PGDATABASE=fmrif_scheduler_stale",
                "SCHEDULER_TEST_DB_NAME=fmrif_scheduler_test_stale",
                "SESSION__COOKIE_NAME=dsid-stale",
                "MAIL__DEFAULT_SENDER=scheduler-stale@example.invalid",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "setup-dotenv.sh", "--profile", "host-local-postgres"],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    env_text = (workspace / ".env").read_text(encoding="utf-8")
    assert "PGHOST=127.0.0.1" in env_text
    assert "PGPORT=5432" in env_text
    assert "COMPOSE_PROJECT_NAME=scheduler" in env_text
    assert "PGDATABASE=fmrif_scheduler_default" in env_text
    assert "SCHEDULER_TEST_DB_NAME=fmrif_scheduler_test_default" in env_text
    assert "SESSION__COOKIE_NAME=dsid-default" in env_text
    assert "MAIL__DEFAULT_SENDER=scheduler-default@localhost.localdomain" in env_text
    assert "PGPORT=61626" not in env_text
    assert "PGDATABASE=fmrif_scheduler_stale" not in env_text


def test_setup_dotenv_rejects_unknown_profile(tmp_path: Path) -> None:
    workspace = _prepare_setup_dotenv_workspace(tmp_path)

    result = subprocess.run(
        ["bash", "setup-dotenv.sh", "--profile", "does-not-exist"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "unsupported setup-dotenv profile" in result.stderr
