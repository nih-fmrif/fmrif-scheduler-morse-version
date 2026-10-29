from __future__ import annotations

from typing import Any, Callable, List, Tuple

from ._entity_group_device_routes import register_group_and_device_routes
from ._entity_route_common import BreadcrumbLinks, SubpageLinks, configure_route_helpers
from ._entity_template_routes import register_template_routes


def register_entity_routes(
    app,
    *,
    active_user_required: Callable[[Callable[..., Any]], Callable[..., Any]],
    login_required: Callable[[Callable[..., Any]], Callable[..., Any]],
    render_to: Callable[[str], Callable[[Callable[..., Any]], Callable[..., Any]]],
    my_url_fn: Callable[[], str],
    to_fn: Callable[..., Any],
    breadcrumb_fn: Callable[..., BreadcrumbLinks],
    subpage_nav_fn: Callable[[str, List[Tuple[bool, str, str]]], SubpageLinks],
) -> None:
    configure_route_helpers(
        my_url_fn=my_url_fn,
        to_fn=to_fn,
        breadcrumb_fn=breadcrumb_fn,
        subpage_nav_fn=subpage_nav_fn,
    )

    register_group_and_device_routes(
        app,
        active_user_required=active_user_required,
        login_required=login_required,
        render_to=render_to,
    )
    register_template_routes(
        app,
        active_user_required=active_user_required,
        render_to=render_to,
    )
