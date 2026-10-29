import json
import uuid

import pytest
from route_seed import (
    create_device,
    create_group,
    ensure_active_user,
    ensure_admin_user,
    ensure_group,
    extract_csrf_token,
    seeded_scanner_id,
    set_admin_session,
    set_group_membership,
    set_session_user,
)

from scheduler import logic, model

pytestmark = pytest.mark.route


def _capture_rbac_events(
    monkeypatch,
) -> list[tuple[str, str, str, str, str, str]]:
    events: list[tuple[str, str, str, str, str, str]] = []

    def capture(
        action: str,
        actor: str,
        where: str,
        how: str,
        what: str,
        source_ip: str = "",
    ) -> None:
        events.append((action, actor, where, how, what, source_ip))

    monkeypatch.setattr(logic, "log_rbac_audit_event", capture)
    return events


@pytest.mark.covers_route("/rbac", "GET")
def test_rbac_page_renders_for_admin(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    response = route_client.get("/rbac")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "RBAC Explorer" in body
    assert "Explorer Controls" in body
    assert "Relationship Map" in body
    assert "find entity" in body
    assert "view by" in body
    assert "include inactive" in body
    assert "entity" in body
    assert "+ add group" in body
    assert "+ add device" in body
    assert "Review And Update" in body


def test_rbac_page_forbidden_for_non_admin(route_client):
    user_id = "normal-user-rbac"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Normal User")

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Normal User",
    )

    response = route_client.get("/rbac")

    assert response.status_code == 403


def test_rbac_page_renders_for_group_pi(route_client):
    group_id = create_group()
    user_id = f"gpi{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, user_id)
    set_group_membership(group_id, user_id, approved=True, pi=True)

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name=user_id,
        groups=[group_id],
    )

    response = route_client.get("/rbac")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "RBAC Explorer" in body
    assert "Explorer Controls" in body
    assert "RBAC audit visibility is restricted to admins." in body


def test_rbac_explorer_limits_scope_and_entities_for_group_pi(route_client):
    group_id = create_group()
    user_id = f"gpi{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, user_id)
    set_group_membership(group_id, user_id, approved=True, pi=True)

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name=user_id,
        groups=[group_id],
    )

    response = route_client.get("/json/v1/rbac/explorer?scope=device&detail=0&active=1")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["scope"] == "group"
    assert payload["include_inactive"] is False
    scopes = {scope["id"] for scope in payload["scopes"]}
    assert scopes == {"group"}
    entities = payload["entities"]
    assert len(entities) == 1
    assert entities[0]["id"] == group_id


