"""Explicit route contract for no-browser route coverage.

If a route or method is added/changed in the app, this contract must be updated.
The route-matrix tests enforce parity against Flask's registered URL map.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Mapping


@dataclass(frozen=True)
class RouteExpectation:
    sample_path: str
    methods: Mapping[str, int]
    headers: Mapping[str, str] = field(default_factory=dict)


def protected_route(sample_path: str, methods: Iterable[str]) -> RouteExpectation:
    """Route requiring authentication in API mode (expects 401 unauthenticated)."""
    return RouteExpectation(
        sample_path=sample_path,
        methods={method.upper(): 401 for method in methods},
        headers={"Accept": "application/json"},
    )


def public_route(
    sample_path: str,
    methods: Mapping[str, int],
    headers: Mapping[str, str] | None = None,
) -> RouteExpectation:
    """Public/auth route with explicit status expectations by HTTP method."""
    return RouteExpectation(
        sample_path=sample_path,
        methods={method.upper(): status for method, status in methods.items()},
        headers=dict(headers or {}),
    )


RBAC_ROLES = ("admin", "member", "dev", "tech", "inactive")


@dataclass(frozen=True)
class RbacRouteExpectation:
    sample_path: str
    by_role: Mapping[str, int]
    headers: Mapping[str, str] = field(default_factory=dict)


def _rbac_statuses(**kwargs: int) -> Dict[str, int]:
    expected = set(RBAC_ROLES)
    actual = set(kwargs.keys())
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        problems = []
        if missing:
            problems.append(f"missing={missing}")
        if extra:
            problems.append(f"extra={extra}")
        raise ValueError("invalid RBAC role status mapping: " + ", ".join(problems))
    return {role: int(kwargs[role]) for role in RBAC_ROLES}


def rbac_login_required(sample_path: str) -> RbacRouteExpectation:
    return RbacRouteExpectation(
        sample_path=sample_path,
        by_role=_rbac_statuses(admin=200, member=200, dev=200, tech=200, inactive=200),
    )


def rbac_active_user_required(sample_path: str) -> RbacRouteExpectation:
    return RbacRouteExpectation(
        sample_path=sample_path,
        by_role=_rbac_statuses(admin=200, member=200, dev=200, tech=200, inactive=403),
    )


def rbac_admin_only(sample_path: str) -> RbacRouteExpectation:
    return RbacRouteExpectation(
        sample_path=sample_path,
        by_role=_rbac_statuses(admin=200, member=403, dev=403, tech=403, inactive=403),
    )


def rbac_custom(sample_path: str, **statuses: int) -> RbacRouteExpectation:
    return RbacRouteExpectation(
        sample_path=sample_path, by_role=_rbac_statuses(**statuses)
    )


@dataclass(frozen=True)
class RbacMutatingExpectation:
    sample_path: str
    method: str
    by_role: Mapping[str, bool]
    headers: Mapping[str, str] = field(default_factory=dict)


def _rbac_gate(**kwargs: bool) -> Dict[str, bool]:
    expected = set(RBAC_ROLES)
    actual = set(kwargs.keys())
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        problems = []
        if missing:
            problems.append(f"missing={missing}")
        if extra:
            problems.append(f"extra={extra}")
        raise ValueError("invalid RBAC gate mapping: " + ", ".join(problems))
    return {role: bool(kwargs[role]) for role in RBAC_ROLES}


def rbac_mutating_login_required(
    sample_path: str,
    method: str = "POST",
) -> RbacMutatingExpectation:
    return RbacMutatingExpectation(
        sample_path=sample_path,
        method=method.upper(),
        by_role=_rbac_gate(admin=True, member=True, dev=True, tech=True, inactive=True),
    )


def rbac_mutating_active_user_required(
    sample_path: str,
    method: str = "POST",
) -> RbacMutatingExpectation:
    return RbacMutatingExpectation(
        sample_path=sample_path,
        method=method.upper(),
        by_role=_rbac_gate(
            admin=True, member=True, dev=True, tech=True, inactive=False
        ),
    )


def rbac_mutating_admin_only(
    sample_path: str,
    method: str = "POST",
) -> RbacMutatingExpectation:
    return RbacMutatingExpectation(
        sample_path=sample_path,
        method=method.upper(),
        by_role=_rbac_gate(
            admin=True, member=False, dev=False, tech=False, inactive=False
        ),
    )


def rbac_mutating_dev_only(
    sample_path: str,
    method: str = "POST",
) -> RbacMutatingExpectation:
    return RbacMutatingExpectation(
        sample_path=sample_path,
        method=method.upper(),
        by_role=_rbac_gate(
            admin=False, member=False, dev=True, tech=False, inactive=False
        ),
    )


def rbac_mutating_custom(
    sample_path: str,
    method: str = "POST",
    **gate: bool,
) -> RbacMutatingExpectation:
    return RbacMutatingExpectation(
        sample_path=sample_path,
        method=method.upper(),
        by_role=_rbac_gate(**gate),
    )


ROUTE_EXPECTATIONS: Dict[str, RouteExpectation] = {
    "/": protected_route("/", ["GET"]),
    "/auth/callback": public_route("/auth/callback", {"GET": 302}),
    "/auth/entra": public_route("/auth/entra", {"GET": 302}),
    "/auth/login": public_route("/auth/login", {"GET": 200}),
    "/auth/logout": public_route("/auth/logout", {"POST": 400}),
    "/auth/session": public_route("/auth/session", {"POST": 401}),
    "/auth/test/session": public_route(
        "/auth/test/session", {"POST": 403, "DELETE": 403}
    ),
    "/app/issues": protected_route("/app/issues", ["GET"]),
    "/app/issues/notifications/scan": protected_route(
        "/app/issues/notifications/scan", ["POST"]
    ),
    "/app/issues/notifications/state": protected_route(
        "/app/issues/notifications/state", ["POST"]
    ),
    "/device/<the_device>": protected_route("/device/test-device", ["GET", "POST"]),
    "/device/<the_device>/templates": protected_route(
        "/device/test-device/templates", ["GET", "POST"]
    ),
    "/device/<the_device>/templates/add": protected_route(
        "/device/test-device/templates/add", ["GET", "POST"]
    ),
    "/device/<the_device>/templates/archive": protected_route(
        "/device/test-device/templates/archive", ["GET"]
    ),
    "/device/<the_device>/templates/edit-metadata/<the_template>": protected_route(
        "/device/test-device/templates/edit-metadata/test-template", ["GET", "POST"]
    ),
    "/device/<the_device>/templates/edit/<the_template>": protected_route(
        "/device/test-device/templates/edit/test-template", ["GET", "POST"]
    ),
    "/device/<the_device>/templates/list": protected_route(
        "/device/test-device/templates/list", ["GET"]
    ),
    "/group/<the_group>": protected_route("/group/test-group", ["GET"]),
    "/rbac": protected_route("/rbac", ["GET"]),
    "/join": protected_route("/join", ["GET", "POST"]),
    "/join/approve/<token>": protected_route(
        "/join/approve/test-token", ["GET", "POST"]
    ),
    "/join/deny/<token>": protected_route("/join/deny/test-token", ["GET", "POST"]),
    "/join/tech": protected_route("/join/tech", ["GET", "POST"]),
    "/json/v1/device/<the_device>/schedule-rows": protected_route(
        "/json/v1/device/TEST/schedule-rows?start=2026-02-01&days=7&hours=8,9",
        ["GET"],
    ),
    "/json/v1/device/<the_device>/schedule-next-day": protected_route(
        "/json/v1/device/TEST/schedule-next-day?start=2026-02-01&direction=1",
        ["GET"],
    ),
    "/json/v1/rbac/mutate": protected_route("/json/v1/rbac/mutate", ["POST"]),
    "/json/v1/rbac/audit": protected_route("/json/v1/rbac/audit", ["GET"]),
    "/json/v1/email/audit": protected_route("/json/v1/email/audit", ["GET"]),
    "/json/v1/rbac/explorer": protected_route("/json/v1/rbac/explorer", ["GET"]),
    "/json/v1/log/<id>": protected_route("/json/v1/log/1", ["GET"]),
    "/mailing-lists": protected_route("/mailing-lists", ["GET", "POST"]),
    "/robots.txt": public_route("/robots.txt", {"GET": 200}),
}


# Explicit role contract for authenticated GET routes.
# This complements ROUTE_EXPECTATIONS by enforcing role behavior across mock profiles.
RBAC_GET_EXPECTATIONS: Dict[str, RbacRouteExpectation] = {
    "/": rbac_login_required("/"),
    "/mailing-lists": rbac_login_required("/mailing-lists"),
    "/device/<the_device>": rbac_login_required("/device/TEST"),
    "/device/<the_device>/templates": rbac_admin_only("/device/TEST/templates"),
    "/device/<the_device>/templates/list": rbac_admin_only(
        "/device/TEST/templates/list"
    ),
    "/device/<the_device>/templates/archive": rbac_admin_only(
        "/device/TEST/templates/archive"
    ),
    "/device/<the_device>/templates/add": rbac_admin_only("/device/TEST/templates/add"),
    "/device/<the_device>/templates/edit/<the_template>": rbac_admin_only(
        "/device/TEST/templates/edit/A"
    ),
    "/device/<the_device>/templates/edit-metadata/<the_template>": rbac_admin_only(
        "/device/TEST/templates/edit-metadata/A"
    ),
    "/rbac": rbac_custom(
        "/rbac", admin=200, member=403, dev=403, tech=403, inactive=403
    ),
    "/app/issues": rbac_admin_only("/app/issues"),
    "/group/<the_group>": rbac_custom(
        "/group/DEV", admin=200, member=403, dev=200, tech=200, inactive=403
    ),
    "/join": rbac_active_user_required("/join"),
    "/join/tech": rbac_custom(
        "/join/tech", admin=403, member=403, dev=200, tech=403, inactive=403
    ),
    "/join/approve/<token>": rbac_custom(
        "/join/approve/test-token",
        admin=400,
        member=400,
        dev=400,
        tech=400,
        inactive=403,
    ),
    "/join/deny/<token>": rbac_custom(
        "/join/deny/test-token",
        admin=400,
        member=400,
        dev=400,
        tech=400,
        inactive=403,
    ),
    "/json/v1/device/<the_device>/schedule-rows": rbac_login_required(
        "/json/v1/device/TEST/schedule-rows?start=2026-02-01&days=7&hours=8,9"
    ),
    "/json/v1/device/<the_device>/schedule-next-day": rbac_login_required(
        "/json/v1/device/TEST/schedule-next-day?start=2026-02-01&direction=1"
    ),
    "/json/v1/rbac/audit": rbac_admin_only("/json/v1/rbac/audit"),
    "/json/v1/email/audit": rbac_admin_only("/json/v1/email/audit"),
    "/json/v1/rbac/explorer": rbac_admin_only("/json/v1/rbac/explorer"),
    "/json/v1/log/<id>": rbac_login_required("/json/v1/log/1"),
}


# Explicit role-gate contract for protected mutating routes.
# "allow" means role should pass authorization checks (may still fail validation).
# "deny" means role should be rejected with 403 before mutation logic.
RBAC_MUTATING_EXPECTATIONS: Dict[tuple[str, str], RbacMutatingExpectation] = {
    ("/device/<the_device>", "POST"): rbac_mutating_custom(
        "/device/TEST",
        admin=True,
        member=False,
        dev=True,
        tech=False,
        inactive=False,
    ),
    ("/device/<the_device>/templates", "POST"): rbac_mutating_admin_only(
        "/device/TEST/templates"
    ),
    ("/device/<the_device>/templates/add", "POST"): rbac_mutating_admin_only(
        "/device/TEST/templates/add"
    ),
    (
        "/device/<the_device>/templates/edit-metadata/<the_template>",
        "POST",
    ): rbac_mutating_admin_only("/device/TEST/templates/edit-metadata/A"),
    (
        "/device/<the_device>/templates/edit/<the_template>",
        "POST",
    ): rbac_mutating_admin_only("/device/TEST/templates/edit/A"),
    ("/join", "POST"): rbac_mutating_active_user_required("/join"),
    ("/join/tech", "POST"): rbac_mutating_dev_only("/join/tech"),
    ("/json/v1/rbac/mutate", "POST"): rbac_mutating_admin_only("/json/v1/rbac/mutate"),
    ("/app/issues/notifications/scan", "POST"): rbac_mutating_admin_only(
        "/app/issues/notifications/scan"
    ),
    ("/app/issues/notifications/state", "POST"): rbac_mutating_admin_only(
        "/app/issues/notifications/state"
    ),
    ("/mailing-lists", "POST"): rbac_mutating_login_required("/mailing-lists"),
}

# Protected mutating routes that need richer fixtures to evaluate role gates.
RBAC_MUTATING_EXEMPTIONS: Dict[tuple[str, str], str] = {
    (
        "/auth/session",
        "POST",
    ): "Session bootstrap validates bearer tokens and is not role-based.",
    (
        "/join/approve/<token>",
        "POST",
    ): "PI authorization depends on a valid signed token and pending join request fixture.",
    (
        "/join/deny/<token>",
        "POST",
    ): "PI authorization depends on a valid signed token and pending join request fixture.",
}

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Route methods that must have explicit behavioral tests linked with:
# @pytest.mark.covers_route("<rule>", "<method>")
BEHAVIOR_TEST_REQUIREMENTS: Dict[tuple[str, str], str] = {
    ("/auth/logout", "POST"): "Logout must enforce CSRF and clear session state.",
    (
        "/auth/session",
        "POST",
    ): "Session bootstrap must reject missing/invalid bearer tokens.",
    (
        "/auth/test/session",
        "POST",
    ): "Mock session creation must enforce test secrets and network restrictions.",
    (
        "/auth/test/session",
        "DELETE",
    ): "Mock session cleanup must clear established test sessions.",
    (
        "/join/approve/<token>",
        "POST",
    ): "Join approval must enforce CSRF and update request state.",
    (
        "/join/deny/<token>",
        "POST",
    ): "Join denial must enforce CSRF and remove pending requests.",
    (
        "/json/v1/rbac/mutate",
        "POST",
    ): "RBAC explorer mutations must enforce CSRF and admin-only write permissions.",
    (
        "/app/issues/notifications/scan",
        "POST",
    ): "Admin issues panel scan must run detector reconciliation with CSRF protection.",
    (
        "/app/issues/notifications/state",
        "POST",
    ): "Admin issues panel state updates must require CSRF and mandatory notes.",
    (
        "/device/<the_device>",
        "POST",
    ): "Scheduler route must process JSON diff submissions safely.",
    (
        "/device/<the_device>/templates",
        "POST",
    ): "Template application must validate submitted template selections.",
    (
        "/device/<the_device>/templates/add",
        "POST",
    ): "Template add must persist template metadata and seed template slots.",
    (
        "/device/<the_device>/templates/edit/<the_template>",
        "POST",
    ): "Template schedule edit must process JSON diff submissions safely.",
    (
        "/device/<the_device>/templates/edit-metadata/<the_template>",
        "POST",
    ): "Template metadata edit must persist changes.",
    (
        "/mailing-lists",
        "POST",
    ): "Mailing-list form must validate selected lists and submit requested actions.",
    (
        "/join",
        "POST",
    ): "Join form must create pending membership requests for selected groups.",
    (
        "/join/tech",
        "POST",
    ): "Technologist join form must persist a pending technologist application for eligible users.",
}

# Route methods intentionally not required in no-browser route tests yet.
# Keep this list explicit so adding/changing mutating routes always requires
# deciding whether to add a behavioral test or document why it is deferred.
BEHAVIOR_TEST_EXEMPTIONS: Dict[tuple[str, str], str] = {}
