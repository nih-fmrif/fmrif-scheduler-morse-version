import uuid

import pytest
from route_seed import (
    ensure_active_user,
    ensure_group,
    set_group_membership,
    set_session_user,
)

from scheduler import model
from scheduler.app import app

pytestmark = pytest.mark.route


def test_home_shows_technologist_join_form_link_for_eligible_dev_member():
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

    client = app.test_client()
    set_session_user(
        client,
        username=user_id,
        email=email,
        display_name="Home Tech User",
    )

    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "technologist join form" in body
    assert 'href="/join/tech"' in body


def test_home_hides_technologist_join_form_link_for_non_dev_member():
    user_id = f"home-user-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Home User")

    client = app.test_client()
    set_session_user(
        client,
        username=user_id,
        email=email,
        display_name="Home User",
    )

    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'href="/groups"' in body
    assert "technologist join form" not in body


def test_home_hides_groups_link_for_inactive_user():
    user_id = f"home-inactive-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Home Inactive User")
    with app.app_context():
        user = model.User.query.get(user_id)
        assert user is not None
        user.active = False
        model.db.session.add(user)
        model.db.session.commit()

    client = app.test_client()
    set_session_user(
        client,
        username=user_id,
        email=email,
        display_name="Home Inactive User",
    )

    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'href="/groups"' not in body