def test_rbac_mutate_batch_for_group_pi_allows_membership_and_blocks_device_link(
    route_client, route_app_context
):
    group_id = create_group()
    manager_id = f"gpi{uuid.uuid4().hex[:6]}"
    member_id = f"mem{uuid.uuid4().hex[:6]}"
    ensure_active_user(manager_id, f"{manager_id}@example.com", manager_id)
    ensure_active_user(member_id, f"{member_id}@example.com", member_id)
    set_group_membership(group_id, manager_id, approved=True, pi=True)
    device_id = seeded_scanner_id()

    set_session_user(
        route_client,
        username=manager_id,
        email=f"{manager_id}@example.com",
        display_name=manager_id,
        groups=[group_id],
    )

    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))
    membership_response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "group",
            "entity": group_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "group.membership.set",
                        "group": group_id,
                        "user": member_id,
                        "member": True,
                        "approved": True,
                    }
                ]
            ),
        },
    )
    assert membership_response.status_code == 200
    member_row = model.GroupMember.query.get((group_id, member_id))
    assert member_row is not None
    assert member_row.approved is not None

    blocked_response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "group",
            "entity": group_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "device.group.set",
                        "group": group_id,
                        "device": device_id,
                        "linked": True,
                    }
                ]
            ),
        },
    )
    assert blocked_response.status_code == 403
    blocked_payload = blocked_response.get_json()
    assert blocked_payload is not None
    assert blocked_payload["ok"] is False
    assert "Permission denied" in blocked_payload["message"]


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_rejects_membership_pi_field(route_client, route_app_context):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    pi_owner = f"pi-owner-{uuid.uuid4().hex[:6]}"
    unrelated_member = f"member-{uuid.uuid4().hex[:6]}"
    stable_member = f"stable-{uuid.uuid4().hex[:6]}"
    ensure_active_user(pi_owner, f"{pi_owner}@example.com", pi_owner)
    ensure_active_user(
        unrelated_member, f"{unrelated_member}@example.com", unrelated_member
    )
    ensure_active_user(stable_member, f"{stable_member}@example.com", stable_member)
    set_group_membership(group_id, pi_owner, approved=True, pi=True)
    set_group_membership(group_id, stable_member, approved=True, pi=False)

    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))
    response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "group",
            "entity": group_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "group.membership.set",
                        "group": group_id,
                        "user": unrelated_member,
                        "member": True,
                        "approved": True,
                    },
                    {
                        # Membership updates no longer accept pi.
                        "kind": "group.membership.set",
                        "group": group_id,
                        "user": stable_member,
                        "member": True,
                        "approved": True,
                        "pi": True,
                    },
                ]
            ),
        },
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is False
    invalid_messages = [
        row["message"] for row in payload["results"] if row["status"] == "invalid"
    ]
    assert len(invalid_messages) >= 1
    assert any("no longer accepts pi" in msg for msg in invalid_messages)

    assert model.GroupMember.query.get((group_id, unrelated_member)) is None
    assert model.PrimaryGroupMember.query.get((group_id, pi_owner)) is not None
    assert model.PrimaryGroupMember.query.get((group_id, stable_member)) is None


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_updates_group_pi_with_explicit_operation(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    old_pi = f"old-pi-{uuid.uuid4().hex[:6]}"
    new_pi = f"new-pi-{uuid.uuid4().hex[:6]}"
    ensure_active_user(old_pi, f"{old_pi}@example.com", old_pi)
    ensure_active_user(new_pi, f"{new_pi}@example.com", new_pi)
    set_group_membership(group_id, old_pi, approved=True, pi=True)
    set_group_membership(group_id, new_pi, approved=True, pi=False)

    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))
    response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "group",
            "entity": group_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "group.pi.set",
                        "group": group_id,
                        "user": new_pi,
                        "expected_current_pi": old_pi,
                    }
                ]
            ),
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is True
    assert payload["applied"] == 1
    assert model.PrimaryGroupMember.query.get((group_id, old_pi)) is None
    assert model.PrimaryGroupMember.query.get((group_id, new_pi)) is not None


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_returns_conflict_for_stale_group_pi_expected_state(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    old_pi = f"old-pi-{uuid.uuid4().hex[:6]}"
    new_pi = f"new-pi-{uuid.uuid4().hex[:6]}"
    ensure_active_user(old_pi, f"{old_pi}@example.com", old_pi)
    ensure_active_user(new_pi, f"{new_pi}@example.com", new_pi)
    set_group_membership(group_id, old_pi, approved=True, pi=True)
    set_group_membership(group_id, new_pi, approved=True, pi=False)

    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))
    response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "group",
            "entity": group_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "group.pi.set",
                        "group": group_id,
                        "user": new_pi,
                        "expected_current_pi": "someone-else",
                    }
                ]
            ),
        },
    )

    assert response.status_code == 409
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is False
    conflict_rows = [row for row in payload["results"] if row["status"] == "conflict"]
    assert len(conflict_rows) == 1
    assert model.PrimaryGroupMember.query.get((group_id, old_pi)) is not None
    assert model.PrimaryGroupMember.query.get((group_id, new_pi)) is None


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_returns_conflict_for_stale_membership_expected_state(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    user_id = f"mem-{uuid.uuid4().hex[:6]}"
    ensure_active_user(user_id, f"{user_id}@example.com", user_id)
    set_group_membership(group_id, user_id, approved=True, pi=False)

    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))
    response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "group",
            "entity": group_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "group.membership.set",
                        "group": group_id,
                        "user": user_id,
                        "member": True,
                        "approved": False,
                        "expected_member": True,
                        "expected_approved": False,
                    }
                ]
            ),
        },
    )

    assert response.status_code == 409
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is False
    assert payload["applied"] == 0
    conflict_rows = [row for row in payload["results"] if row["status"] == "conflict"]
    assert len(conflict_rows) == 1
    row = model.GroupMember.query.get((group_id, user_id))
    assert row is not None
    assert row.approved is not None


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_rolls_back_all_changes_on_conflict(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    target_member = f"target-{uuid.uuid4().hex[:6]}"
    stale_member = f"stale-{uuid.uuid4().hex[:6]}"
    ensure_active_user(target_member, f"{target_member}@example.com", target_member)
    ensure_active_user(stale_member, f"{stale_member}@example.com", stale_member)
    set_group_membership(group_id, stale_member, approved=True, pi=False)

    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))
    response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "group",
            "entity": group_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "group.membership.set",
                        "group": group_id,
                        "user": target_member,
                        "member": True,
                        "approved": True,
                        "expected_member": False,
                        "expected_approved": False,
                    },
                    {
                        "kind": "group.membership.set",
                        "group": group_id,
                        "user": stale_member,
                        "member": True,
                        "approved": False,
                        "expected_member": True,
                        "expected_approved": False,
                    },
                ]
            ),
        },
    )

    assert response.status_code == 409
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is False
    rolled_back_rows = [
        row for row in payload["results"] if row["status"] == "rolled_back"
    ]
    assert len(rolled_back_rows) == 1
    assert model.GroupMember.query.get((group_id, target_member)) is None


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_applies_group_meta_rows_without_cross_row_overwrite(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    group_row = model.Group.query.get(group_id)
    assert group_row is not None
    original_label = group_row.label
    original_description = group_row.description
    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))

    response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "scope": "group",
            "entity": group_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "group.meta.set",
                        "group": group_id,
                        "label": "Meta Group One",
                        "expected_label": original_label,
                    },
                    {
                        "kind": "group.meta.set",
                        "group": group_id,
                        "description": "Updated metadata description",
                        "expected_description": original_description,
                    },
                ]
            ),
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is True
    assert payload["applied"] == 2
    updated_group = model.Group.query.get(group_id)
    assert updated_group is not None
    assert updated_group.label == "Meta Group One"
    assert updated_group.description == "Updated metadata description"


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_returns_conflict_for_stale_group_meta_expected_state(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    group_row = model.Group.query.get(group_id)
    assert group_row is not None
    original_label = group_row.label
    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))

    response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "scope": "group",
            "entity": group_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "group.meta.set",
                        "group": group_id,
                        "label": "New Group Label",
                        "expected_label": "stale-label",
                    }
                ]
            ),
        },
    )

    assert response.status_code == 409
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is False
    conflict_rows = [row for row in payload["results"] if row["status"] == "conflict"]
    assert len(conflict_rows) == 1
    fresh_group = model.Group.query.get(group_id)
    assert fresh_group is not None
    assert fresh_group.label == original_label


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_returns_conflict_for_stale_device_group_expected_state(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    device_id = seeded_scanner_id()
    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))

    response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "scope": "group",
            "entity": group_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "device.group.set",
                        "group": group_id,
                        "device": device_id,
                        "linked": True,
                        "expected_linked": True,
                    }
                ]
            ),
        },
    )

    assert response.status_code == 409
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is False
    conflict_rows = [row for row in payload["results"] if row["status"] == "conflict"]
    assert len(conflict_rows) == 1
    assert model.DeviceGroup.query.get((device_id, group_id)) is None


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_returns_conflict_for_stale_user_device_expected_state(
    route_client, route_app_context
):
    ensure_admin_user()
    ensure_group(
        "DEV",
        label="DEV",
        description="Development Group",
        color="#222222",
        active=True,
        has_membership=True,
    )
    set_admin_session(route_client)

    user_id = f"staleud{uuid.uuid4().hex[:5]}"
    ensure_active_user(user_id, f"{user_id}@example.com", user_id)
    set_group_membership("DEV", user_id, approved=True, pi=False)
    device_id, _ = create_device()
    model.db.session.add(
        model.UserDevice(
            user=user_id,
            device=device_id,
            templates=True,
            slot=False,
            tech=False,
            medical=False,
            training=False,
        )
    )
    model.db.session.flush()
    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))

    response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "scope": "user",
            "entity": user_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "user.device.set",
                        "user": user_id,
                        "device": device_id,
                        "templates": True,
                        "slot": False,
                        "tech": False,
                        "medical": False,
                        "training": False,
                        "expected_templates": False,
                        "expected_slot": False,
                        "expected_tech": False,
                        "expected_medical": False,
                        "expected_training": False,
                    }
                ]
            ),
        },
    )

    assert response.status_code == 409
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is False
    conflict_rows = [row for row in payload["results"] if row["status"] == "conflict"]
    assert len(conflict_rows) == 1
    row = model.UserDevice.query.get((user_id, device_id))
    assert row is not None
    assert row.templates is True


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_returns_conflict_for_stale_user_active_expected_state(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)

    user_id = f"staleactive{uuid.uuid4().hex[:5]}"
    ensure_active_user(user_id, f"{user_id}@example.com", user_id)
    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))

    response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "scope": "user",
            "entity": user_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "user.active.set",
                        "user": user_id,
                        "active": False,
                        "expected_active": False,
                    }
                ]
            ),
        },
    )

    assert response.status_code == 409
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is False
    conflict_rows = [row for row in payload["results"] if row["status"] == "conflict"]
    assert len(conflict_rows) == 1
    user_row = model.User.query.get(user_id)
    assert user_row is not None
    assert user_row.active is True


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_returns_conflict_for_stale_device_meta_expected_state(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)

    device_id, _ = create_device()
    device_row = model.Device.query.get(device_id)
    assert device_row is not None
    original_label = device_row.label
    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))

    response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "scope": "device",
            "entity": device_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "device.meta.set",
                        "device": device_id,
                        "label": "Updated Device Label",
                        "expected_label": "stale-device-label",
                    }
                ]
            ),
        },
    )

    assert response.status_code == 409
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is False
    conflict_rows = [row for row in payload["results"] if row["status"] == "conflict"]
    assert len(conflict_rows) == 1
    fresh_device = model.Device.query.get(device_id)
    assert fresh_device is not None
    assert fresh_device.label == original_label


