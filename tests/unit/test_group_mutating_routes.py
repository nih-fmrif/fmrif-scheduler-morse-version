import uuid

import pytest
from route_seed import (
    create_group,
    ensure_active_user,
    ensure_admin_user,
    set_admin_session,
    set_group_membership,
    set_session_user,
)

pytestmark = pytest.mark.route


@pytest.mark.covers_route("/group/<the_group>/edit", "POST")
def test_group_management_post_endpoints_are_retired_for_admin(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)
    group_id = create_group()

    edit = route_client.post(f"/group/{group_id}/edit", data={}, follow_redirects=False)
    membership = route_client.post(
        f"/group/{group_id}/membership", data={}, follow_redirects=False
    )
    pi = route_client.post(f"/group/{group_id}/pi", data={}, follow_redirects=False)

    assert edit.status_code == 404
    assert membership.status_code == 404
    assert pi.status_code == 404


def test_group_management_get_endpoints_are_retired_for_group_pi(
    route_client, route_app_context
):
    group_id = create_group()
    user_id = f"gpi{uuid.uuid4().hex[:6]}"
    ensure_active_user(user_id, f"{user_id}@example.com", user_id)
    set_group_membership(group_id, user_id, approved=True, pi=True)

    set_session_user(
        route_client,
        username=user_id,
        email=f"{user_id}@example.com",
        display_name=user_id,
        groups=[group_id],
    )

    edit = route_client.get(f"/group/{group_id}/edit")
    membership = route_client.get(f"/group/{group_id}/membership")
    pi = route_client.get(f"/group/{group_id}/pi")

    assert edit.status_code == 404
    assert membership.status_code == 404
    assert pi.status_code == 404
