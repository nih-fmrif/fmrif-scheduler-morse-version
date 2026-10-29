from __future__ import annotations

import contextlib
import importlib
import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_script_module(script_name: str, module_name: str):
    script_path = REPO_ROOT / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_check_db_health_accepts_legacy_database_only_flag(monkeypatch, capsys):
    module = _load_script_module("check-db-health.py", "check_db_health_script")

    class _DummyApp:
        def app_context(self):
            return contextlib.nullcontext()

    monkeypatch.setattr(
        module,
        "create_app",
        lambda skip_startup_db_check=True: _DummyApp(),
    )
    monkeypatch.setattr(
        module.db_runtime,
        "probe_database_health",
        lambda: {
            "status": "ok",
            "latency_ms": 1.2,
            "active_connection_count": 1,
            "lock_wait_count": 0,
            "idle_in_transaction_count": 0,
        },
    )
    monkeypatch.setattr(module.db_runtime, "dispose_database_engines", lambda: None)

    exit_code = module.main(["--json", "--database-only"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["active_connection_count"] == 1


def test_rehearsal_database_name_defaults_to_dedicated_scratch_database():
    module = importlib.import_module("scheduler.deployment_rehearsal")

    assert (
        module.derive_rehearsal_database_name("fmrif_scheduler")
        == "fmrif_scheduler_deployment_rehearsal"
    )
    assert (
        module.derive_rehearsal_database_name("Mixed-Case Demo DB")
        == "mixed_case_demo_db_deployment_rehearsal"
    )


def test_docker_rehearsal_excludes_docs_submodule_git_metadata():
    dockerignore = (REPO_ROOT / ".dockerignore").read_text().splitlines()

    assert "fmrif-scheduler-docs/.git" in dockerignore


def test_debian_runtime_wrapper_scaffolds_compose_profile_when_env_missing():
    wrapper = (REPO_ROOT / "scripts" / "with-debian-runtime-stack.sh").read_text()

    assert "bash setup-dotenv.sh --profile compose" in wrapper


def test_run_db_backup_script_passes_backup_format_override(monkeypatch, capsys):
    module = _load_script_module("run-db-backup.py", "run_db_backup_script")

    class _DummyApp:
        def app_context(self):
            return contextlib.nullcontext()

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        module,
        "create_app",
        lambda skip_startup_db_check=True: _DummyApp(),
    )
    monkeypatch.setattr(module, "_commit_status_updates", lambda: None)

    def fake_run_backup_operation(*, force, updated_by, backup_format):
        captured["force"] = force
        captured["updated_by"] = updated_by
        captured["backup_format"] = backup_format
        return module.admin_logic.AdminOperationResult(
            status="ok",
            detail="created fmrif-test.sql (plain format)",
            backup_path="/tmp/fmrif-test.sql",
            backup_format="plain",
        )

    monkeypatch.setattr(
        module.admin_logic,
        "run_backup_operation",
        fake_run_backup_operation,
    )

    exit_code = module.main(["--json", "--backup-format", "plain"])

    assert exit_code == 0
    assert captured == {
        "force": False,
        "updated_by": "system",
        "backup_format": "plain",
    }
    payload = json.loads(capsys.readouterr().out)
    assert payload["backup_format"] == "plain"
    assert payload["backup_path"] == "/tmp/fmrif-test.sql"


def test_run_db_globals_backup_script_passes_owner_args(monkeypatch, capsys):
    module = _load_script_module(
        "run-db-globals-backup.py",
        "run_db_globals_backup_script",
    )

    class _DummyApp:
        def app_context(self):
            return contextlib.nullcontext()

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        module,
        "create_app",
        lambda skip_startup_db_check=True: _DummyApp(),
    )

    def fake_run_globals_backup_operation(
        *, force, updated_by, owner_user, owner_group
    ):
        captured["force"] = force
        captured["updated_by"] = updated_by
        captured["owner_user"] = owner_user
        captured["owner_group"] = owner_group
        return module.admin_logic.AdminOperationResult(
            status="ok",
            detail="created fmrif-test.globals.sql (globals companion backup)",
            backup_path="/tmp/fmrif-test.globals.sql",
            backup_format="globals",
        )

    monkeypatch.setattr(
        module.admin_logic,
        "run_globals_backup_operation",
        fake_run_globals_backup_operation,
    )

    exit_code = module.main(
        [
            "--json",
            "--owner-user",
            "fmrif-scheduler",
            "--owner-group",
            "fmrif-scheduler",
        ]
    )

    assert exit_code == 0
    assert captured == {
        "force": False,
        "updated_by": "system",
        "owner_user": "fmrif-scheduler",
        "owner_group": "fmrif-scheduler",
    }
    payload = json.loads(capsys.readouterr().out)
    assert payload["backup_format"] == "globals"
    assert payload["backup_path"] == "/tmp/fmrif-test.globals.sql"