@pytest.mark.covers_route("/json/v1/rbac/explorer", "GET")
def test_rbac_explorer_api_returns_user_scope_payload_for_admin(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    response = route_client.get("/json/v1/rbac/explorer?scope=user&entity=test-admin")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["scope"] == "user"
    assert payload["selected"] == "test-admin"
    assert isinstance(payload["scopes"], list)
    assert isinstance(payload["entities"], list)
    detail = payload["detail"]
    assert "summary" in detail
    assert "graph" in detail
    assert "matrices" in detail
    assert isinstance(detail["matrices"], list)


def test_rbac_explorer_api_returns_guided_mutations(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    response = route_client.get(f"/json/v1/rbac/explorer?scope=group&entity={group_id}")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    matrices = payload["detail"].get("matrices")
    assert isinstance(matrices, list)
    matrix_by_id = {matrix.get("id"): matrix for matrix in matrices}
    assert "group-metadata-matrix" in matrix_by_id
    metadata = matrix_by_id["group-metadata-matrix"]
    assert metadata.get("layout") == "keyvalue"
    assert any(row.get("field") == "active" for row in metadata.get("rows", []))
    assert payload["detail"].get("links") == []


def test_rbac_explorer_device_permissions_matrix_exposes_quick_add(route_client):
    ensure_admin_user()
    ensure_group(
        "DEV",
        label="DEV",
        description="Development Group",
        color="#222222",
        active=True,
        has_membership=True,
    )
    set_group_membership("DEV", "test-admin", approved=True, pi=False)
    set_admin_session(route_client)

    device_id, _ = create_device()
    response = route_client.get(
        f"/json/v1/rbac/explorer?scope=device&entity={device_id}"
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["detail"].get("links") == []
    matrices = payload["detail"].get("matrices", [])
    matrix_by_id = {matrix.get("id"): matrix for matrix in matrices}
    assert "device-user-permissions-matrix" in matrix_by_id
    quick_add = matrix_by_id["device-user-permissions-matrix"].get("quick_add")
    assert isinstance(quick_add, dict)
    assert quick_add.get("label") == "+ add DEV user"
    operation = quick_add.get("operation")
    assert isinstance(operation, dict)
    assert operation.get("kind") == "user.device.set"
    assert operation.get("device") == device_id
    assert operation.get("expected_templates") is False
    assert operation.get("expected_slot") is False
    assert operation.get("expected_tech") is False
    assert operation.get("expected_medical") is False
    assert operation.get("expected_training") is False


def test_rbac_explorer_api_filters_inactive_entities_by_default(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    inactive_group_id = f"INACT{uuid.uuid4().hex[:4]}".upper()
    ensure_group(
        inactive_group_id,
        label=f"Inactive {inactive_group_id}",
        description=f"Inactive {inactive_group_id}",
        active=False,
    )

    inactive_device_id, _ = create_device()
    device_row = model.Device.query.get(inactive_device_id)
    assert device_row is not None
    device_row.active = False

    inactive_user_id = f"inusr{uuid.uuid4().hex[:5]}"
    ensure_active_user(
        inactive_user_id, f"{inactive_user_id}@example.com", inactive_user_id
    )
    user_row = model.User.query.get(inactive_user_id)
    assert user_row is not None
    user_row.active = False
    model.db.session.commit()

    default_response = route_client.get("/json/v1/rbac/explorer?scope=group&detail=0")
    assert default_response.status_code == 200
    default_payload = default_response.get_json()
    assert default_payload is not None
    assert default_payload["include_inactive"] is False
    default_ids = {entry["id"] for entry in default_payload["entities"]}
    assert inactive_group_id not in default_ids

    inclusive_response = route_client.get(
        "/json/v1/rbac/explorer?scope=group&detail=0&active=1"
    )
    assert inclusive_response.status_code == 200
    inclusive_payload = inclusive_response.get_json()
    assert inclusive_payload is not None
    assert inclusive_payload["include_inactive"] is True
    inclusive_ids = {entry["id"] for entry in inclusive_payload["entities"]}
    assert inactive_group_id in inclusive_ids

    default_devices_response = route_client.get(
        "/json/v1/rbac/explorer?scope=device&detail=0"
    )
    assert default_devices_response.status_code == 200
    default_devices_payload = default_devices_response.get_json()
    assert default_devices_payload is not None
    default_device_ids = {entry["id"] for entry in default_devices_payload["entities"]}
    assert inactive_device_id not in default_device_ids

    inclusive_devices_response = route_client.get(
        "/json/v1/rbac/explorer?scope=device&detail=0&active=1"
    )
    assert inclusive_devices_response.status_code == 200
    inclusive_devices_payload = inclusive_devices_response.get_json()
    assert inclusive_devices_payload is not None
    inclusive_device_ids = {
        entry["id"] for entry in inclusive_devices_payload["entities"]
    }
    assert inactive_device_id in inclusive_device_ids

    default_users_response = route_client.get(
        "/json/v1/rbac/explorer?scope=user&detail=0"
    )
    assert default_users_response.status_code == 200
    default_users_payload = default_users_response.get_json()
    assert default_users_payload is not None
    default_user_ids = {entry["id"] for entry in default_users_payload["entities"]}
    assert inactive_user_id not in default_user_ids

    inclusive_users_response = route_client.get(
        "/json/v1/rbac/explorer?scope=user&detail=0&active=1"
    )
    assert inclusive_users_response.status_code == 200
    inclusive_users_payload = inclusive_users_response.get_json()
    assert inclusive_users_payload is not None
    inclusive_user_ids = {entry["id"] for entry in inclusive_users_payload["entities"]}
    assert inactive_user_id in inclusive_user_ids

    hidden_detail_response = route_client.get(
        f"/json/v1/rbac/explorer?scope=group&entity={inactive_group_id}&entities=0&detail=1"
    )
    assert hidden_detail_response.status_code == 200
    hidden_detail_payload = hidden_detail_response.get_json()
    assert hidden_detail_payload is not None
    assert hidden_detail_payload["selected"] == ""
    assert hidden_detail_payload["detail"]["summary"]["title"] == "No groups found"

    visible_detail_response = route_client.get(
        f"/json/v1/rbac/explorer?scope=group&entity={inactive_group_id}&entities=0&detail=1&active=1"
    )
    assert visible_detail_response.status_code == 200
    visible_detail_payload = visible_detail_response.get_json()
    assert visible_detail_payload is not None
    assert visible_detail_payload["selected"] == inactive_group_id


def test_rbac_explorer_api_supports_detail_without_entity_list(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    response = route_client.get(
        "/json/v1/rbac/explorer?scope=user&entity=test-admin&entities=0&detail=1"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["scope"] == "user"
    assert payload["selected"] == "test-admin"
    assert payload["entities"] == []
    assert payload["entities_included"] is False
    assert payload["detail"]["summary"]["subtitle"] == "user"


def test_rbac_explorer_api_forbidden_for_non_admin(route_client):
    user_id = "normal-user-rbac-api"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Normal User API")

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Normal User API",
    )

    response = route_client.get("/json/v1/rbac/explorer?scope=group")

    assert response.status_code == 403


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_removes_device_group_link_for_admin(
    route_client, route_app_context, monkeypatch
):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    device_id = seeded_scanner_id()
    model.db.session.add(model.DeviceGroup(device=device_id, group=group_id))
    model.db.session.flush()

    events = _capture_rbac_events(monkeypatch)

    missing_csrf = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "action": "device.group.remove",
            "device": device_id,
            "group": group_id,
        },
    )
    assert missing_csrf.status_code == 400
    assert model.DeviceGroup.query.get((device_id, group_id)) is not None

    get_response = route_client.get("/rbac")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "group",
            "entity": group_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "device.group.set",
                        "device": device_id,
                        "group": group_id,
                        "linked": False,
                    }
                ]
            ),
        },
        headers={"X-Forwarded-For": "203.0.113.9"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is True
    assert payload["applied"] == 1
    assert model.DeviceGroup.query.get((device_id, group_id)) is None
    assert len(events) == 1
    action, actor, where, how, what, source_ip = events[0]
    assert action == "device.group.remove"
    assert actor == "test-admin"
    assert where == f"/device/{device_id}/groups"
    assert how == "rbac-explorer-batch"
    assert f"device={device_id}" in what
    assert f"group={group_id}" in what
    assert source_ip == "203.0.113.9"


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_is_atomic_on_validation_failure(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    device_id = seeded_scanner_id()
    user_id = f"rbacbatch{uuid.uuid4().hex[:5]}"
    ensure_active_user(user_id, f"{user_id}@example.com", user_id)

    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))
    operations = [
        {
            "kind": "device.group.set",
            "group": group_id,
            "device": device_id,
            "linked": True,
        },
        {
            "kind": "user.device.set",
            "user": user_id,
            "device": device_id,
            "templates": True,
            "slot": False,
            "tech": False,
            "medical": False,
            "training": False,
        },
    ]
    response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "group",
            "entity": group_id,
            "operations": json.dumps(operations),
        },
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is False
    assert payload["atomic"] is True
    assert payload["applied"] == 0
    assert model.DeviceGroup.query.get((device_id, group_id)) is None
    invalid = [row for row in payload["results"] if row["status"] == "invalid"]
    assert len(invalid) == 1
    assert "must target selected group" in invalid[0]["message"]


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_api_updates_user_device_permissions_and_audit_feed(
    route_client, route_app_context
):
    ensure_admin_user()
    ensure_group(
        "DEV",
        label="DEV",
        description="Development Group",
        color="#222222",
        active=True,
        has_membership=True,
    )

    user_id = f"rbacdev{uuid.uuid4().hex[:5]}"
    ensure_active_user(user_id, f"{user_id}@example.com", user_id)
    set_group_membership("DEV", user_id, approved=True, pi=False)
    device_id, _ = create_device()

    set_admin_session(route_client)
    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))
    operations = [
        {
            "kind": "user.device.set",
            "user": user_id,
            "device": device_id,
            "templates": True,
            "slot": False,
            "tech": False,
            "medical": False,
            "training": True,
        }
    ]

    post_response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "user",
            "entity": user_id,
            "operations": json.dumps(operations),
        },
        headers={"X-Forwarded-For": "198.51.100.7"},
    )
    assert post_response.status_code == 200
    payload = post_response.get_json()
    assert payload is not None
    assert payload["ok"] is True
    assert payload["atomic"] is True
    assert payload["applied"] == 1

    row = model.UserDevice.query.get((user_id, device_id))
    assert row is not None
    assert row.templates is True
    assert row.training is True
    assert row.slot is False

    audit_response = route_client.get(
        f"/json/v1/rbac/audit?scope=user&entity={user_id}&limit=20"
    )
    assert audit_response.status_code == 200
    audit_payload = audit_response.get_json()
    assert audit_payload is not None
    assert audit_payload["scope"] == "user"
    assert audit_payload["selected"] == user_id
    matching = [
        event
        for event in audit_payload["events"]
        if event["action"] == "user.device.update"
        and event["where"] == f"/device/{device_id}/users/{user_id}"
    ]
    assert len(matching) >= 1
    assert matching[0]["how"] == "rbac-explorer-batch"
    assert matching[0]["ip"] == "198.51.100.7"


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_updates_entity_active_state(route_client, route_app_context):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    device_id, _ = create_device()
    user_id = f"rbacactive{uuid.uuid4().hex[:4]}"
    ensure_active_user(user_id, f"{user_id}@example.com", user_id)
    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))

    response_group = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "group",
            "entity": group_id,
            "operations": json.dumps(
                [{"kind": "group.active.set", "group": group_id, "active": False}]
            ),
        },
    )
    assert response_group.status_code == 200
    payload_group = response_group.get_json()
    assert payload_group is not None
    assert payload_group["ok"] is True
    assert payload_group["applied"] == 1
    group = model.Group.query.get(group_id)
    assert group is not None
    assert group.active is False

    response_device = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "device",
            "entity": device_id,
            "operations": json.dumps(
                [{"kind": "device.active.set", "device": device_id, "active": False}]
            ),
        },
    )
    assert response_device.status_code == 200
    payload_device = response_device.get_json()
    assert payload_device is not None
    assert payload_device["ok"] is True
    assert payload_device["applied"] == 1
    device = model.Device.query.get(device_id)
    assert device is not None
    assert device.active is False

    response_user = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "user",
            "entity": user_id,
            "operations": json.dumps(
                [{"kind": "user.active.set", "user": user_id, "active": False}]
            ),
        },
    )
    assert response_user.status_code == 200
    payload_user = response_user.get_json()
    assert payload_user is not None
    assert payload_user["ok"] is True
    assert payload_user["applied"] == 1
    user = model.User.query.get(user_id)
    assert user is not None
    assert user.active is False

    response_special_group = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "group",
            "entity": "DEV",
            "operations": json.dumps(
                [{"kind": "group.active.set", "group": "DEV", "active": False}]
            ),
        },
    )
    assert response_special_group.status_code == 400
    payload_special_group = response_special_group.get_json()
    assert payload_special_group is not None
    assert payload_special_group["ok"] is False
    invalid_messages = [
        row["message"]
        for row in payload_special_group["results"]
        if row["status"] == "invalid"
    ]
    assert len(invalid_messages) == 1
    assert "special group cannot be deactivated" in invalid_messages[0]


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_updates_group_and_device_metadata(
    route_client, route_app_context, monkeypatch
):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = create_group()
    device_id, _ = create_device()
    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))
    events = _capture_rbac_events(monkeypatch)

    group_update = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "group",
            "entity": group_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "group.meta.set",
                        "group": group_id,
                        "label": "Meta Group",
                        "description": "Metadata Updated Group",
                        "addr": "meta-group@example.com",
                        "link": "https://example.org/group-meta",
                        "color": "#123456",
                        "inst": "",
                        "active": False,
                    }
                ]
            ),
        },
        headers={"X-Forwarded-For": "198.51.100.31"},
    )
    assert group_update.status_code == 200
    group_payload = group_update.get_json()
    assert group_payload is not None
    assert group_payload["ok"] is True
    assert group_payload["applied"] == 1
    group = model.Group.query.get(group_id)
    assert group is not None
    assert group.label == "Meta Group"
    assert group.description == "Metadata Updated Group"
    assert group.addr == "meta-group@example.com"
    assert group.link == "https://example.org/group-meta"
    assert group.color == "#123456"
    assert group.inst is None
    assert group.active is False

    device_update = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "device",
            "entity": device_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "device.meta.set",
                        "device": device_id,
                        "label": "Meta Device",
                        "description": "Updated device description",
                        "addr": "device@example.com",
                        "tech_addr": "tech@example.com",
                        "med_addr": "med@example.com",
                        "train_addr": "train@example.com",
                        "active": False,
                    }
                ]
            ),
        },
        headers={"X-Forwarded-For": "198.51.100.31"},
    )
    assert device_update.status_code == 200
    device_payload = device_update.get_json()
    assert device_payload is not None
    assert device_payload["ok"] is True
    assert device_payload["applied"] == 1
    device = model.Device.query.get(device_id)
    assert device is not None
    assert device.label == "Meta Device"
    assert device.description == "Updated device description"
    assert device.addr == "device@example.com"
    assert device.tech_addr == "tech@example.com"
    assert device.med_addr == "med@example.com"
    assert device.train_addr == "train@example.com"
    assert device.active is False

    assert any(
        action == "group.update"
        and where == f"/group/{group_id}/edit"
        and how == "rbac-explorer-batch"
        and source_ip == "198.51.100.31"
        for action, _actor, where, how, _what, source_ip in events
    )
    assert any(
        action == "device.update"
        and where == f"/device/{device_id}/edit"
        and how == "rbac-explorer-batch"
        and source_ip == "198.51.100.31"
        for action, _actor, where, how, _what, source_ip in events
    )


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_rejects_invalid_group_link_url(
    route_client, route_app_context
):
    ensure_admin_user()
    set_admin_session(route_client)
    group_id = create_group()
    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))

    response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "group",
            "entity": group_id,
            "operations": json.dumps(
                [
                    {
                        "kind": "group.meta.set",
                        "group": group_id,
                        "label": "Meta Group",
                        "description": "Meta Group",
                        "addr": "",
                        "link": "not-a-url",
                        "color": "#123456",
                        "inst": "",
                    }
                ]
            ),
        },
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload is not None
    assert payload["ok"] is False
    invalid_messages = [
        row["message"] for row in payload["results"] if row["status"] == "invalid"
    ]
    assert len(invalid_messages) == 1
    assert "invalid URL for link" in invalid_messages[0]


