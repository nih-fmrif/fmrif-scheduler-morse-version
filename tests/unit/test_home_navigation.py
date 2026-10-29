import uuid

import pytest
from route_seed import (
    ensure_active_user,
    ensure_admin_user,
    ensure_group,
    set_group_membership,
    set_session_user,
)

from scheduler import model

pytestmark = pytest.mark.route


def test_home_shows_technologist_join_form_link_for_eligible_dev_member(route_client):
    user_id = f"home-tech-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Home Tech User")
    ensure_group(
        "DEV",
        label="DEV",
        description="Development Group",
        color="#222222",
        active=True,
        has_membership=True,
    )
    set_group_membership("DEV", user_id, approved=True, pi=False)

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Home Tech User",
    )

    response = route_client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "FMRIF Scheduler" in body
    assert 'data-home-section="devices"' in body
    assert 'data-home-section="groups"' in body
    assert "technologist join form" in body
    assert 'href="/join/tech"' in body
    assert 'href="/mailing-lists"' in body


def test_home_hides_technologist_join_form_link_for_non_dev_member(route_client):
    user_id = f"home-user-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Home User")

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Home User",
    )

    response = route_client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'data-home-section="groups"' in body
    assert "technologist join form" not in body
    assert 'href="/mailing-lists"' in body


def test_home_hides_groups_link_for_inactive_user(route_client, route_app_context):
    user_id = f"home-inactive-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Home Inactive User")
    user = model.User.query.get(user_id)
    assert user is not None
    user.active = False
    model.db.session.add(user)
    model.db.session.flush()

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Home Inactive User",
    )

    response = route_client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Groups are available only to active users." in body
    assert 'href="/join"' not in body
    assert 'href="/mailing-lists"' in body


def test_home_shows_rbac_link_for_admin(route_client):
    ensure_admin_user()
    user_id = "test-admin"
    email = f"{user_id}@example.com"

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="RBAC Admin User",
    )

    response = route_client.get("/")
    body = response.get_data(as_text=True)
    assert 'href="/rbac"' in body


def test_home_hides_rbac_link_for_non_admin(route_client, route_app_context):
    user_id = f"home-user-nonadmin-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Home User")

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Home User",
    )

    response = route_client.get("/")
    body = response.get_data(as_text=True)
    assert 'href="/rbac"' not in body
