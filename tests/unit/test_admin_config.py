import csv
import datetime
import io
import json
import subprocess
import tempfile
import uuid
from pathlib import Path

import pytest

import scheduler.logic._admin_config_operations as ops_logic
import scheduler.logic.admin_config as logic
from scheduler import model


def test_admin_mapping_text_round_trips_user_group_rows(app_context):
    user_id = f"mu{uuid.uuid4().hex[:6]}"
    group_id = f"G{uuid.uuid4().hex[:6]}"

    model.db.session.add(
        model.Group(
            id=group_id,
            label=f"Group {group_id}",
            description=f"Description {group_id}",
            color="#123456",
            active=True,
            has_membership=True,
        )
    )
    model.db.session.add(
        model.User(
            id=user_id,
            label=user_id,
            active=True,
            addr=f"{user_id}@example.com",
        )
    )
    model.db.session.commit()

    csv_text = f"usr,dept,pi\n{user_id},{group_id},pi\n"
    rows = logic.parse_admin_mapping_text("user-dept", csv_text)
    validated_rows = logic.validate_import_rows("user-dept", rows)

    applied_count = logic.apply_import_rows("user-dept", validated_rows)
    model.db.session.commit()

    assert applied_count == 1
    assert model.db.session.get(model.GroupMember, (group_id, user_id)) is not None
    assert (
        model.db.session.get(model.PrimaryGroupMember, (group_id, user_id)) is not None
    )

    rendered = logic.format_admin_mapping_rows_for_form("user-dept")
    parsed_rows = list(csv.reader(io.StringIO(rendered)))
    assert parsed_rows[:1] == [["usr", "dept", "pi"]]
    assert [user_id, group_id, "pi"] in parsed_rows[1:]


def test_parse_admin_group_institute_mapping_normalizes_and_validates_shape():
    parsed = logic.parse_admin_group_institute_mapping(
        json.dumps(
            {
                "canonical_institutes": {
                    "NIMH": {
                        "label": "National Institute of Mental Health",
                        "kind": "nih_ic",
                        "active": True,
                    },
                    "NMRF": {
                        "label": "NMRF",
                        "kind": "local_operational",
                        "active": True,
                    },
                },
                "raw_aliases": {
                    "National Institute of Mental Health": "NIMH",
                },
                "group_defaults": {
                    "DEV": "NMRF",
                },
                "exceptions": [
                    {
                        "group": "DEV",
                        "reason": "legacy shared slot",
                    }
                ],
            }
        )
    )

    assert parsed == {
        "canonical_institutes": {
            "NIMH": {
                "label": "National Institute of Mental Health",
                "kind": "nih_ic",
                "active": True,
            },
            "NMRF": {
                "label": "NMRF",
                "kind": "local_operational",
                "active": True,
            },
        },
        "raw_aliases": {
            "National Institute of Mental Health": "NIMH",
        },
        "group_defaults": {
            "DEV": "NMRF",
        },
        "exceptions": [
            {
                "group": "DEV",
                "device": "",
                "template": "",
                "raw_institute": "",
                "canonical_institute": "",
                "reason": "legacy shared slot",
            }
        ],
    }


def test_parse_admin_operations_form_normalizes_backup_and_restore_settings():
    backup_config, restore_config = logic.parse_admin_operations_form(
        {
            "ops_backup_enabled": "1",
            "ops_backup_directory": "/srv/backups/fmrif",
            "ops_backup_format": "plain",
            "ops_backup_retention_count": "14",
            "ops_backup_max_age_hours": "48",
            "ops_backup_min_free_gb": "8",
            "ops_restore_enabled": "true",
            "ops_restore_interval_days": "10",
        }
    )

    assert backup_config.enabled is True
    assert backup_config.directory == "/srv/backups/fmrif"
    assert backup_config.format == "plain"
    assert backup_config.retention_count == 14
    assert backup_config.max_age_hours == 48
    assert backup_config.min_free_gb == 8
    assert restore_config.enabled is True
    assert restore_config.interval_days == 10


