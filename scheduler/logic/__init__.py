"""Public scheduler.logic package API used across routes and tests."""

from . import admin_config as _admin_config
from . import app_error_events as _app_error_events
from . import core as _core
from . import csp_violation_events as _csp_violation_events
from . import notifications as _notifications
from . import rbac_audit_support as _rbac_audit_support
from . import schedule_editor as _schedule_editor
from . import templates as _templates


def _export_public(module: object) -> list[str]:
    names = list(getattr(module, "__all__", []))
    globals().update({name: getattr(module, name) for name in names})
    return names


__all__ = list(
    dict.fromkeys(
        [
            *_export_public(_admin_config),
            *_export_public(_app_error_events),
            *_export_public(_core),
            *_export_public(_csp_violation_events),
            *_export_public(_notifications),
            *_export_public(_rbac_audit_support),
            *_export_public(_schedule_editor),
            *_export_public(_templates),
        ]
    )
)

del (
    _admin_config,
    _app_error_events,
    _core,
    _csp_violation_events,
    _notifications,
    _rbac_audit_support,
    _schedule_editor,
    _templates,
    _export_public,
)
