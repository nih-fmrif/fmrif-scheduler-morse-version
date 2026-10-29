import os

from scheduler.runtime_scope import (
    apply_runtime_scope_database_env,
    load_runtime_scope_metadata,
    resolve_scoped_runtime_values,
    runtime_scope_metadata_path,
    runtime_scope_offset,
    sanitize_runtime_scope,
)


def test_sanitize_runtime_scope_normalizes_empty_and_symbols():
    assert sanitize_runtime_scope(None) == "default"
    assert sanitize_runtime_scope(" Codex 2418 Deploy ") == "codex-2418-deploy"


def test_load_runtime_scope_metadata_reads_scope_file(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNTIME_SCOPE_DIR", str(tmp_path))
    metadata_path = runtime_scope_metadata_path("agent-demo")
    metadata_path.write_text(
        "\n".join(
            [
                "# comment",
                "PGHOST=127.0.0.1",
                "PGPORT=61626",
                "PGUSER=postgres",
                "PGPASSWORD=password",
                "PGDATABASE=fmrif_scheduler",
                "FMRIF_RUNTIME_SCOPE_OFFSET=1160",
            ]
        ),
        encoding="utf-8",
    )

    assert load_runtime_scope_metadata("agent-demo") == {
        "PGHOST": "127.0.0.1",
        "PGPORT": "61626",
        "PGUSER": "postgres",
        "PGPASSWORD": "password",
        "PGDATABASE": "fmrif_scheduler",
        "FMRIF_RUNTIME_SCOPE_OFFSET": "1160",
    }


def test_apply_runtime_scope_database_env_uses_scoped_port(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNTIME_SCOPE_DIR", str(tmp_path))
    monkeypatch.setenv("FMRIF_RUNTIME_SCOPE", "codex2418deploy")
    for name in ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("FMRIF_RUNTIME_SCOPE_OFFSET", raising=False)
    runtime_scope_metadata_path().write_text(
        "\n".join(
            [
                "PGHOST=127.0.0.1",
                "PGPORT=61626",
                "PGUSER=postgres",
                "PGPASSWORD=password",
                "PGDATABASE=fmrif_scheduler",
                "FMRIF_RUNTIME_SCOPE_OFFSET=1160",
            ]
        ),
        encoding="utf-8",
    )

    applied = apply_runtime_scope_database_env()

    assert applied == {
        "PGHOST": "127.0.0.1",
        "PGUSER": "postgres",
        "PGPASSWORD": "password",
        "PGDATABASE": "fmrif_scheduler",
        "PGPORT": "62786",
        "FMRIF_RUNTIME_SCOPE_OFFSET": "1160",
    }
    assert os.environ["PGPORT"] == "62786"


def test_apply_runtime_scope_database_env_keeps_explicit_env(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNTIME_SCOPE_DIR", str(tmp_path))
    monkeypatch.setenv("FMRIF_RUNTIME_SCOPE", "default")
    for name in ("PGHOST", "PGUSER", "PGPASSWORD", "PGDATABASE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PGPORT", "9999")
    runtime_scope_metadata_path().write_text(
        "\n".join(
            [
                "PGHOST=127.0.0.1",
                "PGPORT=61626",
                "PGUSER=postgres",
                "PGPASSWORD=password",
                "PGDATABASE=fmrif_scheduler",
            ]
        ),
        encoding="utf-8",
    )

    applied = apply_runtime_scope_database_env()

    assert applied["PGHOST"] == "127.0.0.1"
    assert "PGPORT" not in applied
    assert os.environ["PGPORT"] == "9999"


def test_runtime_scope_offset_uses_scope_file_value(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNTIME_SCOPE_DIR", str(tmp_path))
    monkeypatch.setenv("FMRIF_RUNTIME_SCOPE", "agent-demo")
    for name in (
        "PGHOST",
        "PGPORT",
        "PGUSER",
        "PGPASSWORD",
        "PGDATABASE",
        "APP_PORT",
        "FMRIF_RUNTIME_SCOPE_OFFSET",
    ):
        monkeypatch.delenv(name, raising=False)
    runtime_scope_metadata_path().write_text(
        "\n".join(
            [
                "PGPORT=61626",
                "FMRIF_RUNTIME_SCOPE_OFFSET=1160",
            ]
        ),
        encoding="utf-8",
    )

    assert runtime_scope_offset() == 1160


def test_resolve_scoped_runtime_values_applies_offset_to_configured_ports(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("RUNTIME_SCOPE_DIR", str(tmp_path))
    monkeypatch.setenv("FMRIF_RUNTIME_SCOPE", "agent-demo")
    for name in (
        "PGHOST",
        "PGPORT",
        "PGUSER",
        "PGPASSWORD",
        "PGDATABASE",
        "APP_PORT",
        "FMRIF_RUNTIME_SCOPE_OFFSET",
    ):
        monkeypatch.delenv(name, raising=False)
    runtime_scope_metadata_path().write_text(
        "\n".join(
            [
                "PGHOST=127.0.0.1",
                "PGPORT=61626",
                "APP_PORT=5051",
                "FMRIF_RUNTIME_SCOPE_OFFSET=1160",
            ]
        ),
        encoding="utf-8",
    )

    resolved = resolve_scoped_runtime_values(
        {
            "PGHOST": "localhost",
            "PGPORT": "5444",
            "APP_PORT": "5051",
        }
    )

    assert resolved == {
        "PGHOST": "127.0.0.1",
        "PGPORT": "62786",
        "APP_PORT": "6211",
        "FMRIF_RUNTIME_SCOPE_OFFSET": "1160",
    }


def test_resolve_scoped_runtime_values_can_leave_ports_unscoped(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNTIME_SCOPE_DIR", str(tmp_path))
    monkeypatch.setenv("FMRIF_RUNTIME_SCOPE", "agent-demo")
    for name in (
        "PGHOST",
        "PGPORT",
        "PGUSER",
        "PGPASSWORD",
        "PGDATABASE",
        "APP_PORT",
        "FMRIF_RUNTIME_SCOPE_OFFSET",
    ):
        monkeypatch.delenv(name, raising=False)
    runtime_scope_metadata_path().write_text(
        "\n".join(
            [
                "PGPORT=61626",
                "APP_PORT=5051",
                "FMRIF_RUNTIME_SCOPE_OFFSET=1160",
            ]
        ),
        encoding="utf-8",
    )

    resolved = resolve_scoped_runtime_values(
        {
            "PGPORT": "5444",
            "APP_PORT": "5051",
        },
        scoped_port_names=frozenset(),
    )

    assert resolved == {
        "PGPORT": "61626",
        "APP_PORT": "5051",
        "FMRIF_RUNTIME_SCOPE_OFFSET": "1160",
    }
