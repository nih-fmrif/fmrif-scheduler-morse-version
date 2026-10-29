import csv
import datetime
import html
import io
import uuid
from io import BytesIO
from urllib.parse import parse_qs, urlparse

import pytest
from route_seed import (
    create_group,
    ensure_active_user,
    ensure_admin_user,
    extract_csrf_token,
    set_admin_session,
)
from sqlalchemy import select

import scheduler.logic.admin_config as logic
from scheduler import model

pytestmark = pytest.mark.route


def _seed_admin_config(
    overrides: dict[str, str], *, updated_by: str = "test-admin"
) -> None:
    for key, value in sorted(overrides.items()):
        row = model.db.session.get(model.AppSetting, key)
        if row is None:
            row = model.AppSetting(key=key)
        row.value = value
        row.updated_by = updated_by
        model.db.session.add(row)
    model.db.session.commit()


@pytest.mark.covers_route("/app/issues", "GET")
def test_app_issues_page_shows_admin_configuration_fields(route_client):
    ensure_admin_user()
    set_admin_session(route_client)
    _seed_admin_config(
        {
            "core.listserv": "listserv-from-db@example.com",
            "mail.default_sender": "sender-from-db@example.com",
            "mail.mailing_lists": '{"Ops": "Operations"}',
        }
    )

    response = route_client.get("/app/issues")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    normalized_body = " ".join(body.split())
    assert "Admin configuration" in body
    assert 'name="admin_listserv"' in body
    assert 'name="admin_default_sender"' in body
    assert 'name="admin_mailing_lists"' in body
    assert 'name="admin_group_institute_mapping"' in body
    assert 'id="admin-mapping-user-dept"' in body
    assert 'id="admin-mapping-dev-dept"' in body
    assert 'id="admin-mapping-devperm"' in body
    assert 'value="listserv-from-db@example.com"' in body
    assert 'value="sender-from-db@example.com"' in body
    assert '"Ops": "Operations"' in html.unescape(body)
    assert "Organization mapping" in body
    assert "No stored mapping exists yet." in body
    assert '"NCCAM": "NCCIH"' in html.unescape(body)
    assert "run recent schedule scan" in normalized_body
    assert 'name="organization_history_years"' in body
    assert 'type="number"' in body
    assert 'min="1"' in body
    assert 'max="30"' in body
    assert 'value="2"' in body
    assert "download issues (CSV)" in body
    assert "Legacy CSV headers still use <code>dept</code>" in body
    assert "why <code>dept</code>?" in body
    assert 'href="/rbac"' in body
    assert 'Use the <a href="/rbac">RBAC explorer</a> for day-to-day' in normalized_body
    assert "usr,dept,pi" in body