@pytest.mark.covers_route("/json/v1/rbac/mutate", "POST")
def test_rbac_mutate_batch_creates_group_and_device(
    route_client, route_app_context, monkeypatch
):
    ensure_admin_user()
    set_admin_session(route_client)
    events = _capture_rbac_events(monkeypatch)

    pi_user = f"rbacpi{uuid.uuid4().hex[:5]}"
    ensure_active_user(pi_user, f"{pi_user}@example.com", pi_user)
    csrf_token = extract_csrf_token(route_client.get("/rbac").get_data(as_text=True))
    new_group = f"RB{uuid.uuid4().hex[:8]}".upper()
    new_device = f"d{uuid.uuid4().hex[:4]}"

    group_response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "group",
            "entity": "__create__",
            "operations": json.dumps(
                [
                    {
                        "kind": "group.create",
                        "group": new_group,
                        "label": f"Label {new_group}",
                        "description": f"Description {new_group}",
                        "pi": pi_user,
                        "addr": "",
                        "link": "",
                        "color": "#0f4c81",
                        "inst": "",
                        "active": True,
                    }
                ]
            ),
        },
        headers={"X-Forwarded-For": "198.51.100.88"},
    )
    assert group_response.status_code == 200
    group_payload = group_response.get_json()
    assert group_payload is not None
    assert group_payload["ok"] is True
    created_group = model.Group.query.get(new_group)
    assert created_group is not None
    assert created_group.label == f"Label {new_group}"
    membership = model.GroupMember.query.get((new_group, pi_user))
    assert membership is not None
    pi = model.PrimaryGroupMember.query.get((new_group, pi_user))
    assert pi is not None

    device_response = route_client.post(
        "/json/v1/rbac/mutate",
        data={
            "csrf_token": csrf_token,
            "mode": "batch",
            "scope": "device",
            "entity": "__create__",
            "operations": json.dumps(
                [
                    {
                        "kind": "device.create",
                        "device": new_device,
                        "label": f"Label {new_device}",
                        "description": "Created from RBAC",
                        "addr": "device@example.com",
                        "tech_addr": "",
                        "med_addr": "",
                        "train_addr": "",
                        "active": True,
                    }
                ]
            ),
        },
        headers={"X-Forwarded-For": "198.51.100.88"},
    )
    assert device_response.status_code == 200
    device_payload = device_response.get_json()
    assert device_payload is not None
    assert device_payload["ok"] is True
    created_device = model.Device.query.get(new_device)
    assert created_device is not None
    assert created_device.label == f"Label {new_device}"

    assert any(
        action == "group.create"
        and where == f"/group/{new_group}"
        and how == "rbac-explorer-batch"
        and source_ip == "198.51.100.88"
        for action, _actor, where, how, _what, source_ip in events
    )
    assert any(
        action == "device.create"
        and where == f"/device/{new_device}"
        and how == "rbac-explorer-batch"
        and source_ip == "198.51.100.88"
        for action, _actor, where, how, _what, source_ip in events
    )


