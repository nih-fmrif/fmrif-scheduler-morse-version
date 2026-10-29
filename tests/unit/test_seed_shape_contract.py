"""Guardrails for the rooted SQL seed shape.

This test encodes the minimum rooted-data contract expected from
`sql/003-import-data.sql` plus `sql/900-import-new-data.sql`.

If this fails after seed edits, either:
- restore the missing rooted compatibility patterns in the seed, or
- update this contract with an explicit rationale.
"""

from collections import defaultdict

import pytest

from scheduler import logic, model

pytestmark = pytest.mark.route


def _seed_metrics() -> dict[str, int]:
    row = (
        model.execute(
            """
            select
                (select count(*) from tblsched) as sched_rows,
                (select count(distinct scannercode) from tblsched) as sched_devices,
                (select count(distinct scheddate) from tblsched) as sched_dates,
                (select count(*) from tblsched where researchercode is null) as sched_rc_null,
                (select count(*) from tblsched where templateid is null) as sched_template_null,

                (select count(*) from tbltemplate) as template_rows,
                (select count(*) from tbltemplate where researchercode is null) as template_rc_null,
                (select count(*) from tbltemplate where researchercode is not null) as template_rc_set,
                (select count(*) from tbltemplate where instcode is null) as template_inst_null,
                (select count(*) from tbltemplate where instcode is not null) as template_inst_set,
                (select count(*) from tbltemplate where researchercode like '%[OLD]') as template_old_user_rows,
                (select count(*) from tbltemplate where deptcode = '(none)') as template_none_group_rows,
                (
                    select count(*)
                    from (
                        select scannercode, templatecode, count(*) as cells
                        from tbltemplate
                        group by scannercode, templatecode
                        having count(*) <> 168
                    ) malformed
                ) as template_malformed_count,

                (select count(*) from tbltemplates) as templates_total,
                (select count(*) from tbltemplates where hidden) as templates_hidden,
                (select count(*) from tbltemplates where not hidden) as templates_visible,

                (select count(*) from tlogsched) as log_rows,

                (select count(*) from tlkpdept) as group_rows,
                (select count(*) from tlkpdept where iscurrent) as group_active,
                (select count(*) from tlkpdept where not iscurrent) as group_inactive,
                (select count(*) from tlkpdept where department) as group_department,
                (select count(*) from tlkpdept where not department) as group_non_department,

                (select count(*) from tlkpscanner) as scanner_rows,
                (select count(*) from tlkpscanner where active) as scanner_active,
                (select count(*) from tlkpscanner where not active) as scanner_inactive,

                (select count(*) from devicegroup) as device_group_rows,

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


def _template_compatibility_metrics() -> dict[str, int]:
    template_ids_by_device: dict[str, list[str]] = defaultdict(list)
    for device_id, template_id in model.execute(
        """
        select scannercode, templatecode
        from tbltemplates
        order by scannercode, templatecode
        """
    ):
        template_ids_by_device[str(device_id)].append(str(template_id))

    metrics = {
        "blocking_templates": 0,
        "ready_templates": 0,
        "legacy_member_templates": 0,
        "invalid_group_templates": 0,
    }

    for device_id, template_ids in template_ids_by_device.items():
        device = model.get(model.Device, device_id)
        assert device is not None

        reports = logic.inspect_template_compatibility(device, template_ids)
        for template_id in template_ids:
            report = reports[template_id]
            if report["blocking"]:
                metrics["blocking_templates"] += 1
            else:
                metrics["ready_templates"] += 1
            if any(issue["code"] == "legacy-member" for issue in report["issues"]):
                metrics["legacy_member_templates"] += 1
            if any(issue["code"] == "invalid-group" for issue in report["issues"]):
                metrics["invalid_group_templates"] += 1

    return metrics


def test_route_seed_shape_contract(route_app_context):
    metrics = _seed_metrics()
    compatibility = _template_compatibility_metrics()

    # Rooted schedule rows remain available for interaction tests without
    # claiming a broader production snapshot than the checked-in subset.
    assert metrics["sched_rows"] >= 4
    assert metrics["sched_devices"] >= 2
    assert metrics["sched_dates"] >= 2
    assert metrics["sched_rc_null"] > 0
    assert metrics["sched_template_null"] > 0

    # Rooted templates stay complete and preserve legacy markers for repair flows.
    assert metrics["templates_total"] >= 4
    assert metrics["template_rows"] == metrics["templates_total"] * 168
    assert metrics["template_rc_null"] > 0 and metrics["template_rc_set"] > 0
    assert metrics["template_inst_null"] > 0 and metrics["template_inst_set"] > 0
    assert metrics["template_old_user_rows"] > 0
    assert metrics["template_none_group_rows"] > 0
    assert metrics["template_malformed_count"] == 0
    assert metrics["templates_hidden"] > 0 and metrics["templates_visible"] > 0
    assert compatibility["blocking_templates"] > 0
    assert compatibility["ready_templates"] > 0
    assert compatibility["legacy_member_templates"] > 0
    assert compatibility["invalid_group_templates"] > 0

    # Historical log rows remain present for the log route contract.
    assert metrics["log_rows"] >= 3

    # The additive layer still hydrates enough current relationships for route/RBAC tests.
    assert metrics["group_rows"] >= 80
    assert metrics["group_active"] > 0 and metrics["group_inactive"] > 0
    assert metrics["group_department"] > 0 and metrics["group_non_department"] > 0

    assert metrics["scanner_rows"] >= 15
    assert metrics["scanner_active"] > 0 and metrics["scanner_inactive"] > 0
    assert metrics["device_group_rows"] > 0

    # Membership assumptions used by route/RBAC tests.
    assert metrics["membership_rows"] >= 60
    assert metrics["membership_approved"] >= 60
    assert metrics["membership_pi"] >= 60
    assert metrics["membership_rows"] >= metrics["membership_approved"]
    assert metrics["membership_rows"] >= metrics["membership_pi"]
    assert metrics["dev_pi"] == 1