def test_parse_admin_operations_form_rejects_invalid_backup_format():
    with pytest.raises(ValueError, match="backup format must be custom or plain"):
        logic.parse_admin_operations_form(
            {
                "ops_backup_enabled": "1",
                "ops_backup_directory": "/srv/backups/fmrif",
                "ops_backup_format": "tarball",
                "ops_backup_retention_count": "14",
                "ops_backup_max_age_hours": "48",
                "ops_backup_min_free_gb": "8",
                "ops_restore_enabled": "true",
                "ops_restore_interval_days": "10",
            }
        )


def test_collect_backup_status_reports_latest_backup_and_thresholds(app_context):
    with tempfile.TemporaryDirectory() as temp_dir:
        backup_dir = Path(temp_dir)
        latest = backup_dir / "fmrif-20260323T120000Z.dump"
        latest.write_bytes(b"backup-bytes")
        globals_file = backup_dir / "fmrif-20260324T120000Z.globals.sql"
        globals_file.write_text("-- globals --", encoding="utf-8")
        model.db.session.add(
            model.AppSetting(
                key=logic.ADMIN_SETTING_KEY_BACKUP_DIRECTORY,
                value=str(backup_dir),
                updated_by="test-admin",
            )
        )
        model.db.session.commit()

        status = logic.collect_backup_status()
        latest_backup = logic.latest_backup_file()
        latest_globals_backup = logic.latest_globals_backup_file()

    assert status["directory_exists"] is True
    assert status["latest_backup_path"] == str(latest)
    assert status["format"] == "custom"
    assert status["latest_backup_format"] == "custom"
    assert status["latest_backup_size_bytes"] == len(b"backup-bytes")
    assert status["backup_age_state"] == "ok"
    assert status["free_disk_state"] == "ok"
    assert latest_backup == latest
    assert latest_globals_backup == globals_file


def test_run_backup_operation_records_success_and_prunes_old_backups(
    app_context, monkeypatch
):
    with tempfile.TemporaryDirectory() as temp_dir:
        backup_dir = Path(temp_dir)
        stale = backup_dir / "fmrif-20240101T000000Z.dump"
        stale.write_bytes(b"stale-bytes")
        model.db.session.add_all(
            [
                model.AppSetting(
                    key=logic.ADMIN_SETTING_KEY_BACKUP_DIRECTORY,
                    value=str(backup_dir),
                    updated_by="test-admin",
                ),
                model.AppSetting(
                    key=logic.ADMIN_SETTING_KEY_BACKUP_RETENTION_COUNT,
                    value="1",
                    updated_by="test-admin",
                ),
            ]
        )
        model.db.session.commit()

        def fake_run(command, **kwargs):
            output_path = Path(command[command.index("-f") + 1])
            output_path.write_bytes(b"fresh-backup")
            return subprocess.CompletedProcess(command, 0, "", "")

        session_resets: list[str] = []

        monkeypatch.setattr(ops_logic.subprocess, "run", fake_run)
        monkeypatch.setattr(
            ops_logic,
            "_reset_admin_settings_session",
            lambda: session_resets.append("reset"),
        )

        result = logic.run_backup_operation(force=True, updated_by="tester")
        model.db.session.commit()

        assert result.status == "ok"
        assert result.backup_format == "custom"
        assert result.backup_path.endswith(".dump")
        assert result.size_bytes == len(b"fresh-backup")
        assert result.pruned_paths == (str(stale),)
        assert "--format=custom" in result.command
        assert session_resets == ["reset", "reset"]
        status = logic.collect_backup_status()
        assert status["last_status"] == "success"
        assert status["format"] == "custom"
        assert status["last_path"] == result.backup_path
        assert status["last_size_bytes"] == len(b"fresh-backup")


