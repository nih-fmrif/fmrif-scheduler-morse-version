import pytest

from scheduler import model

pytestmark = pytest.mark.route


def test_route_db_isolation_allows_commit_within_test(route_app_context):
    group = model.Group(
        id="ISOG",
        label="ISOG",
        description="Isolation Group",
        color="#123456",
        active=True,
        has_membership=True,
    )
    model.db.session.add(group)
    model.db.session.commit()

    assert model.Group.query.get("ISOG") is not None


def test_route_db_isolation_rolls_back_previous_test_state(route_app_context):
    assert model.Group.query.get("ISOG") is None
