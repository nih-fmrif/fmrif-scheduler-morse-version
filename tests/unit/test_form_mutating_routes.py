import uuid

import pytest
from route_seed import (
    ensure_active_user,
    ensure_group,
    extract_csrf_token,
    set_group_membership,
    set_session_user,
)

import scheduler.message as scheduler_message
from scheduler import logic, model


def _capture_rbac_events(monkeypatch) -> list[tuple[str, str, str, str, str]]:
    events: list[tuple[str, str, str, str, str]] = []

    def capture(action: str, actor: str, where: str, how: str, what: str) -> None:
        events.append((action, actor, where, how, what))

    monkeypatch.setattr(logic, "log_rbac_audit_event", capture)
    return events


pytestmark = pytest.mark.route


@pytest.mark.covers_route("/mailing-lists", "POST")
def test_mailing_lists_post_submits_selected_list(monkeypatch, route_app, route_client):
    user_id = f"list-user-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@nih.gov"
    ensure_active_user(user_id, email, "List User")

    sent = []
    monkeypatch.setattr(
        scheduler_message,
        "send",
        lambda to, subj, msg, sender=None: sent.append((to, subj, msg, sender)) or True,
    )

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="List User",
    )

    get_response = route_client.get("/mailing-lists")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    post_response = route_client.post(
        "/mailing-lists",
        data={
            "csrf_token": csrf_token,
            "addr": email,
            "name": "List User",
            "action": "sub",
            "lists-ml-0": "y",
        },
        follow_redirects=False,
    )

    assert post_response.status_code == 302
    assert post_response.headers["Location"].endswith("/")
    assert len(sent) == 1
    to, subj, msg, sender = sent[0]
    assert to == route_app.config["nih_listserv"]
    assert subj == "Automated list change"
    assert "subscribe" in msg
    assert sender == email


@pytest.mark.covers_route("/join", "POST")
def test_join_post_creates_pending_membership_request(
    monkeypatch, route_client, route_app_context
):
    requester_id = f"join-user-{uuid.uuid4().hex[:6]}"
    requester_email = f"{requester_id}@example.com"
    ensure_active_user(requester_id, requester_email, "Join Requester")

    group_id = f"G{uuid.uuid4().hex[:6]}"
    ensure_group(
        group_id,
        label=f"Group {group_id}",
        description=f"Group {group_id}",
        color="#336699",
        active=True,
        has_membership=True,
    )

    pi_id = f"pi-{uuid.uuid4().hex[:6]}"
    pi_email = f"{pi_id}@example.com"
    ensure_active_user(pi_id, pi_email, "Group PI")
    set_group_membership(group_id, pi_id, approved=True, pi=True)

    sent = []
    monkeypatch.setattr(
        scheduler_message,
        "send",
        lambda to, subj, msg, sender=None: sent.append((to, subj, msg, sender)) or True,
    )

    set_session_user(
        route_client,
        username=requester_id,
        email=requester_email,
        display_name="Join Requester",
    )

    get_response = route_client.get("/join")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    events = _capture_rbac_events(monkeypatch)

    post_response = route_client.post(
        "/join",
        data={
            "csrf_token": csrf_token,
            "group": group_id,
        },
        follow_redirects=False,
    )

    assert post_response.status_code == 302
    assert post_response.headers["Location"].endswith("/")
    req = model.GroupMember.query.get((group_id, requester_id))
    assert req is not None
    assert req.approved is None
    assert len(sent) == 1
    assert len(events) == 1
    action, actor, where, how, what = events[0]
    assert action == "group.join.request"
    assert actor == requester_id
    assert where == f"/join/{group_id}"
    assert how == "email"
    assert f"group={group_id}" in what


@pytest.mark.covers_route("/join", "POST")
def test_join_post_survives_mail_transport_failure(
    monkeypatch, route_client, route_app_context
):
    requester_id = f"join-user-{uuid.uuid4().hex[:6]}"
    requester_email = f"{requester_id}@example.com"
    ensure_active_user(requester_id, requester_email, "Join Requester")

    group_id = f"G{uuid.uuid4().hex[:6]}"
    ensure_group(
        group_id,
        label=f"Group {group_id}",
        description=f"Group {group_id}",
        color="#336699",
        active=True,
        has_membership=True,
    )

    pi_id = f"pi-{uuid.uuid4().hex[:6]}"
    pi_email = f"{pi_id}@example.com"
    ensure_active_user(pi_id, pi_email, "Group PI")
    set_group_membership(group_id, pi_id, approved=True, pi=True)

    monkeypatch.setattr(
        scheduler_message.mailer,
        "send",
        lambda _m: (_ for _ in ()).throw(ConnectionRefusedError("refused")),
    )

    set_session_user(
        route_client,
        username=requester_id,
        email=requester_email,
        display_name="Join Requester",
    )

    get_response = route_client.get("/join")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    events = _capture_rbac_events(monkeypatch)

    post_response = route_client.post(
        "/join",
        data={
            "csrf_token": csrf_token,
            "group": group_id,
        },
        follow_redirects=False,
    )

    assert post_response.status_code == 302
    assert post_response.headers["Location"].endswith("/")
    req = model.GroupMember.query.get((group_id, requester_id))
    assert req is not None
    assert req.approved is None
    assert len(events) == 1
    action, actor, where, how, what = events[0]
    assert action == "group.join.request"
    assert actor == requester_id
    assert where == f"/join/{group_id}"
    assert how == "email"
    assert f"group={group_id}" in what


