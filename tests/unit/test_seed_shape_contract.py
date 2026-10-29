"""Guardrails for the compact SQL seed shape.

This test encodes the minimum data-complexity contract expected from
`sql/003-import-data.sql` plus `sql/900-import-new-data.sql`.

If this fails after seed edits, either:
- restore the missing complexity in the seed, or
- update this contract with an explicit rationale.
"""

import pytest

from scheduler import model

pytestmark = pytest.mark.route


def _seed_metrics() -> dict[str, int]:
    row = (
        model.db.session.execute(
            """
            select
                (select count(*) from tblsched) as sched_rows,
                (select count(distinct scannercode) from tblsched) as sched_devices,
                (select count(distinct scheddate) from tblsched) as sched_dates,
                (select count(*) from tblsched where researchercode is null) as sched_rc_null,
                (select count(*) from tblsched where researchercode is not null) as sched_rc_set,
                (select count(*) from tblsched where time_used is null) as sched_used_null,
                (select count(*) from tblsched where time_used = true) as sched_used_true,
                (select count(*) from tblsched where time_used = false) as sched_used_false,
                (select count(*) from tblsched where templateid is null) as sched_template_null,
                (select count(*) from tblsched where templateid is not null) as sched_template_set,

                (select count(*) from tbltemplate) as template_rows,
                (select count(*) from tbltemplate where researchercode is null) as template_rc_null,
                (select count(*) from tbltemplate where researchercode is not null) as template_rc_set,
                (select count(*) from tbltemplate where instcode is null) as template_inst_null,
                (select count(*) from tbltemplate where instcode is not null) as template_inst_set,

                (select count(*) from tbltemplates where hidden) as templates_hidden,
                (select count(*) from tbltemplates where not hidden) as templates_visible,

                (select count(*) from tlogsched) as log_rows,
                (select count(*) from tlogsched where deptcode_old is not null or researchercode_old is not null or time_used_old is not null) as log_with_old_values,
                (select count(*) from tlogsched where deptcode_old is null and researchercode_old is null and time_used_old is null) as log_without_old_values,

                (select count(*) from tlkpdept) as group_rows,
                (select count(*) from tlkpdept where iscurrent) as group_active,
                (select count(*) from tlkpdept where not iscurrent) as group_inactive,
                (select count(*) from tlkpdept where department) as group_department,
                (select count(*) from tlkpdept where not department) as group_non_department,

                (select count(*) from tlkpscanner) as scanner_rows,
                (select count(*) from tlkpscanner where active) as scanner_active,
                (select count(*) from tlkpscanner where not active) as scanner_inactive,

                (select count(*) from membership) as membership_rows,
                (select count(*) from membership where approved) as membership_approved,
                (select count(*) from membership where pi) as membership_pi,
                (select count(*) from membership where "group" = 'DEV' and pi) as dev_pi
            """
        )
        .mappings()
        .one()
    )
    return dict(row)


def test_route_seed_shape_contract(route_app_context):
    metrics = _seed_metrics()

    # Core schedule complexity: both assigned/unassigned and used/null/unused states.
    assert metrics["sched_rows"] >= 4
    assert metrics["sched_devices"] >= 2
    assert metrics["sched_dates"] >= 2
    assert metrics["sched_rc_null"] > 0 and metrics["sched_rc_set"] > 0
    assert metrics["sched_used_null"] > 0
    assert metrics["sched_used_true"] > 0
    assert metrics["sched_used_false"] > 0
    assert metrics["sched_template_null"] > 0 and metrics["sched_template_set"] > 0

    # Template complexity: both null and explicit assignees/institutes and hidden variants.
    assert metrics["template_rows"] >= 5
    assert metrics["template_rc_null"] > 0 and metrics["template_rc_set"] > 0
    assert metrics["template_inst_null"] > 0 and metrics["template_inst_set"] > 0
    assert metrics["templates_hidden"] > 0 and metrics["templates_visible"] > 0

    # Log complexity: entries with and without historical "old" values.
    assert metrics["log_rows"] >= 3
    assert metrics["log_with_old_values"] > 0
    assert metrics["log_without_old_values"] > 0

    # Group/device breadth after additive mapping import from csv files.
    assert metrics["group_rows"] >= 80
    assert metrics["group_active"] > 0 and metrics["group_inactive"] > 0
    assert metrics["group_department"] > 0 and metrics["group_non_department"] > 0

    assert metrics["scanner_rows"] >= 15
    assert metrics["scanner_active"] > 0 and metrics["scanner_inactive"] > 0

    # Membership assumptions used by route/RBAC tests.
    assert metrics["membership_rows"] >= 60
    assert metrics["membership_approved"] >= 60
    assert metrics["membership_pi"] >= 60
    assert metrics["membership_rows"] >= metrics["membership_approved"]
    assert metrics["membership_rows"] >= metrics["membership_pi"]
    assert metrics["dev_pi"] == 1
