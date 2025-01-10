import pytest
from scheduler import model
from datetime import datetime

def test_user_model():
    user = model.User(
        id="test_user",
        label="Test User",
        addr="test@example.com",
        active=True
    )
    assert user.id == "test_user"
    assert user.label == "Test User"
    assert user.addr == "test@example.com"
    assert user.active is True

def test_group_model():
    group = model.Group(
        id="test_group",
        label="Test Group",
        active=True,
        created=datetime.now()
    )
    assert group.id == "test_group"
    assert group.label == "Test Group"
    assert group.active is True

def test_device_model():
    device = model.Device(
        id="test_device",
        label="Test Device",
        active=True
    )
    assert device.id == "test_device" 
    assert device.label == "Test Device"
    assert device.active is True 