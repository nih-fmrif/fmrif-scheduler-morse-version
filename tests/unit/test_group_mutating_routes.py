import uuid

import pytest
from route_seed import (
    create_group,
    ensure_active_user,
    ensure_admin_user,
    extract_csrf_token,
    set_admin_session,
    set_group_membership,
)

from scheduler import model
from scheduler.app import app

pytestmark = pytest.mark.route


@pytest.mark.covers_route("/groups/add", "POST")
def test_groups_add_post_creates_group_and_membership():
    ensure_admin_user()
    pi_id = f"pi{uuid.uuid4().hex[:6]}"
    ensure_active_user(pi_id, f"{pi_id}@example.com", "PI User")

    client = app.test_client()
    set_admin_session(client)

    get_response = client.get("/groups/add")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))
    group_id = f"G{uuid.uuid4().hex[:6]}"

    post_response = client.post(
        "/groups/add",
        data={
            "csrf_token": csrf_token,
            "id": group_id,
            "label": f"Label {group_id}",
            "description": f"Long Description {group_id}",
            "addr": "",
            "link": "",
            "color": "#116699",
            "inst": "",
            "pi": pi_id,
            "active": "y",
        },
        follow_redirects=False,
    )

    assert post_response.status_code == 302
    assert post_response.headers["Location"].endswith(f"/group/{group_id}")
    with app.app_context():
        group = model.Group.query.get(group_id)
        assert group is not None
        assert model.GroupMember.query.get((group_id, pi_id)) is not None
        assert model.PrimaryGroupMember.query.get((group_id, pi_id)) is not None


@pytest.mark.covers_route("/group/<the_group>/edit", "POST")
def test_group_edit_post_updates_group_fields():
    ensure_admin_user()
    group_id = create_group()

    client = app.test_client()
    set_admin_session(client)

    get_response = client.get(f"/group/{group_id}/edit")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = client.post(
        f"/group/{group_id}/edit",
        data={
            "csrf_token": csrf_token,
            "label": f"Updated {group_id}",
            "description": f"Updated Description {group_id}",
            "addr": "",
            "link": "",
            "color": "#aa5500",
            "inst": "",
            "active": "y",
        },
        follow_redirects=False,
    )

    assert post_response.status_code == 302
    assert post_response.headers["Location"].endswith(f"/group/{group_id}")
    with app.app_context():
        group = model.Group.query.get(group_id)
        assert group is not None
        assert group.label == f"Updated {group_id}"
        assert group.description == f"Updated Description {group_id}"
        assert group.color == "#aa5500"


@pytest.mark.covers_route("/group/<the_group>/membership", "POST")
def test_group_membership_post_remove_deletes_member():
    ensure_admin_user()
    group_id = create_group()
    member_id = f"member{uuid.uuid4().hex[:5]}"
    ensure_active_user(member_id, f"{member_id}@example.com", member_id)
    set_group_membership(group_id, member_id, approved=True, pi=False)

    client = app.test_client()
    set_admin_session(client)

    get_response = client.get(f"/group/{group_id}/membership")
    html = get_response.get_data(as_text=True)
    csrf_token = extract_csrf_token(html)
    remove_button_name = f"members-member-{member_id}-remove"
    assert remove_button_name in html

    post_response = client.post(
        f"/group/{group_id}/membership",
        data={
            "csrf_token": csrf_token,
            remove_button_name: "y",
        },
        follow_redirects=False,
    )

    assert post_response.status_code == 302
    assert post_response.headers["Location"].endswith(f"/group/{group_id}/membership")
    with app.app_context():
        assert model.GroupMember.query.get((group_id, member_id)) is None


@pytest.mark.covers_route("/group/<the_group>/pi", "POST")
def test_group_pi_post_changes_primary_pi():
    ensure_admin_user()
    group_id = create_group()
    current_pi = f"curpi{uuid.uuid4().hex[:5]}"
    next_pi = f"newpi{uuid.uuid4().hex[:5]}"
    ensure_active_user(current_pi, f"{current_pi}@example.com", current_pi)
    ensure_active_user(next_pi, f"{next_pi}@example.com", next_pi)
    set_group_membership(group_id, current_pi, approved=True, pi=True)
    set_group_membership(group_id, next_pi, approved=True, pi=False)

    client = app.test_client()
    set_admin_session(client)

    get_response = client.get(f"/group/{group_id}/pi")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = client.post(
        f"/group/{group_id}/pi",
        data={
            "csrf_token": csrf_token,
            "pi": next_pi,
        },
        follow_redirects=False,
    )

    assert post_response.status_code == 302
    assert post_response.headers["Location"].endswith(f"/group/{group_id}/membership")
    with app.app_context():
        assert model.PrimaryGroupMember.query.get((group_id, next_pi)) is not None
        assert model.PrimaryGroupMember.query.get((group_id, current_pi)) is None
