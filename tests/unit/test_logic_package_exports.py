import scheduler.logic as logic
import scheduler.logic.admin_config as admin_config
import scheduler.logic.core as core_logic
import scheduler.logic.schedule_editor as schedule_logic


def test_logic_package_reexports_public_symbols():
    assert (
        logic.collect_admin_operations_status
        is admin_config.collect_admin_operations_status
    )
    assert logic.get_group is core_logic.get_group
    assert logic.CsrfOnlyForm is schedule_logic.CsrfOnlyForm