def test_run_backup_operation_supports_plain_format(app_context, monkeypatch):
    with tempfile.TemporaryDirectory() as temp_dir:
        backup_dir = Path(temp_dir)
        model.db.session.add_all(
            [
                model.AppSetting(
                    key=logic.ADMIN_SETTING_KEY_BACKUP_DIRECTORY,
                    value=str(backup_dir),
                    updated_by="test-admin",
                ),
                model.AppSetting(
                    key=logic.ADMIN_SETTING_KEY_BACKUP_FORMAT,
                    value="plain",
                    updated_by="test-admin",
                ),
            ]
        )
        model.db.session.commit()

        def fake_run(command, **kwargs):
            output_path = Path(command[command.index("-f") + 1])
            output_path.write_text("-- plain backup --", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        monkeypatch.setattr(ops_logic.subprocess, "run", fake_run)

        result = logic.run_backup_operation(force=True, updated_by="tester")
        model.db.session.commit()

        assert result.status == "ok"
        assert result.backup_format == "plain"
        assert result.backup_path.endswith(".sql")
        assert "--format=plain" in result.command
        status = logic.collect_backup_status()
        assert status["format"] == "plain"
        assert status["latest_backup_format"] == "plain"


def test_run_globals_backup_operation_records_success_and_prunes_old_backups(
    app_context, monkeypatch
):
    with tempfile.TemporaryDirectory() as temp_dir:
        backup_dir = Path(temp_dir)
        stale = backup_dir / "fmrif-20240101T000000Z.globals.sql"
        stale.write_text("-- stale globals --", encoding="utf-8")
        model.db.session.add_all(
            [
                model.AppSetting(
                    key=logic.ADMIN_SETTING_KEY_BACKUP_DIRECTORY,
                    value=str(backup_dir),
                    updated_by="test-admin",
                ),
                model.AppSetting(
                    key=logic.ADMIN_SETTING_KEY_BACKUP_RETENTION_COUNT,
                    value="1",
                    updated_by="test-admin",
                ),
            ]
        )
        model.db.session.commit()

        chown_calls: list[tuple[Path, str | None, str | None]] = []

        def fake_run(command, **kwargs):
            kwargs["stdout"].write("-- fresh globals --")
            return subprocess.CompletedProcess(command, 0, "", "")

        def fake_chown(path, *, user=None, group=None):
            chown_calls.append((Path(path), user, group))

        monkeypatch.setattr(ops_logic.subprocess, "run", fake_run)
        monkeypatch.setattr(ops_logic.shutil, "chown", fake_chown)

        result = logic.run_globals_backup_operation(
            force=False,
            updated_by="tester",
            owner_user="fmrif-scheduler",
            owner_group="fmrif-scheduler",
        )
        model.db.session.commit()

        assert result.status == "ok"
        assert result.backup_format == "globals"
        assert result.backup_path.endswith(".globals.sql")
        assert result.size_bytes == len("-- fresh globals --")
        assert result.pruned_paths == (str(stale),)
        assert "--globals-only" in result.command
        assert chown_calls == [
            (
                Path(result.backup_path),
                "fmrif-scheduler",
                "fmrif-scheduler",
            )
        ]
        assert logic.latest_globals_backup_file() == Path(result.backup_path)


def test_run_restore_drill_operation_records_success(app_context, monkeypatch):
    with tempfile.TemporaryDirectory() as temp_dir:
        backup_dir = Path(temp_dir)
        latest = backup_dir / "fmrif-20260323T120000Z.dump"
        latest.write_bytes(b"backup-bytes")
        model.db.session.add(
            model.AppSetting(
                key=logic.ADMIN_SETTING_KEY_BACKUP_DIRECTORY,
                value=str(backup_dir),
                updated_by="test-admin",
            )
        )
        model.db.session.commit()

        commands: list[list[str]] = []
        databases: list[str] = []

        class FakeCursor:
            def __init__(self, database: str):
                self.database = database

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, query, params=None):
                return None

            def fetchone(self):
                return (True, True, True)

        class FakeConnection:
            def __init__(self, database: str):
                self.database = database
                self.autocommit = False

            def cursor(self):
                return FakeCursor(self.database)

            def close(self):
                return None

            def set_isolation_level(self, level):
                return None

        def fake_connect(*, host, port, user, password, database):
            databases.append(database)
            return FakeConnection(database)

        def fake_run(command, **kwargs):
            commands.append(list(command))
            return subprocess.CompletedProcess(command, 0, "", "")

        session_resets: list[str] = []

        monkeypatch.setattr(ops_logic.psycopg2, "connect", fake_connect)
        monkeypatch.setattr(ops_logic.subprocess, "run", fake_run)
        monkeypatch.setattr(
            ops_logic,
            "_reset_admin_settings_session",
            lambda: session_resets.append("reset"),
        )

        result = logic.run_restore_drill_operation(force=True, updated_by="tester")
        model.db.session.commit()

        assert result.status == "ok"
        assert result.backup_path == str(latest)
        assert "_restore_" in result.database_name
        assert commands and commands[0][0] == "pg_restore"
        assert commands[0][-1] == str(latest)
        assert databases[0] == "postgres"
        assert databases[1] == result.database_name
        assert session_resets == ["reset", "reset"]
        status = logic.collect_restore_drill_status()
        assert status["last_status"] == "success"
        assert status["last_database"] == result.database_name
        assert status["last_duration_seconds"] is not None


