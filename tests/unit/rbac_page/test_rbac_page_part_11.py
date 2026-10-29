import csv
import html
import io
import uuid
from io import BytesIO

import pytest
from route_seed import (
    create_group,
    ensure_active_user,
    ensure_admin_user,
    extract_csrf_token,
    set_admin_session,
)

from scheduler import logic, model

pytestmark = pytest.mark.route


def _seed_admin_config(
    overrides: dict[str, str], *, updated_by: str = "test-admin"
) -> None:
    for key, value in sorted(overrides.items()):
        row = model.get(model.AppSetting, key)
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
    assert "Admin configuration" in body
    assert 'name="admin_listserv"' in body
    assert 'name="admin_default_sender"' in body
    assert 'name="admin_mailing_lists"' in body
    assert 'value="listserv-from-db@example.com"' in body
    assert 'value="sender-from-db@example.com"' in body
    assert '"Ops": "Operations"' in html.unescape(body)


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
    assert model.get(model.GroupMember, (group_id, user_id)) is not None
    assert model.get(model.PrimaryGroupMember, (group_id, user_id)) is not None

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
    assert model.get(model.GroupMember, (group_id, user_id)) is None
