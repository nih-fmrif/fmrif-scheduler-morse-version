import datetime
import time
import uuid
from contextlib import contextmanager
from typing import Iterator

import pytest
from mailpit_api import (
    clear_mailpit_messages,
    get_mailpit_message,
    list_mailpit_messages,
    mailpit_available,
    mailpit_config_from_env,
    wait_for_mailpit_message,
)
from route_seed import (
    create_device,
    create_group,
    ensure_active_user,
    ensure_admin_user,
    extract_csrf_token,
    set_admin_session,
    set_group_membership,
    set_session_user,
)
from sqlalchemy import func, select

import scheduler.message as scheduler_message
from scheduler import logic, model

pytestmark = pytest.mark.route


def _require_mailpit():
    cfg = mailpit_config_from_env()
    if cfg is None:
        pytest.skip(
            "Mailpit API config missing. Set MAILPIT__PORT or MAILPIT_API_BASE_URL."
        )
    if not mailpit_available(cfg):
        pytest.skip(f"Mailpit API not reachable at {cfg.api_base_url}.")
    return cfg


@contextmanager
def _route_mail_config(route_app, **mail_updates) -> Iterator[None]:
    original_mail_config = {
        "MAIL_SERVER": route_app.config.get("MAIL_SERVER"),
        "MAIL_PORT": route_app.config.get("MAIL_PORT"),
        "MAIL_USE_TLS": route_app.config.get("MAIL_USE_TLS"),
        "MAIL_USE_SSL": route_app.config.get("MAIL_USE_SSL"),
        "MAIL_SUPPRESS_SEND": route_app.config.get("MAIL_SUPPRESS_SEND"),
        "MAIL_DEFAULT_SENDER": route_app.config.get("MAIL_DEFAULT_SENDER"),
    }
    route_app.config.update(**mail_updates)
    scheduler_message.mailer.init_app(route_app)
    try:
        yield
    finally:
        route_app.config.update(**original_mail_config)
        scheduler_message.mailer.init_app(route_app)


