"""Public scheduler.logic package API used across routes and tests."""

from . import admin_config as _admin_config
from . import app_error_events as _app_error_events
from . import core as _core
from . import csp_violation_events as _csp_violation_events
from . import notifications as _notifications
from . import rbac_audit_support as _rbac_audit_support
from . import schedule_editor as _schedule_editor
from . import templates as _templates
from .admin_config import *  # noqa: F401,F403
from .app_error_events import *  # noqa: F401,F403
from .core import *  # noqa: F401,F403
from .csp_violation_events import *  # noqa: F401,F403
from .notifications import *  # noqa: F401,F403
from .rbac_audit_support import *  # noqa: F401,F403
from .schedule_editor import *  # noqa: F401,F403
from .templates import *  # noqa: F401,F403

__all__ = list(
    dict.fromkeys(
        [
            *_admin_config.__all__,
            *_app_error_events.__all__,
            *_core.__all__,
            *_csp_violation_events.__all__,
            *_notifications.__all__,
            *_rbac_audit_support.__all__,
            *_schedule_editor.__all__,
            *_templates.__all__,
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
)
