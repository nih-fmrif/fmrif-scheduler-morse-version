from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from scheduler.scheduler_save_error_policy import explain_scheduler_save_error


class _Diag:
    def __init__(
        self,
        *,
        constraint_name=None,
        message_primary=None,
        message_detail=None,
        sqlstate=None,
    ):
        self.constraint_name = constraint_name
        self.message_primary = message_primary
        self.message_detail = message_detail
        self.sqlstate = sqlstate


class _Orig(Exception):
    def __init__(
        self,
        *,
        constraint_name=None,
        message_primary=None,
        message_detail=None,
        pgcode=None,
    ):
        super().__init__(message_primary or "database error")
        self.diag = _Diag(
            constraint_name=constraint_name,
            message_primary=message_primary,
            message_detail=message_detail,
            sqlstate=pgcode,
        )
        self.pgcode = pgcode


def _integrity_error(
    *,
    constraint_name=None,
    message_primary=None,
    message_detail=None,
    pgcode=None,
):
    return IntegrityError(
        "insert into tblsched ...",
        {},
        _Orig(
            constraint_name=constraint_name,
            message_primary=message_primary,
            message_detail=message_detail,
            pgcode=pgcode,
        ),
    )


def test_scheduler_save_error_policy_maps_known_schedule_constraint():
    decision = explain_scheduler_save_error(
        _integrity_error(
            constraint_name="tblsched_scannercode_key",
            message_primary="duplicate key value violates unique constraint",
            message_detail=(
                "Key (scannercode, scheddate, schedhour)=(TEST, 2035-02-01, 8) "
                "already exists."
            ),
            pgcode="23505",
        )
    )

    assert decision.source == "slot"
    assert decision.code == "slot_conflict"
    assert "another entry already exists" in decision.message
    assert decision.notify_admin is False


def test_scheduler_save_error_policy_keeps_bounded_detail_for_unknown_constraint():
    decision = explain_scheduler_save_error(
        _integrity_error(
            constraint_name="tblsched_custom_debug_path",
            message_primary="violates custom schedule guard",
            message_detail="explanation repeated " * 30,
            pgcode="XX000",
        )
    )

    assert decision.source == "database"
    assert decision.code == "database_rejected"
    assert decision.message == (
        "database rejected the change. refresh the schedule and retry. "
        "if it keeps happening, contact an administrator."
    )
    assert decision.notify_admin is True


def test_scheduler_save_error_policy_handles_non_diagnostic_sqlalchemy_errors():
    decision = explain_scheduler_save_error(SQLAlchemyError("plain database failure"))

    assert decision.source == "database"
    assert decision.code == "database_rejected"
    assert decision.message == (
        "database rejected the change. refresh the schedule and retry. "
        "if it keeps happening, contact an administrator."
    )
    assert decision.notify_admin is True
