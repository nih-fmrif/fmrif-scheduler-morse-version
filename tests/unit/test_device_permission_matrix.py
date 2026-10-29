import pytest
from route_seed import (
    create_device,
    ensure_active_user,
    ensure_group,
    set_group_membership,
)

from scheduler import logic, model

pytestmark = pytest.mark.route


def _seed_matrix_device() -> model.Device:
    device_id, device_label = create_device()
    device = model.get(model.Device, device_id)
    assert device is not None
    device.label = device_label
    model.db.session.add(device)
    ensure_group(
        "admin",
        label="admin",
        description="admin",
        color="#000000",
        active=True,
        has_membership=True,
    )
    ensure_group(
        "DEV",
        label="DEV",
        description="DEV",
        color="#224466",
        active=True,
        has_membership=True,
    )
    ensure_group(
        "MATRIX",
        label="Matrix Group",
        description="Matrix Group",
        color="#335577",
        active=True,
        has_membership=True,
    )
    if model.get(model.DeviceGroup, (device_id, "MATRIX")) is None:
        model.db.session.add(model.DeviceGroup(device=device_id, group="MATRIX"))
    model.db.session.flush()
    return device


def _seed_matrix_user(user_id: str) -> model.User:
    ensure_active_user(user_id, f"{user_id}@example.com", user_id)
    user = model.get(model.User, user_id)
    assert user is not None
    return user


def _matrix_user_id(scenario: str) -> str:
    return {
        "admin": "mx-admin",
        "dev_pi": "mx-devpi",
        "group_writer": "mx-writer",
        "templates_only": "mx-template",
        "slot_only": "mx-slot",
        "tech_only": "mx-tech",
        "medical_only": "mx-med",
        "training_only": "mx-train",
        "read_only": "mx-read",
    }[scenario]


def _upsert_user_device(
    user_id: str,
    device_id: str,
    *,
    templates: bool = False,
    slot: bool = False,
    tech: bool = False,
    medical: bool = False,
    training: bool = False,
) -> None:
    row = model.get(model.UserDevice, (user_id, device_id))
    if row is None:
        row = model.UserDevice(user=user_id, device=device_id)
    row.templates = templates
    row.slot = slot
    row.tech = tech
    row.medical = medical
    row.training = training
    model.db.session.add(row)
    model.db.session.flush()


@pytest.mark.parametrize(
    ("scenario", "setup", "expected"),
    [
        (
            "admin",
            lambda device, user_id: set_group_membership(
                "admin", user_id, approved=True, pi=False
            ),
            {
                "edit": True,
                "edit_any": True,
                "template": True,
                "tech": True,
                "medical": True,
                "training": True,
            },
        ),
        (
            "dev_pi",
            lambda device, user_id: set_group_membership(
                "DEV", user_id, approved=True, pi=True
            ),
            {
                "edit": True,
                "edit_any": True,
                "template": True,
                "tech": True,
                "medical": True,
                "training": True,
            },
        ),
        (
            "group_writer",
            lambda device, user_id: set_group_membership(
                "MATRIX", user_id, approved=True, pi=False
            ),
            {
                "edit": True,
                "edit_any": False,
                "template": False,
                "tech": False,
                "medical": False,
                "training": False,
            },
        ),
        (
            "templates_only",
            lambda device, user_id: _upsert_user_device(
                user_id, device.id, templates=True
            ),
            {
                "edit": False,
                "edit_any": False,
                "template": True,
                "tech": False,
                "medical": False,
                "training": False,
            },
        ),
        (
            "slot_only",
            lambda device, user_id: _upsert_user_device(user_id, device.id, slot=True),
            {
                "edit": True,
                "edit_any": True,
                "template": False,
                "tech": False,
                "medical": False,
                "training": False,
            },
        ),
        (
            "tech_only",
            lambda device, user_id: _upsert_user_device(user_id, device.id, tech=True),
            {
                "edit": False,
                "edit_any": False,
                "template": False,
                "tech": True,
                "medical": False,
                "training": False,
            },
        ),
        (
            "medical_only",
            lambda device, user_id: _upsert_user_device(
                user_id, device.id, medical=True
            ),
            {
                "edit": False,
                "edit_any": False,
                "template": False,
                "tech": False,
                "medical": True,
                "training": False,
            },
        ),
        (
            "training_only",
            lambda device, user_id: _upsert_user_device(
                user_id, device.id, training=True
            ),
            {
                "edit": False,
                "edit_any": False,
                "template": False,
                "tech": False,
                "medical": False,
                "training": True,
            },
        ),
        (
            "read_only",
            lambda device, user_id: None,
            {
                "edit": False,
                "edit_any": False,
                "template": False,
                "tech": False,
                "medical": False,
                "training": False,
            },
        ),
    ],
)
def test_device_permission_matrix_exposes_expected_capabilities(
    route_app_context, scenario, setup, expected
):
    device = _seed_matrix_device()
    user = _seed_matrix_user(_matrix_user_id(scenario))
    setup(device, user.id)

    perms = logic.get_dev_perms(user, device)

    assert {
        "edit": perms.edit,
        "edit_any": perms.edit_any,
        "template": perms.template,
        "tech": perms.tech,
        "medical": perms.medical,
        "training": perms.training,
    } == expected
