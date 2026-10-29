import datetime

from sqlalchemy.exc import IntegrityError

from scheduler.scheduler_save_error_attribution import (
    SchedulerDiffContext,
    select_scheduler_error_client_ids,
)


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


def test_scheduler_save_error_attribution_matches_member_by_fk_value():
    contexts = {
        "d0": SchedulerDiffContext(
            server_ref="d0",
            client_id="11",
            server_id=11,
            date=None,
            hour=8,
            changed_fields=frozenset({"member"}),
            group_value=None,
            member_value="member-a",
            institute_value=None,
        ),
        "d1": SchedulerDiffContext(
            server_ref="d1",
            client_id="12",
            server_id=12,
            date=None,
            hour=9,
            changed_fields=frozenset({"member"}),
            group_value=None,
            member_value="member-b",
            institute_value=None,
        ),
    }
    err = _integrity_error(
        constraint_name="tblsched_researchercode_fkey",
        message_primary='insert or update on table "tblsched" violates foreign key constraint',
        message_detail='Key (researchercode)=(member-b) is not present in table "tlkpresearcher".',
        pgcode="23503",
    )

    assert select_scheduler_error_client_ids(err, contexts) == ["12"]


def test_scheduler_save_error_attribution_matches_slot_by_date_and_hour():
    contexts = {
        "d0": SchedulerDiffContext(
            server_ref="d0",
            client_id="new-2035-02-01-08",
            server_id=101,
            date=datetime.date(2035, 2, 1),
            hour=8,
            changed_fields=frozenset({"group"}),
            group_value="DEV",
            member_value=None,
            institute_value=None,
        ),
        "d1": SchedulerDiffContext(
            server_ref="d1",
            client_id="new-2035-02-02-09",
            server_id=102,
            date=datetime.date(2035, 2, 2),
            hour=9,
            changed_fields=frozenset({"group"}),
            group_value="DEV",
            member_value=None,
            institute_value=None,
        ),
    }
    err = _integrity_error(
        constraint_name="tblsched_scannercode_key",
        message_primary="duplicate key value violates unique constraint",
        message_detail=(
            "Key (scannercode, scheddate, schedhour)=(TEST, 2035-02-02, 9) "
            "already exists."
        ),
        pgcode="23505",
    )

    assert select_scheduler_error_client_ids(err, contexts) == ["new-2035-02-02-09"]


def test_scheduler_save_error_attribution_falls_back_to_all_candidates():
    contexts = {
        "d0": SchedulerDiffContext(
            server_ref="d0",
            client_id="11",
            server_id=11,
            date=None,
            hour=8,
            changed_fields=frozenset({"group"}),
            group_value="DEV",
            member_value=None,
            institute_value=None,
        ),
        "d1": SchedulerDiffContext(
            server_ref="d1",
            client_id="12",
            server_id=12,
            date=None,
            hour=9,
            changed_fields=frozenset({"member"}),
            group_value=None,
            member_value="member-b",
            institute_value=None,
        ),
    }
    err = _integrity_error(
        constraint_name="tblsched_custom_debug_path",
        message_primary="violates custom schedule guard",
        message_detail="opaque detail",
        pgcode="XX000",
    )

    assert select_scheduler_error_client_ids(err, contexts) == ["11", "12"]