@pytest.mark.covers_route("/app/issues", "GET")
def test_app_issues_page_renders_for_admin(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    response = route_client.get("/app/issues")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Potential issues" in body
    assert "RBAC audit log" in body


def test_app_issues_page_shows_missing_pi_issue(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    group_id = f"G{uuid.uuid4().hex[:6]}"
    ensure_group(
        group_id,
        label=f"Group {group_id}",
        description=f"Group {group_id}",
        active=True,
        has_membership=True,
    )

    response = route_client.get("/app/issues")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert f"Group {group_id} has no active PI configured" in body


def test_app_issues_page_forbidden_for_non_admin(route_client):
    user_id = "normal-user-rbac-audit-page"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Normal User Audit Page")

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Normal User Audit Page",
    )

    response = route_client.get("/app/issues")
    assert response.status_code == 403


def test_legacy_rbac_audit_route_is_not_found(route_client):
    ensure_admin_user()
    set_admin_session(route_client)

    response = route_client.get("/rbac/audit?scope=group&entity=DEV&limit=20")
    assert response.status_code == 404


@pytest.mark.covers_route("/json/v1/rbac/audit", "GET")
def test_rbac_audit_api_forbidden_for_non_admin(route_client):
    user_id = "normal-user-rbac-audit"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Normal User Audit")

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Normal User Audit",
    )

    response = route_client.get("/json/v1/rbac/audit?scope=group")
    assert response.status_code == 403