def test_drop_database_retries_when_other_role_backend_is_transient(monkeypatch):
    executed: list[tuple[str, object | None]] = []
    drop_attempts = 0

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params=None):
            nonlocal drop_attempts
            text = str(query)
            executed.append((text, params))
            if "DROP DATABASE IF EXISTS" in text:
                drop_attempts += 1
                if drop_attempts == 1:
                    raise ops_logic.psycopg2.OperationalError(
                        "database is being accessed by other users"
                    )

        def fetchone(self):
            return (1,)

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(ops_logic.time, "sleep", lambda _: None)

    ops_logic._drop_database(
        FakeConnection(),
        "fmrif_scheduler_restore_test",
        retry_timeout_seconds=1.0,
        retry_interval_seconds=0.0,
    )

    terminate_queries = [
        text for text, _params in executed if "SELECT pg_terminate_backend" in text
    ]
    assert terminate_queries
    assert "AND usename = current_user" in terminate_queries[0]
    assert drop_attempts == 2


def test_parse_admin_group_institute_mapping_rejects_unknown_canonical_targets():
    try:
        logic.parse_admin_group_institute_mapping(
            json.dumps(
                {
                    "canonical_institutes": {
                        "NIMH": {
                            "label": "National Institute of Mental Health",
                            "kind": "nih_ic",
                            "active": True,
                        }
                    },
                    "raw_aliases": {
                        "Legacy NIMH": "NOPE",
                    },
                }
            )
        )
    except ValueError as ex:
        assert "unknown canonical institute" in str(ex)
    else:
        raise AssertionError("expected parser to reject unknown canonical target")


def test_recommended_group_institute_mapping_covers_official_and_operational_ids():
    mapping = logic.recommended_group_institute_mapping()

    assert mapping["canonical_institutes"]["NIMH"]["kind"] == "nih_ic"
    assert (
        mapping["canonical_institutes"]["NCCIH"]["label"]
        == "National Center for Complementary and Integrative Health"
    )
    assert mapping["canonical_institutes"]["DEV"]["kind"] == "local_operational"
    assert (
        mapping["canonical_institutes"]["NMRF"]["label"] == "NIH MRI Research Facility"
    )
    assert mapping["raw_aliases"]["NCCAM"] == "NCCIH"
    assert mapping["raw_aliases"]["GE"] == "MAINT"


def test_get_admin_group_institute_mapping_uses_recommended_default_when_unset(
    app_context,
):
    assert logic.admin_group_institute_mapping_uses_recommended_default() is True
    mapping = logic.get_admin_group_institute_mapping()

    assert mapping["canonical_institutes"]["NIMH"]["label"] == (
        "National Institute of Mental Health"
    )
    assert mapping["canonical_institutes"]["DEV"]["kind"] == "local_operational"
    assert "NCCAM" in mapping["raw_aliases"]