def _wait_for_mail_count(cfg, *, expected: int, timeout_seconds: float = 8.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if len(list_mailpit_messages(cfg)) >= expected:
            return
        time.sleep(0.2)
    raise AssertionError(
        f"Expected at least {expected} Mailpit messages within {timeout_seconds}s."
    )


def _mailpit_message_for_recipient(cfg, recipient: str) -> dict:
    expected = recipient.lower()
    summary = wait_for_mailpit_message(
        cfg,
        lambda row: any(
            str(item.get("Address", "")).lower() == expected
            for item in row.get("To", [])
            if isinstance(item, dict)
        ),
        timeout_seconds=8.0,
        poll_interval_seconds=0.2,
    )
    assert summary is not None
    return get_mailpit_message(cfg, str(summary["ID"]))


def _email_audit_rows(*criteria):
    statement = select(model.EmailAuditLog).order_by(model.EmailAuditLog.id.asc())
    for criterion in criteria:
        statement = statement.where(criterion)
    return model.db.session.scalars(statement).all()


def _support_request_for_entry(entry_id: int, supportkind: int) -> model.SupportRequest:
    return model.db.session.execute(
        select(model.SupportRequest)
        .where(model.SupportRequest.schedid == entry_id)
        .where(model.SupportRequest.supportkind == supportkind)
    ).scalar_one()


def _support_request_count(entry_id: int, supportkind: int) -> int:
    return int(
        model.db.session.scalar(
            select(func.count())
            .select_from(model.SupportRequest)
            .where(model.SupportRequest.schedid == entry_id)
            .where(model.SupportRequest.supportkind == supportkind)
        )
        or 0
    )


def _active_inst_id() -> str:
    inst = model.db.session.scalars(
        select(model.Inst).where(model.Inst.active).order_by(model.Inst.id)
    ).first()
    if inst is None:
        inst = model.Inst(id="I001", label="Test Institute", active=True)
        model.db.session.add(inst)
        model.db.session.flush()
    return inst.id


def _notification_fixture(*, medical_addr: str) -> tuple[str, str, str, int]:
    device_id, device_label = create_device()
    device = model.get(model.Device, device_id)
    assert device is not None
    device.label = device_label
    device.addr = f"{device_id.lower()}-schedule@example.com"
    device.med_addr = medical_addr
    device.train_addr = f"{device_id.lower()}-training@example.com"
    device.tech_addr = f"{device_id.lower()}-tech@example.com"
    model.db.session.add(device)

    group_id = create_group(color="#335577", has_membership=True)
    member_id = f"route-member-{uuid.uuid4().hex[:6]}"
    ensure_active_user(member_id, f"{member_id}@example.com", member_id)
    set_group_membership(group_id, member_id, approved=True, pi=False)
    if model.get(model.DeviceGroup, (device_id, group_id)) is None:
        model.db.session.add(model.DeviceGroup(device=device_id, group=group_id))

    slot_date = datetime.date(2035, 2, 24)
    entry = model.ScheduleEntry(
        device=device_id,
        template=None,
        date=slot_date,
        dow=slot_date.isoweekday() % 7,
        hour=8,
        group=group_id,
        user=member_id,
        orig_group=group_id,
        orig_inst=_active_inst_id(),
        modified_by="test-admin",
    )
    model.db.session.add(entry)
    model.db.session.flush()
    model.db.session.commit()
    return device_id, group_id, member_id, entry.id


def _grant_medical_support(device_id: str, user_id: str) -> None:
    ensure_active_user(user_id, f"{user_id}@example.com", user_id)
    row = model.get(model.UserDevice, (user_id, device_id))
    if row is None:
        row = model.UserDevice(user=user_id, device=device_id)
    row.templates = False
    row.slot = False
    row.tech = False
    row.medical = True
    row.training = False
    model.db.session.add(row)
    model.db.session.flush()


def _set_support_session(client, user_id: str) -> None:
    set_session_user(
        client,
        username=user_id,
        email=f"{user_id}@example.com",
        display_name=user_id,
        groups=[],
    )


def _post_scheduler_payload(
    route_client, device_id: str, slot_date: datetime.date, payload
):
    target = f"/device/{device_id}?start={slot_date.isoformat()}&days=1"
    get_response = route_client.get(target)
    csrf_token = extract_csrf_token(get_response.get_data(as_text=True))
    return route_client.post(
        target,
        json={
            "csrf_token": csrf_token,
            "payload": payload,
        },
        follow_redirects=False,
    )


@pytest.mark.covers_route("/device/<the_device>", "POST")
def test_device_schedule_post_delivers_support_notifications_to_mailpit(
    route_app, route_client, route_app_context
):
    cfg = _require_mailpit()
    ensure_admin_user()
    set_admin_session(route_client)
    device_id, _group_id, _member_id, entry_id = _notification_fixture(
        medical_addr="route-medical@example.com"
    )
    slot_date = datetime.date(2035, 2, 24)

    with _route_mail_config(
        route_app,
        MAIL_SERVER=cfg.smtp_host,
        MAIL_PORT=cfg.smtp_port,
        MAIL_USE_TLS=False,
        MAIL_USE_SSL=False,
        MAIL_SUPPRESS_SEND=False,
    ):
        clear_mailpit_messages(cfg)
        try:
            response = _post_scheduler_payload(
                route_client,
                device_id,
                slot_date,
                {
                    "diffs": [{"id": entry_id, "med": {"requested": True}}],
                    "notify": True,
                },
            )

            assert response.status_code == 200
            payload = response.get_json()
            assert payload is not None
            assert sorted(payload["notifications"], key=lambda note: note["key"]) == [
                {"key": "medical", "msg": "success"},
                {"key": "schedule", "msg": "success"},
            ]
            _wait_for_mail_count(cfg, expected=2)

            schedule_detail = _mailpit_message_for_recipient(
                cfg, f"{device_id.lower()}-schedule@example.com"
            )
            schedule_text = str(schedule_detail.get("Text", ""))
            assert "Support Requests" in schedule_text
            assert "medical" in schedule_text
            assert "new request" in schedule_text

            medical_detail = _mailpit_message_for_recipient(
                cfg, "route-medical@example.com"
            )
            medical_text = str(medical_detail.get("Text", ""))
            assert "new request" in medical_text
            assert "Support Requests" not in medical_text

            audit_rows = _email_audit_rows(
                model.EmailAuditLog.action == "email.scheduler.notification",
                model.EmailAuditLog.details.like(f"%device={device_id}%"),
            )
            assert len(audit_rows) == 2
            assert {row.recipient for row in audit_rows} == {
                f"{device_id.lower()}-schedule@example.com",
                "route-medical@example.com",
            }
            assert all(
                row.status == logic.EMAIL_AUDIT_STATUS_SENT for row in audit_rows
            )
        finally:
            clear_mailpit_messages(cfg)


@pytest.mark.parametrize(
    ("existing_handler", "next_handler", "expected_text"),
    [
        ("", "route-handler-a", "request approved"),
        ("route-handler-a", "route-handler-b", "request reassigned to new handler"),
        ("route-handler-a", "", "request no longer has handler but still open"),
    ],
)
@pytest.mark.covers_route("/device/<the_device>", "POST")
def test_device_schedule_post_formats_medical_handler_state_changes(
    route_app,
    route_client,
    route_app_context,
    existing_handler,
    next_handler,
    expected_text,
):
    cfg = _require_mailpit()
    ensure_admin_user()
    set_admin_session(route_client)
    device_id, _group_id, _member_id, entry_id = _notification_fixture(
        medical_addr="route-medical@example.com"
    )
    slot_date = datetime.date(2035, 2, 24)
    _grant_medical_support(device_id, "route-handler-a")
    _grant_medical_support(device_id, "route-handler-b")

    support_request = model.SupportRequest(
        schedid=entry_id,
        supportkind=1,
        filed_by="test-admin",
        modified_by="test-admin",
        fulfilled_by=existing_handler or None,
        approved=True if existing_handler else None,
        note="",
    )
    model.db.session.add(support_request)
    model.db.session.commit()

    with _route_mail_config(
        route_app,
        MAIL_SERVER=cfg.smtp_host,
        MAIL_PORT=cfg.smtp_port,
        MAIL_USE_TLS=False,
        MAIL_USE_SSL=False,
        MAIL_SUPPRESS_SEND=False,
    ):
        clear_mailpit_messages(cfg)
        try:
            response = _post_scheduler_payload(
                route_client,
                device_id,
                slot_date,
                {
                    "diffs": [
                        {
                            "id": entry_id,
                            "med": {"handler": [existing_handler, next_handler]},
                        }
                    ],
                    "notify": True,
                },
            )

            assert response.status_code == 200
            payload = response.get_json()
            assert payload is not None
            assert sorted(payload["notifications"], key=lambda note: note["key"]) == [
                {"key": "medical", "msg": "success"},
                {"key": "schedule", "msg": "success"},
            ]

            medical_detail = _mailpit_message_for_recipient(
                cfg, "route-medical@example.com"
            )
            medical_text = str(medical_detail.get("Text", ""))
            assert expected_text in medical_text
            if next_handler:
                assert f"to be handled by {next_handler}" in medical_text
            else:
                assert "to be handled by" not in medical_text
        finally:
            clear_mailpit_messages(cfg)


@pytest.mark.covers_route("/device/<the_device>", "POST")
def test_device_schedule_post_notify_false_suppresses_support_emails(
    route_app, route_client, route_app_context
):
    cfg = _require_mailpit()
    ensure_admin_user()
    set_admin_session(route_client)
    device_id, _group_id, _member_id, entry_id = _notification_fixture(
        medical_addr="route-medical@example.com"
    )
    slot_date = datetime.date(2035, 2, 24)

    with _route_mail_config(
        route_app,
        MAIL_SERVER=cfg.smtp_host,
        MAIL_PORT=cfg.smtp_port,
        MAIL_USE_TLS=False,
        MAIL_USE_SSL=False,
        MAIL_SUPPRESS_SEND=False,
    ):
        clear_mailpit_messages(cfg)
        try:
            response = _post_scheduler_payload(
                route_client,
                device_id,
                slot_date,
                {
                    "diffs": [{"id": entry_id, "med": {"requested": True}}],
                    "notify": False,
                },
            )

            assert response.status_code == 200
            payload = response.get_json()
            assert payload is not None
            assert payload["notifications"] == []
            assert list_mailpit_messages(cfg) == []
            assert (
                len(
                    _email_audit_rows(
                        model.EmailAuditLog.action == "email.scheduler.notification",
                        model.EmailAuditLog.details.like(f"%device={device_id}%"),
                    )
                )
                == 0
            )
        finally:
            clear_mailpit_messages(cfg)


@pytest.mark.covers_route("/device/<the_device>", "POST")
def test_device_schedule_post_reports_missing_support_address_without_false_send(
    route_app, route_client, route_app_context
):
    cfg = _require_mailpit()
    ensure_admin_user()
    set_admin_session(route_client)
    device_id, _group_id, _member_id, entry_id = _notification_fixture(medical_addr="")
    slot_date = datetime.date(2035, 2, 24)

    with _route_mail_config(
        route_app,
        MAIL_SERVER=cfg.smtp_host,
        MAIL_PORT=cfg.smtp_port,
        MAIL_USE_TLS=False,
        MAIL_USE_SSL=False,
        MAIL_SUPPRESS_SEND=False,
    ):
        clear_mailpit_messages(cfg)
        try:
            response = _post_scheduler_payload(
                route_client,
                device_id,
                slot_date,
                {
                    "diffs": [{"id": entry_id, "med": {"requested": True}}],
                    "notify": True,
                },
            )

            assert response.status_code == 200
            payload = response.get_json()
            assert payload is not None
            assert sorted(payload["notifications"], key=lambda note: note["key"]) == [
                {"key": "medical", "msg": "address"},
                {"key": "schedule", "msg": "success"},
            ]
            _wait_for_mail_count(cfg, expected=1)

            schedule_detail = _mailpit_message_for_recipient(
                cfg, f"{device_id.lower()}-schedule@example.com"
            )
            assert "Support Requests" in str(schedule_detail.get("Text", ""))

            audit_rows = _email_audit_rows(
                model.EmailAuditLog.action == "email.scheduler.notification",
                model.EmailAuditLog.details.like(f"%device={device_id}%"),
            )
            assert len(audit_rows) == 1
            assert (
                audit_rows[0].recipient == f"{device_id.lower()}-schedule@example.com"
            )
            assert "stream=schedule" in audit_rows[0].details
        finally:
            clear_mailpit_messages(cfg)


@pytest.mark.covers_route("/device/<the_device>", "POST")
def test_support_only_user_can_assign_existing_medical_request(
    route_client, route_app_context
):
    ensure_admin_user()
    device_id, _group_id, _member_id, entry_id = _notification_fixture(
        medical_addr="route-medical@example.com"
    )
    slot_date = datetime.date(2035, 2, 24)
    support_user = "route-support-med"
    _grant_medical_support(device_id, support_user)
    support_request = model.SupportRequest(
        schedid=entry_id,
        supportkind=1,
        filed_by="test-admin",
        modified_by="test-admin",
        fulfilled_by=None,
        approved=None,
        note="",
    )
    model.db.session.add(support_request)
    model.db.session.commit()

    _set_support_session(route_client, support_user)
    response = _post_scheduler_payload(
        route_client,
        device_id,
        slot_date,
        {
            "diffs": [
                {
                    "id": entry_id,
                    "med": {"handler": ["", support_user]},
                }
            ],
            "notify": False,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["saved"] == 1

    updated_request = _support_request_for_entry(entry_id, 1)
    assert updated_request.fulfilled_by == support_user
    assert updated_request.approved is True
    assert updated_request.modified_by == support_user


@pytest.mark.covers_route("/device/<the_device>", "GET")
def test_support_only_user_gets_support_assignment_datalists(
    route_client, route_app_context
):
    ensure_admin_user()
    device_id, _group_id, _member_id, _entry_id = _notification_fixture(
        medical_addr="route-medical@example.com"
    )
    slot_date = datetime.date(2035, 2, 24)
    support_user = "route-support-med"
    _grant_medical_support(device_id, support_user)
    _set_support_session(route_client, support_user)

    response = route_client.get(
        f"/device/{device_id}?start={slot_date.isoformat()}&days=1"
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'datalist id="med"' in body
    assert f'value="{support_user}"' in body


@pytest.mark.covers_route("/device/<the_device>", "POST")
def test_support_only_user_cannot_create_new_medical_request(
    route_client, route_app_context
):
    ensure_admin_user()
    device_id, _group_id, _member_id, entry_id = _notification_fixture(
        medical_addr="route-medical@example.com"
    )
    slot_date = datetime.date(2035, 2, 24)
    support_user = "route-support-med"
    _grant_medical_support(device_id, support_user)
    _set_support_session(route_client, support_user)

    response = _post_scheduler_payload(
        route_client,
        device_id,
        slot_date,
        {
            "diffs": [{"id": entry_id, "med": {"requested": True}}],
            "notify": False,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert "saved" not in payload
    assert payload["errors"][str(entry_id)][0]["message"] == (
        "this change requires booking edit access"
    )
    assert _support_request_count(entry_id, 1) == 0
