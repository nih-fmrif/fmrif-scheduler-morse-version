from scheduler import model


def test_db_isolation_allows_commit_within_test(app_context):
    user = model.User(
        id="isolation-unit-user",
        label="Isolation Unit",
        addr="isolation.unit@example.com",
        active=True,
    )
    model.db.session.add(user)
    model.db.session.commit()

    assert model.get(model.User, "isolation-unit-user") is not None


def test_db_isolation_rolls_back_previous_test_state(app_context):
    assert model.get(model.User, "isolation-unit-user") is None
