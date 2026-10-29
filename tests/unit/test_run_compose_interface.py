from __future__ import annotations

import os
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_COMPOSE = REPO_ROOT / "run-compose.sh"
INHERITED_RUNTIME_ENV_KEYS = (
    "APP_PORT",
    "AUTH_TEST__SHARED_SECRET",
    "COMPOSE_PROJECT_NAME",
    "FMRIF_RUNTIME_SCOPE",
    "FMRIF_RUNTIME_SCOPE_OFFSET",
    "INTEGRATION_APP_PORT",
    "MAILPIT__PORT",
    "MAILPIT__SMTP_PORT",
    "MAILPIT_INTEGRATION__PORT",
    "MAILPIT_INTEGRATION__SMTP_PORT",
    "MAILPIT_ROUTES__PORT",
    "MAILPIT_ROUTES__SMTP_PORT",
    "MAILPIT_UNIT__PORT",
    "MAILPIT_UNIT__SMTP_PORT",
    "PGDATABASE",
    "PGHOST",
    "PGPASSWORD",
    "PGPORT",
    "PGUSER",
    "RUNTIME_SCOPE_DIR",
    "SESSION__COOKIE_NAME",
)


def _write_fake_docker(tmp_path: Path) -> tuple[Path, Path]:
    docker_dir = tmp_path / "bin"
    docker_dir.mkdir()
    log_file = tmp_path / "docker.log"
    docker_script = docker_dir / "docker"
    docker_script.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail

            log_file="${FAKE_DOCKER_LOG:?}"
            running_projects=",${FAKE_RUNNING_PROJECTS:-},"
            resource_projects=",${FAKE_RESOURCE_PROJECTS:-${FAKE_RUNNING_PROJECTS:-}},"

            case "${1:-}" in
              ps)
                project_name=""
                running_only=0
                shift
                while [ "$#" -gt 0 ]; do
                  case "$1" in
                    --filter)
                      filter_value="${2:-}"
                      case "$filter_value" in
                        label=com.docker.compose.project=*)
                          project_name="${filter_value#label=com.docker.compose.project=}"
                          ;;
                        status=running)
                          running_only=1
                          ;;
                      esac
                      shift 2
                      ;;
                    *)
                      shift
                      ;;
                  esac
                done
                if [[ "$running_projects" == *",${project_name},"* ]]; then
                  printf 'fake-container-%s\\n' "$project_name"
                elif [ "$running_only" -eq 0 ] && [[ "$resource_projects" == *",${project_name},"* ]]; then
                  printf 'fake-resource-%s\\n' "$project_name"
                fi
                ;;
              volume)
                if [ "${2:-}" != "ls" ]; then
                  exit 0
                fi
                project_name=""
                shift 2
                while [ "$#" -gt 0 ]; do
                  case "$1" in
                    --filter)
                      filter_value="${2:-}"
                      case "$filter_value" in
                        label=com.docker.compose.project=*)
                          project_name="${filter_value#label=com.docker.compose.project=}"
                          ;;
                      esac
                      shift 2
                      ;;
                    *)
                      shift
                      ;;
                  esac
                done
                if [[ "$resource_projects" == *",${project_name},"* ]]; then
                  printf 'fake-volume-%s\\n' "$project_name"
                fi
                ;;
              network)
                if [ "${2:-}" != "ls" ]; then
                  exit 0
                fi
                project_name=""
                shift 2
                while [ "$#" -gt 0 ]; do
                  case "$1" in
                    --filter)
                      filter_value="${2:-}"
                      case "$filter_value" in
                        label=com.docker.compose.project=*)
                          project_name="${filter_value#label=com.docker.compose.project=}"
                          ;;
                      esac
                      shift 2
                      ;;
                    *)
                      shift
                      ;;
                  esac
                done
                if [[ "$resource_projects" == *",${project_name},"* ]]; then
                  printf 'fake-network-%s\\n' "$project_name"
                fi
                ;;
              compose)
                shift
                project_name=""
                while [ "$#" -gt 0 ]; do
                  case "$1" in
                    --project-name)
                      project_name="${2:-}"
                      shift 2
                      ;;
                    *)
                      shift
                      ;;
                  esac
                done
                printf 'compose-down:%s\\n' "$project_name" >>"$log_file"
                ;;
              *)
                echo "unexpected docker invocation: $*" >&2
                exit 1
                ;;
            esac
            """
        )
    )
    docker_script.chmod(0o755)
    return docker_dir, log_file


def _write_scope_file(
    runtime_dir: Path,
    scope_name: str,
    project_name: str | None,
    extra_lines: dict[str, str | int] | None = None,
) -> None:
    lines = [f"RUNTIME_SCOPE={scope_name}", f"WORKTREE_ROOT={REPO_ROOT}"]
    if project_name is not None:
        lines.append(f"COMPOSE_PROJECT_NAME={project_name}")
    if extra_lines:
        for key, value in extra_lines.items():
            lines.append(f"{key}={value}")
    (runtime_dir / scope_name).write_text("\n".join(lines) + "\n")


def _reserve_free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_tcp_listener(port: int, timeout_seconds: float = 5.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for listener on port {port}")


def _start_http_listener(port: int) -> subprocess.Popen[str]:
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port)],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        _wait_for_tcp_listener(port)
    except Exception:
        proc.terminate()
        proc.wait(timeout=5)
        raise
    return proc


def _run_compose(
    *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    for key in INHERITED_RUNTIME_ENV_KEYS:
        run_env.pop(key, None)
    if env:
        run_env.update(env)
    return subprocess.run(
        ["bash", str(RUN_COMPOSE), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=run_env,
    )


def test_help_describes_cleanup_modes() -> None:
    result = _run_compose("--help")

    assert result.returncode == 0
    assert "--clear" in result.stdout
    assert "--wipe" not in result.stdout
    assert "--clear-stale" in result.stdout
    assert "--clear-all" in result.stdout


def test_check_writes_resolved_scoped_project_to_metadata(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime-scopes"
    runtime_dir.mkdir()
    docker_dir, log_file = _write_fake_docker(tmp_path)
    env_file = tmp_path / "test.env"
    env_file.write_text(
        "\n".join(
            [
                "PGHOST=localhost",
                "PGPORT=35444",
                "APP_PORT=35051",
                "PGUSER=postgres",
                "PGPASSWORD=password",
                "PGDATABASE=fmrif_scheduler_icons",
                "MAIL__DEFAULT_SENDER=test@example.com",
                "COMPOSE_PROJECT_NAME=scheduler",
            ]
        )
        + "\n"
    )

    result = _run_compose(
        "--check",
        env={
            "ENVFILE": str(env_file),
            "RUNTIME_SCOPE_DIR": str(runtime_dir),
            "FMRIF_RUNTIME_SCOPE": "icons",
            "FAKE_DOCKER_LOG": str(log_file),
            "PATH": f"{docker_dir}{os.pathsep}{os.environ['PATH']}",
        },
    )

    assert result.returncode == 0
    metadata = (runtime_dir / "icons").read_text()
    compose_project_line = next(
        line
        for line in metadata.splitlines()
        if line.startswith("COMPOSE_PROJECT_NAME=")
    )
    assert compose_project_line.endswith("-icons")
    assert compose_project_line != "COMPOSE_PROJECT_NAME=scheduler"


def test_list_all_reports_running_stopped_and_untracked_scopes(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime-scopes"
    runtime_dir.mkdir()
    docker_dir, log_file = _write_fake_docker(tmp_path)
    _write_scope_file(runtime_dir, "running-scope", "proj-running-scope")
    _write_scope_file(runtime_dir, "stopped-scope", "proj-stopped-scope")
    _write_scope_file(runtime_dir, "metadata-only", None)

    result = _run_compose(
        "--list-all",
        env={
            "RUNTIME_SCOPE_DIR": str(runtime_dir),
            "FAKE_DOCKER_LOG": str(log_file),
            "FAKE_RUNNING_PROJECTS": "proj-running-scope",
            "PATH": f"{docker_dir}{os.pathsep}{os.environ['PATH']}",
        },
    )

    assert result.returncode == 0
    assert "Scope: running-scope" in result.stdout
    assert "stack_state: running" in result.stdout
    assert "Scope: stopped-scope" in result.stdout
    assert "stack_state: stopped" in result.stdout
    assert "Scope: metadata-only" in result.stdout
    assert "metadata_status: incomplete" in result.stdout
    assert "stack_state: untracked" in result.stdout
    assert (
        "Summary: 1 running, 1 stopped, 1 untracked, 0 invalid, 0 unknown."
        in result.stdout
    )


def test_list_all_reconciles_legacy_base_project_metadata(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime-scopes"
    runtime_dir.mkdir()
    docker_dir, log_file = _write_fake_docker(tmp_path)
    _write_scope_file(runtime_dir, "icons", "scheduler")

    result = _run_compose(
        "--list-all",
        env={
            "RUNTIME_SCOPE_DIR": str(runtime_dir),
            "FAKE_DOCKER_LOG": str(log_file),
            "FAKE_RUNNING_PROJECTS": "scheduler-icons",
            "PATH": f"{docker_dir}{os.pathsep}{os.environ['PATH']}",
        },
    )

    assert result.returncode == 0
    assert "Scope: icons" in result.stdout
    assert "compose_project: scheduler-icons" in result.stdout
    assert "metadata_compose_project: scheduler" in result.stdout
    assert "stack_state: running" in result.stdout
    assert (
        "Summary: 1 running, 0 stopped, 0 untracked, 0 invalid, 0 unknown."
        in result.stdout
    )


def test_clear_stale_keeps_running_scopes(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime-scopes"
    runtime_dir.mkdir()
    docker_dir, log_file = _write_fake_docker(tmp_path)
    _write_scope_file(runtime_dir, "running-scope", "proj-running-scope")
    _write_scope_file(runtime_dir, "stopped-scope", "proj-stopped-scope")
    _write_scope_file(runtime_dir, "metadata-only", None)

    result = _run_compose(
        "--clear-stale",
        env={
            "RUNTIME_SCOPE_DIR": str(runtime_dir),
            "FAKE_DOCKER_LOG": str(log_file),
            "FAKE_RUNNING_PROJECTS": "proj-running-scope",
            "PATH": f"{docker_dir}{os.pathsep}{os.environ['PATH']}",
        },
    )

    assert result.returncode == 0
    assert (runtime_dir / "running-scope").exists()
    assert not (runtime_dir / "stopped-scope").exists()
    assert not (runtime_dir / "metadata-only").exists()
    assert "Skipping running scope 'running-scope'" in result.stdout
    assert "Removing stale metadata for scope 'metadata-only'" in result.stdout
    assert log_file.read_text().splitlines() == ["compose-down:proj-stopped-scope"]


def test_clear_stale_uses_scoped_project_for_legacy_metadata(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime-scopes"
    runtime_dir.mkdir()
    docker_dir, log_file = _write_fake_docker(tmp_path)
    _write_scope_file(runtime_dir, "icons", "scheduler")

    result = _run_compose(
        "--clear-stale",
        env={
            "RUNTIME_SCOPE_DIR": str(runtime_dir),
            "FAKE_DOCKER_LOG": str(log_file),
            "PATH": f"{docker_dir}{os.pathsep}{os.environ['PATH']}",
        },
    )

    assert result.returncode == 0
    assert not (runtime_dir / "icons").exists()
    assert log_file.read_text().splitlines() == ["compose-down:scheduler-icons"]


def test_clear_all_removes_running_scopes_and_metadata(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime-scopes"
    runtime_dir.mkdir()
    docker_dir, log_file = _write_fake_docker(tmp_path)
    _write_scope_file(runtime_dir, "running-scope", "proj-running-scope")
    _write_scope_file(runtime_dir, "stopped-scope", "proj-stopped-scope")
    _write_scope_file(runtime_dir, "metadata-only", None)

    result = _run_compose(
        "--clear-all",
        env={
            "RUNTIME_SCOPE_DIR": str(runtime_dir),
            "FAKE_DOCKER_LOG": str(log_file),
            "FAKE_RUNNING_PROJECTS": "proj-running-scope",
            "PATH": f"{docker_dir}{os.pathsep}{os.environ['PATH']}",
        },
    )

    assert result.returncode == 0
    assert list(runtime_dir.iterdir()) == []
    assert log_file.read_text().splitlines() == [
        "compose-down:proj-running-scope",
        "compose-down:proj-stopped-scope",
    ]
    assert (
        "Clearing scope 'running-scope' (project=proj-running-scope, stack_state=running)."
        in result.stdout
    )
    assert "Clearing scope 'metadata-only' metadata only" in result.stdout


def test_clear_replaces_wipe_for_active_scope_cleanup(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime-scopes"
    runtime_dir.mkdir()
    docker_dir, log_file = _write_fake_docker(tmp_path)
    env_file = tmp_path / "test.env"
    env_file.write_text(
        "\n".join(
            [
                "PGHOST=localhost",
                "PGPORT=35444",
                "APP_PORT=35051",
                "PGUSER=postgres",
                "PGPASSWORD=password",
                "PGDATABASE=fmrif_scheduler_icons",
                "MAIL__DEFAULT_SENDER=test@example.com",
                "COMPOSE_PROJECT_NAME=scheduler",
            ]
        )
        + "\n"
    )

    result = _run_compose(
        "--clear",
        env={
            "ENVFILE": str(env_file),
            "RUNTIME_SCOPE_DIR": str(runtime_dir),
            "FMRIF_RUNTIME_SCOPE": "icons",
            "FAKE_DOCKER_LOG": str(log_file),
            "PATH": f"{docker_dir}{os.pathsep}{os.environ['PATH']}",
        },
    )

    assert result.returncode == 0
    assert "Clear mode: removing scope 'icons' stack and metadata." in result.stdout
    assert "Cleared runtime scope 'icons'." in result.stdout
    assert not (runtime_dir / "icons").exists()
    assert log_file.read_text().splitlines() == ["compose-down:scheduler-icons"]


def test_clear_all_stops_tracked_host_app_process(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime-scopes"
    runtime_dir.mkdir()
    docker_dir, log_file = _write_fake_docker(tmp_path)
    app_port = _reserve_free_tcp_port()
    listener = _start_http_listener(app_port)
    try:
        _write_scope_file(
            runtime_dir,
            "default",
            "proj-default",
            extra_lines={
                "FMRIF_RUNTIME_SCOPE_OFFSET": 0,
                "APP_PORT": app_port,
                "HOST_APP_PID": listener.pid,
            },
        )

        result = _run_compose(
            "--clear-all",
            env={
                "RUNTIME_SCOPE_DIR": str(runtime_dir),
                "FAKE_DOCKER_LOG": str(log_file),
                "PATH": f"{docker_dir}{os.pathsep}{os.environ['PATH']}",
            },
        )

        assert result.returncode == 0
        assert "Stopping tracked host app for scope 'default'" in result.stdout
        listener.wait(timeout=5)
        assert not (runtime_dir / "default").exists()
    finally:
        if listener.poll() is None:
            listener.terminate()
            listener.wait(timeout=5)


def test_clear_all_warns_when_listener_remains_after_cleanup(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime-scopes"
    runtime_dir.mkdir()
    docker_dir, log_file = _write_fake_docker(tmp_path)
    app_port = _reserve_free_tcp_port()
    listener = _start_http_listener(app_port)
    try:
        _write_scope_file(
            runtime_dir,
            "default",
            "proj-default",
            extra_lines={
                "FMRIF_RUNTIME_SCOPE_OFFSET": 0,
                "APP_PORT": app_port,
            },
        )

        result = _run_compose(
            "--clear-all",
            env={
                "RUNTIME_SCOPE_DIR": str(runtime_dir),
                "FAKE_DOCKER_LOG": str(log_file),
                "PATH": f"{docker_dir}{os.pathsep}{os.environ['PATH']}",
            },
        )

        assert result.returncode == 0
        assert "still has listeners bound after cleanup" in result.stderr
        assert f"APP_PORT={app_port}" in result.stderr
    finally:
        listener.terminate()
        listener.wait(timeout=5)
