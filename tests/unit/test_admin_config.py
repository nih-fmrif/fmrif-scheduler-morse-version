import csv
import datetime
import io
import json
import uuid

from scheduler import logic, model


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
    assert model.get(model.GroupMember, (group_id, user_id)) is not None
    assert model.get(model.PrimaryGroupMember, (group_id, user_id)) is not None

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