@pytest.mark.covers_route("/app/issues/config", "POST")
def test_app_issues_config_updates_admin_settings(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    response = route_client.get("/app/issues")
    assert response.status_code == 200
    csrf_token = extract_csrf_token(response.get_data(as_text=True))

    post_response = route_client.post(
        "/app/issues/config",
        data={
            "csrf_token": csrf_token,
            "return_query": "",
            "admin_listserv": "new-listserv@example.com",
            "admin_default_sender": "new-sender@example.com",
            "admin_mailing_lists": '{"Infra": "Infrastructure", "Ops": "Operations"}',
            "admin_group_institute_mapping": (
                '{"canonical_institutes": {"NIMH": {"label": "National Institute '
                'of Mental Health", "kind": "nih_ic", "active": true}, '
                '"NMRF": {"label": "NMRF", "kind": "local_operational", '
                '"active": true}}, "raw_aliases": {"National Institute of Mental '
                'Health": "NIMH"}, "group_defaults": {"DEV": "NMRF"}, '
                '"exceptions": [{"group": "DEV", "reason": "legacy shared slot"}]}'
            ),
        },
        follow_redirects=False,
    )

    assert post_response.status_code == 302
    assert post_response.headers["Location"].endswith("/app/issues")

    assert logic.get_admin_listserv() == "new-listserv@example.com"
    assert logic.get_admin_default_sender() == "new-sender@example.com"
    assert logic.get_admin_mailing_lists() == {
        "Infra": "Infrastructure",
        "Ops": "Operations",
    }
    assert logic.get_admin_group_institute_mapping() == {
        "canonical_institutes": {
            "NIMH": {
                "active": True,
                "kind": "nih_ic",
                "label": "National Institute of Mental Health",
            },
            "NMRF": {
                "active": True,
                "kind": "local_operational",
                "label": "NMRF",
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


@pytest.mark.covers_route("/app/issues/mapping/import", "POST")
def test_app_issues_mapping_import_and_export_user_dept(route_client):
    ensure_admin_user()
    set_admin_session(route_client)
    user_id = f"mapping-user-{uuid.uuid4().hex[:6]}"
    group_id = create_group()
    ensure_active_user(user_id, f"{user_id}@example.com", user_id)

    response = route_client.get("/app/issues")
    assert response.status_code == 200
    csrf_token = extract_csrf_token(response.get_data(as_text=True))

    csv_text = f"usr,dept,pi\n{user_id},{group_id},pi\n"
    import_response = route_client.post(
        "/app/issues/mapping/import",
        data={
            "csrf_token": csrf_token,
            "return_query": "",
            "mapping_kind": "user-dept",
            "mapping_file": (BytesIO(csv_text.encode("utf-8")), "user-dept.csv"),
        },
        follow_redirects=False,
    )
    assert import_response.status_code == 302
    assert model.db.session.get(model.GroupMember, (group_id, user_id)) is not None
    assert (
        model.db.session.get(model.PrimaryGroupMember, (group_id, user_id)) is not None
    )

    export_response = route_client.get("/app/issues/mapping/export/user-dept")
    assert export_response.status_code == 200
    assert (
        export_response.headers["Content-Disposition"]
        == 'attachment; filename="user-dept.csv"'
    )

    reader = csv.reader(io.StringIO(export_response.get_data(as_text=True)))
    rows = list(reader)
    assert rows[:1] == [["usr", "dept", "pi"]]
    assert [user_id, group_id, "pi"] in rows[1:]


@pytest.mark.covers_route("/app/issues/mapping/import", "POST")
def test_app_issues_mapping_import_rejects_invalid_csv(route_client):
    ensure_admin_user()
    set_admin_session(route_client)
    user_id = f"mapping-invalid-user-{uuid.uuid4().hex[:6]}"
    group_id = create_group()
    ensure_active_user(user_id, f"{user_id}@example.com", user_id)

    response = route_client.get("/app/issues")
    assert response.status_code == 200
    csrf_token = extract_csrf_token(response.get_data(as_text=True))

    invalid_csv_text = f"usr,dept\n{user_id},{group_id}\n"
    invalid_response = route_client.post(
        "/app/issues/mapping/import",
        data={
            "csrf_token": csrf_token,
            "return_query": "",
            "mapping_kind": "user-dept",
            "mapping_file": (
                BytesIO(invalid_csv_text.encode("utf-8")),
                "bad-user-dept.csv",
            ),
        },
        follow_redirects=False,
    )

    assert invalid_response.status_code == 302
    assert model.db.session.get(model.GroupMember, (group_id, user_id)) is None


@pytest.mark.covers_route("/app/issues/organization/history-scan", "POST")
def test_app_issues_history_scan_toggle_preserves_existing_query(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    response = route_client.get(
        "/app/issues?email_scope=user&organization_history_years=5"
    )
    assert response.status_code == 200
    csrf_token = extract_csrf_token(response.get_data(as_text=True))

    post_response = route_client.post(
        "/app/issues/organization/history-scan",
        data={
            "csrf_token": csrf_token,
            "return_query": "email_scope=user&organization_history_years=5",
            "enabled": "1",
            "organization_history_years": "99",
        },
        follow_redirects=False,
    )

    assert post_response.status_code == 302
    location = urlparse(post_response.headers["Location"])
    assert location.path == "/app/issues"
    assert parse_qs(location.query) == {
        "email_scope": ["user"],
        "organization_history_scan": ["1"],
        "organization_history_years": ["30"],
    }


def test_app_issues_page_and_export_show_recent_history_issues(route_client):
    ensure_admin_user()
    set_admin_session(route_client)
    today = datetime.date.today()
    recent_date = today - datetime.timedelta(days=7)
    inst_primary = "NIMH"
    inst_secondary = "NMRF"
    group_id = f"G{uuid.uuid4().hex[:5]}".upper()[:6]
    device_id = f"D{uuid.uuid4().hex[:3]}".upper()[:4]
    user_id = f"u{uuid.uuid4().hex[:6]}"

    for inst_id in (inst_primary, inst_secondary):
        row = model.db.session.get(model.Inst, inst_id)
        if row is None:
            row = model.Inst(id=inst_id, label=inst_id, active=True)
        else:
            row.active = True
        model.db.session.add(row)
    model.db.session.add(
        model.User(
            id=user_id,
            label=user_id,
            active=True,
            addr=f"{user_id}@example.com",
        )
    )
    model.db.session.commit()
    template_id = (
        model.db.session.scalar(select(model.func.max(model.TemplateEntry.id))) or 0
    ) + 1

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
            model.Template(
                id="H",
                device=device_id,
                label="History",
                description="History",
                hidden=False,
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

    model.db.session.add(
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
        )
    )
    model.db.session.commit()

    page_response = route_client.get(
        "/app/issues?organization_history_scan=1&organization_history_years=5"
    )
    assert page_response.status_code == 200
    body = page_response.get_data(as_text=True)
    assert "Recent schedule history" in body
    assert "Flagged rows:" in body
    assert 'name="organization_history_years"' in body
    assert 'value="5"' in body
    assert "selected number of years only" in body
    assert f"{group_id}: {inst_secondary} != {inst_primary}" in body

    export_response = route_client.get(
        "/app/issues/mapping/export/organization-issues"
        "?organization_history_scan=1&organization_history_years=5"
    )
    assert export_response.status_code == 200
    assert (
        export_response.headers["Content-Disposition"]
        == 'attachment; filename="organization-issues-recent-history.csv"'
    )
    rows = list(csv.reader(io.StringIO(export_response.get_data(as_text=True))))
    assert rows[:1] == [
        [
            "scope",
            "window_start",
            "window_end",
            "category",
            "severity",
            "count",
            "label",
            "detail",
        ]
    ]
    assert any(
        row[0] == "recent-schedule-history"
        and row[3] == "recent-schedule-default-mismatches"
        and row[1] == str(today - datetime.timedelta(days=365 * 5))
        and row[6] == f"{group_id}: {inst_secondary} != {inst_primary}"
        for row in rows[1:]
    )