def test_normalize_group_institute_history_window_years_clamps_to_supported_range():
    assert logic.normalize_group_institute_history_window_years("") == 2
    assert logic.normalize_group_institute_history_window_years("abc") == 2
    assert logic.normalize_group_institute_history_window_years("0") == 1
    assert logic.normalize_group_institute_history_window_years("7") == 7
    assert logic.normalize_group_institute_history_window_years("99") == 30
    assert logic.normalize_group_institute_history_window_years(99) == 30


def test_scan_admin_group_institute_mapping_surfaces_group_and_template_issues(
    app_context,
):
    inst_primary = f"I{uuid.uuid4().hex[:3]}".upper()[:4]
    inst_secondary = f"J{uuid.uuid4().hex[:3]}".upper()[:4]
    inst_inactive = f"K{uuid.uuid4().hex[:3]}".upper()[:4]
    group_match = f"G{uuid.uuid4().hex[:5]}".upper()[:6]
    group_missing = f"G{uuid.uuid4().hex[:5]}".upper()[:6]
    group_inactive = f"G{uuid.uuid4().hex[:5]}".upper()[:6]
    device_id = f"D{uuid.uuid4().hex[:3]}".upper()[:4]

    model.db.session.add_all(
        [
            model.Inst(id=inst_primary, label="Primary", active=True),
            model.Inst(id=inst_secondary, label="Secondary", active=True),
            model.Inst(id=inst_inactive, label="Inactive", active=False),
        ]
    )
    model.db.session.flush()
    model.db.session.add_all(
        [
            model.Group(
                id=group_match,
                label=group_match,
                description=group_match,
                color="#123456",
                active=True,
                inst=inst_primary,
                has_membership=True,
            ),
            model.Group(
                id=group_missing,
                label=group_missing,
                description=group_missing,
                color="#654321",
                active=True,
                inst=None,
                has_membership=True,
            ),
            model.Group(
                id=group_inactive,
                label=group_inactive,
                description=group_inactive,
                color="#abcdef",
                active=True,
                inst=inst_inactive,
                has_membership=True,
            ),
            model.Device(
                id=device_id,
                label=device_id,
                description=device_id,
                active=True,
                addr="",
                tech_addr="",
                med_addr="",
                train_addr="",
            ),
            model.TemplateEntry(
                id=int(uuid.uuid4().int % 1000000),
                device=device_id,
                template="a",
                dow=1,
                hour=9,
                group=group_match,
                user=None,
                inst=inst_secondary,
            ),
        ]
    )
    model.db.session.commit()

    scan = logic.scan_admin_group_institute_mapping(
        {
            "canonical_institutes": {
                inst_primary: {
                    "label": "Primary Canonical",
                    "kind": "nih_ic",
                    "active": True,
                },
                inst_secondary: {
                    "label": "Secondary Canonical",
                    "kind": "local_operational",
                    "active": True,
                },
                "UNUSED": {
                    "label": "Unused Canonical",
                    "kind": "nih_ic",
                    "active": True,
                },
            },
            "raw_aliases": {},
            "group_defaults": {
                "UNKNOWN": inst_primary,
            },
            "exceptions": [],
        }
    )

    sections = {section["id"]: section for section in scan["sections"]}

    assert any(
        item["label"] == group_missing
        for item in sections["groups-missing-default-institute"]["rows"]
    )
    assert any(
        item["label"] == group_inactive
        for item in sections["groups-inactive-default-institute"]["rows"]
    )
    assert any(
        item["label"] == f"{device_id}:a:{group_match}"
        for item in sections["template-default-mismatches"]["rows"]
    )
    assert any(
        item["label"] == "UNKNOWN"
        for item in sections["unknown-group-default-overrides"]["rows"]
    )
    assert any(
        item["label"] == "UNUSED"
        for item in sections["unused-canonical-institutes"]["rows"]
    )