@pytest.mark.covers_route("/join", "POST")
def test_join_post_without_group_pi_does_not_crash(
    monkeypatch, route_client, route_app_context
):
    requester_id = f"join-user-{uuid.uuid4().hex[:6]}"
    requester_email = f"{requester_id}@example.com"
    ensure_active_user(requester_id, requester_email, "Join Requester")

    group_id = f"G{uuid.uuid4().hex[:6]}"
    ensure_group(
        group_id,
        label=f"Group {group_id}",
        description=f"Group {group_id}",
        color="#336699",
        active=True,
        has_membership=True,
    )

    sent = []
    monkeypatch.setattr(
        scheduler_message,
        "send",
        lambda to, subj, msg, sender=None: sent.append((to, subj, msg, sender)) or True,
    )

    set_session_user(
        route_client,
        username=requester_id,
        email=requester_email,
        display_name="Join Requester",
    )

    get_response = route_client.get("/join")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    events = _capture_rbac_events(monkeypatch)

    post_response = route_client.post(
        "/join",
        data={
            "csrf_token": csrf_token,
            "group": group_id,
        },
        follow_redirects=False,
    )

    assert post_response.status_code == 302
    assert post_response.headers["Location"].endswith("/")
    req = model.GroupMember.query.get((group_id, requester_id))
    assert req is not None
    assert req.approved is None
    assert len(sent) == 0
    assert len(events) == 1
    action, actor, where, how, what = events[0]
    assert action == "group.join.request"
    assert actor == requester_id
    assert where == f"/join/{group_id}"
    assert how == "email"
    assert f"group={group_id}" in what


@pytest.mark.covers_route("/join/tech", "POST")
def test_join_tech_post_records_technologist(
    monkeypatch, route_client, route_app_context
):
    user_id = f"tech-user-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Tech User")

    ensure_group(
        "DEV",
        label="DEV",
        description="Development Group",
        color="#222222",
        active=True,
        has_membership=True,
    )
    set_group_membership("DEV", user_id, approved=True, pi=False)

    dev_pi_id = f"dev-pi-{uuid.uuid4().hex[:6]}"
    dev_pi_email = f"{dev_pi_id}@example.com"
    ensure_active_user(dev_pi_id, dev_pi_email, "Dev PI")
    set_group_membership("DEV", dev_pi_id, approved=True, pi=True)

    sent = []
    monkeypatch.setattr(
        scheduler_message,
        "send",
        lambda to, subj, msg, sender=None: sent.append((to, subj, msg, sender)) or True,
    )

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Tech User",
    )

    get_response = route_client.get("/join/tech")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    events = _capture_rbac_events(monkeypatch)

    post_response = route_client.post(
        "/join/tech",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )

    assert post_response.status_code == 302
    assert post_response.headers["Location"].endswith("/")
    assert model.Technologist.query.get(user_id) is not None
    assert len(sent) == 1
    assert len(events) == 1
    action, actor, where, how, what = events[0]
    assert action == "group.join.tech"
    assert actor == user_id
    assert where == "/join/tech"
    assert how == "email"
    assert f"user={user_id}" in what


@pytest.mark.covers_route("/join/tech", "POST")
def test_join_tech_post_without_dev_pi_does_not_crash(
    monkeypatch, route_client, route_app_context
):
    user_id = f"tech-user-{uuid.uuid4().hex[:6]}"
    email = f"{user_id}@example.com"
    ensure_active_user(user_id, email, "Tech User")

    ensure_group(
        "DEV",
        label="DEV",
        description="Development Group",
        color="#222222",
        active=True,
        has_membership=True,
    )
    set_group_membership("DEV", user_id, approved=True, pi=False)

    model.db.session.execute(
        "delete from primarygroupmember where deptcode = :group_id",
        {"group_id": "DEV"},
    )
    model.db.session.flush()

    sent = []
    monkeypatch.setattr(
        scheduler_message,
        "send",
        lambda to, subj, msg, sender=None: sent.append((to, subj, msg, sender)) or True,
    )

    set_session_user(
        route_client,
        username=user_id,
        email=email,
        display_name="Tech User",
    )

    get_response = route_client.get("/join/tech")
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))

    events = _capture_rbac_events(monkeypatch)

    post_response = route_client.post(
        "/join/tech",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )

    assert post_response.status_code == 302
    assert post_response.headers["Location"].endswith("/")
    assert model.Technologist.query.get(user_id) is not None
    assert len(sent) == 0
    assert len(events) == 1
    action, actor, where, how, what = events[0]
    assert action == "group.join.tech"
    assert actor == user_id
    assert where == "/join/tech"
    assert how == "email"
    assert f"user={user_id}" in what