def test_scan_admin_group_institute_schedule_history_surfaces_recent_issues(
    app_context,
):
    today = datetime.date(2026, 3, 12)
    recent_date = today - datetime.timedelta(days=21)
    old_date = today - datetime.timedelta(days=900)
    inst_primary = f"I{uuid.uuid4().hex[:3]}".upper()[:4]
    inst_secondary = f"J{uuid.uuid4().hex[:3]}".upper()[:4]
    inst_unmapped = f"K{uuid.uuid4().hex[:3]}".upper()[:4]
    group_id = f"G{uuid.uuid4().hex[:5]}".upper()[:6]
    device_id = f"D{uuid.uuid4().hex[:3]}".upper()[:4]
    template_id = int(uuid.uuid4().int % 1000000)
    user_id = f"u{uuid.uuid4().hex[:6]}"

    model.db.session.add_all(
        [
            model.Inst(id=inst_primary, label="Primary", active=True),
            model.Inst(id=inst_secondary, label="Secondary", active=True),
            model.Inst(id=inst_unmapped, label="Unmapped", active=True),
            model.User(
                id=user_id,
                label=user_id,
                active=True,
                addr=f"{user_id}@example.com",
            ),
        ]
    )
    model.db.session.commit()

    model.db.session.add_all(
        [
            model.Group(
                id=group_id,
                label=group_id,
                description=group_id,
                color="#123456",
                active=True,
                inst=inst_primary,
                has_membership=True,
            ),
            model.Group(
                id=device_id,
                label=device_id,
                description=f"device row {device_id}",
                color="#345678",
                active=True,
                inst=inst_primary,
                has_membership=False,
            ),
            model.Device(
                id=device_id,
                label=device_id,
                description=device_id,
                active=True,
                addr="",
                tech_addr="",
                med_addr="",
                train_addr="",
            ),
            model.TemplateEntry(
                id=template_id,
                device=device_id,
                template="H",
                dow=recent_date.weekday(),
                hour=8,
                group=group_id,
                user=None,
                inst=inst_primary,
            ),
        ]
    )
    model.db.session.commit()

    model.db.session.add_all(
        [
            model.ScheduleEntry(
                device=device_id,
                template=template_id,
                date=recent_date,
                dow=recent_date.weekday(),
                hour=8,
                group=group_id,
                user=user_id,
                orig_group=group_id,
                orig_inst=inst_secondary,
                modified_by="test-admin",
                used=False,
            ),
            model.ScheduleEntry(
                device=device_id,
                template=template_id,
                date=recent_date + datetime.timedelta(days=1),
                dow=(recent_date + datetime.timedelta(days=1)).weekday(),
                hour=9,
                group=group_id,
                user=user_id,
                orig_group=group_id,
                orig_inst=inst_unmapped,
                modified_by="test-admin",
                used=False,
            ),
            model.ScheduleEntry(
                device=device_id,
                template=template_id,
                date=old_date,
                dow=old_date.weekday(),
                hour=10,
                group=group_id,
                user=user_id,
                orig_group=group_id,
                orig_inst=inst_secondary,
                modified_by="test-admin",
                used=False,
            ),
        ]
    )
    model.db.session.commit()

    scan = logic.scan_admin_group_institute_schedule_history(
        {
            "canonical_institutes": {
                inst_primary: {
                    "label": "Primary Canonical",
                    "kind": "nih_ic",
                    "active": True,
                },
                inst_secondary: {
                    "label": "Secondary Canonical",
                    "kind": "local_operational",
                    "active": True,
                },
            },
            "raw_aliases": {},
            "group_defaults": {},
            "exceptions": [],
        },
        today=today,
    )

    assert scan["summary"] == {
        "window_years": 2,
        "window_start": "2024-03-12",
        "window_end": "2026-03-12",
        "schedule_entry_count": 2,
        "flagged_schedule_row_count": 2,
        "issue_count": 2,
    }

    sections = {section["id"]: section for section in scan["sections"]}
    assert any(
        item["label"] == f"{group_id}: {inst_secondary} != {inst_primary}"
        for item in sections["recent-schedule-default-mismatches"]["rows"]
    )
    assert any(
        item["label"] == f"{group_id}:{inst_unmapped}"
        for item in sections["recent-schedule-unmapped-institutes"]["rows"]
    )


def test_scan_admin_group_institute_schedule_history_clamps_window_years(
    app_context,
):
    today = datetime.date(2026, 3, 12)

    scan = logic.scan_admin_group_institute_schedule_history(
        logic.recommended_group_institute_mapping(),
        window_years=99,
        today=today,
    )

    assert scan["summary"]["window_years"] == 30
    assert scan["summary"]["window_start"] == "1996-03-19"


def test_export_group_institute_issue_rows_includes_recent_history_when_requested(
    app_context,
):
    today = datetime.date(2026, 3, 12)
    recent_date = today - datetime.timedelta(days=14)
    inst_primary = f"I{uuid.uuid4().hex[:3]}".upper()[:4]
    inst_secondary = f"J{uuid.uuid4().hex[:3]}".upper()[:4]
    group_current = f"G{uuid.uuid4().hex[:5]}".upper()[:6]
    group_history = f"H{uuid.uuid4().hex[:5]}".upper()[:6]
    device_id = f"D{uuid.uuid4().hex[:3]}".upper()[:4]
    template_id = int(uuid.uuid4().int % 1000000)
    user_id = f"u{uuid.uuid4().hex[:6]}"

    model.db.session.add_all(
        [
            model.Inst(id=inst_primary, label="Primary", active=True),
            model.Inst(id=inst_secondary, label="Secondary", active=True),
            model.User(
                id=user_id,
                label=user_id,
                active=True,
                addr=f"{user_id}@example.com",
            ),
        ]
    )
    model.db.session.commit()

    model.db.session.add_all(
        [
            model.Group(
                id=group_current,
                label=group_current,
                description=group_current,
                color="#123456",
                active=True,
                inst=None,
                has_membership=True,
            ),
            model.Group(
                id=group_history,
                label=group_history,
                description=group_history,
                color="#654321",
                active=True,
                inst=inst_primary,
                has_membership=True,
            ),
            model.Group(
                id=device_id,
                label=device_id,
                description=f"device row {device_id}",
                color="#345678",
                active=True,
                inst=inst_primary,
                has_membership=False,
            ),
            model.Device(
                id=device_id,
                label=device_id,
                description=device_id,
                active=True,
                addr="",
                tech_addr="",
                med_addr="",
                train_addr="",
            ),
            model.TemplateEntry(
                id=template_id,
                device=device_id,
                template="H",
                dow=recent_date.weekday(),
                hour=8,
                group=group_history,
                user=None,
                inst=inst_primary,
            ),
        ]
    )
    model.db.session.commit()

    model.db.session.add(
        model.ScheduleEntry(
            device=device_id,
            template=template_id,
            date=recent_date,
            dow=recent_date.weekday(),
            hour=8,
            group=group_history,
            user=user_id,
            orig_group=group_history,
            orig_inst=inst_secondary,
            modified_by="test-admin",
            used=False,
        )
    )
    model.db.session.commit()

    headers, rows = logic.export_group_institute_issue_rows(
        {
            "canonical_institutes": {
                inst_primary: {
                    "label": "Primary Canonical",
                    "kind": "nih_ic",
                    "active": True,
                },
                inst_secondary: {
                    "label": "Secondary Canonical",
                    "kind": "local_operational",
                    "active": True,
                },
            },
            "raw_aliases": {},
            "group_defaults": {},
            "exceptions": [],
        },
        include_recent_history=True,
        window_years=5,
        today=today,
    )

    assert headers == (
        "scope",
        "window_start",
        "window_end",
        "category",
        "severity",
        "count",
        "label",
        "detail",
    )
    assert any(
        row[0] == "current-config"
        and row[3] == "groups-missing-default-institute"
        and row[6] == group_current
        for row in rows
    )
    assert any(
        row[0] == "recent-schedule-history"
        and row[3] == "recent-schedule-default-mismatches"
        and row[1] == "2021-03-13"
        and row[6] == f"{group_history}: {inst_secondary} != {inst_primary}"
        for row in rows
    )
