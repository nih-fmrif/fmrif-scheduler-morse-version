from __future__ import annotations

import ast
from pathlib import Path

import pytest
from route_contract import (
    BEHAVIOR_TEST_EXEMPTIONS,
    BEHAVIOR_TEST_REQUIREMENTS,
    MUTATING_METHODS,
    RBAC_GET_EXPECTATIONS,
    RBAC_MUTATING_EXEMPTIONS,
    RBAC_MUTATING_EXPECTATIONS,
    RBAC_ROLES,
    ROUTE_EXPECTATIONS,
)
from route_seed import seeded_dev_user_id, seeded_scanner_id, seeded_sched_log_id

from scheduler import model
from scheduler.auth import views as auth_views
from scheduler.config import settings

pytestmark = pytest.mark.route


def _registered_route_methods(route_app) -> dict[str, set[str]]:
    registered: dict[str, set[str]] = {}
    for rule in route_app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        methods = {m for m in rule.methods if m not in {"HEAD", "OPTIONS"}}
        registered[rule.rule] = methods
    return registered


def _expected_route_methods() -> dict[str, set[str]]:
    expected: dict[str, set[str]] = {}
    for rule, expectation in ROUTE_EXPECTATIONS.items():
        expected[rule] = set(expectation.methods.keys())
    return expected


def _route_method_cases() -> list[tuple[str, str]]:
    cases: list[tuple[str, str]] = []
    for rule, expectation in sorted(ROUTE_EXPECTATIONS.items()):
        for method in sorted(expectation.methods.keys()):
            cases.append((rule, method))
    return cases


def _mutating_route_method_cases() -> list[tuple[str, str]]:
    cases: list[tuple[str, str]] = []
    for rule, expectation in sorted(ROUTE_EXPECTATIONS.items()):
        for method in sorted(expectation.methods.keys()):
            if method in MUTATING_METHODS:
                cases.append((rule, method))
    return cases


def _format_route_method_case(case: tuple[str, str]) -> str:
    rule, method = case
    return f"{method} {rule}"


def _rbac_route_cases() -> list[tuple[str, str]]:
    cases: list[tuple[str, str]] = []
    for rule in sorted(RBAC_GET_EXPECTATIONS.keys()):
        for role in RBAC_ROLES:
            cases.append((rule, role))
    return cases


def _protected_get_rules() -> set[str]:
    return {
        rule
        for rule, expectation in ROUTE_EXPECTATIONS.items()
        if expectation.methods.get("GET") == 401
    }


def _protected_mutating_route_methods() -> set[tuple[str, str]]:
    protected: set[tuple[str, str]] = set()
    for rule, expectation in ROUTE_EXPECTATIONS.items():
        for method, status in expectation.methods.items():
            if method in MUTATING_METHODS and status == 401:
                protected.add((rule, method))
    return protected


def _rbac_mutating_route_cases() -> list[tuple[str, str, str]]:
    cases: list[tuple[str, str, str]] = []
    for rule, method in sorted(RBAC_MUTATING_EXPECTATIONS.keys()):
        for role in RBAC_ROLES:
            cases.append((rule, method, role))
    return cases


def _seed_rbac_contract_data() -> None:
    scanner_id = seeded_scanner_id()
    # RBAC contract paths for template edit routes depend on a concrete template id.
    existing = model.Template.query.get(("A", scanner_id))
    if existing is not None:
        return
    model.db.session.add(
        model.Template(
            id="A",
            device=scanner_id,
            label="RBAC Template",
            description="RBAC contract seed",
            hidden=False,
        )
    )
    model.db.session.flush()


def _resolve_seeded_device_sample_path(sample_path: str) -> str:
    resolved = sample_path
    if "/device/TEST" in resolved:
        resolved = resolved.replace("/device/TEST", f"/device/{seeded_scanner_id()}")
    if "/users/testuser" in resolved:
        resolved = resolved.replace("/users/testuser", f"/users/{seeded_dev_user_id()}")
    if "/json/v1/log/1" in resolved:
        try:
            resolved = resolved.replace(
                "/json/v1/log/1", f"/json/v1/log/{seeded_sched_log_id()}"
            )
        except AssertionError:
            # Some seed sets have no schedule entries; keep fallback sample id.
            pass
    return resolved


def _client_for_profile(profile: str, route_app):
    client = route_app.test_client()
    response = client.post(
        "/auth/test/session",
        json={"profile": profile},
        headers={"X-Test-Auth-Secret": "unit-secret"},
    )
    assert response.status_code == 200, (
        f"failed to create test session for profile={profile}: "
        f"{response.status_code} {response.get_data(as_text=True)}"
    )
    return client


@pytest.fixture(autouse=True)
def _enable_mock_auth(monkeypatch):
    monkeypatch.setattr(settings.auth_test, "enabled", True)
    monkeypatch.setattr(settings.auth_test, "shared_secret", "unit-secret")
    monkeypatch.setattr(settings.security, "auth_rate_limit_max_requests", 100000)
    auth_views._AUTH_RATE_LIMIT_BUCKETS.clear()


def _covers_route_markers_from_tests() -> set[tuple[str, str]]:
    def parse_marker(call: ast.Call) -> tuple[str, str] | None:
        if not isinstance(call.func, ast.Attribute) or call.func.attr != "covers_route":
            return None
        mark_obj = call.func.value
        if not isinstance(mark_obj, ast.Attribute) or mark_obj.attr != "mark":
            return None
        if not isinstance(mark_obj.value, ast.Name) or mark_obj.value.id != "pytest":
            return None
        if len(call.args) != 2:
            return None
        rule_node, method_node = call.args
        if (
            not isinstance(rule_node, ast.Constant)
            or not isinstance(rule_node.value, str)
            or not isinstance(method_node, ast.Constant)
            or not isinstance(method_node.value, str)
        ):
            return None
        return (rule_node.value, method_node.value.upper())

    covered: set[tuple[str, str]] = set()
    tests_root = Path(__file__).resolve().parent
    for test_file in sorted(tests_root.glob("test_*.py")):
        tree = ast.parse(test_file.read_text(encoding="utf-8"), filename=str(test_file))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                marker = parse_marker(decorator)
                if marker is not None:
                    covered.add(marker)
    return covered


def test_route_contract_tracks_all_registered_route_methods(route_app):
    registered = _registered_route_methods(route_app)
    expected = _expected_route_methods()

    missing_rules = sorted(set(registered) - set(expected))
    stale_rules = sorted(set(expected) - set(registered))

    assert not missing_rules, (
        "Routes missing from ROUTE_EXPECTATIONS. "
        "Add coverage expectations for these route rules: "
        f"{missing_rules}"
    )
    assert not stale_rules, (
        "ROUTE_EXPECTATIONS contains routes that are not registered anymore. "
        f"Remove these stale entries: {stale_rules}"
    )

    method_mismatches: list[str] = []
    for rule in sorted(registered):
        if registered[rule] != expected[rule]:
            method_mismatches.append(
                f"{rule}: registered={sorted(registered[rule])}, "
                f"expected={sorted(expected[rule])}"
            )

    assert not method_mismatches, (
        "ROUTE_EXPECTATIONS method set mismatch. "
        "Update expected methods to match route decorators:\n"
        + "\n".join(method_mismatches)
    )


def test_rbac_contract_tracks_all_protected_get_routes():
    protected_get = _protected_get_rules()
    rbac_rules = set(RBAC_GET_EXPECTATIONS.keys())

    missing_rules = sorted(protected_get - rbac_rules)
    stale_rules = sorted(rbac_rules - protected_get)

    assert not missing_rules, (
        "Protected GET routes missing from RBAC_GET_EXPECTATIONS. "
        "Add role expectations for: "
        f"{missing_rules}"
    )
    assert not stale_rules, (
        "RBAC_GET_EXPECTATIONS contains non-protected-GET routes. "
        f"Remove stale entries: {stale_rules}"
    )

    role_mismatches: list[str] = []
    expected_roles = set(RBAC_ROLES)
    for rule in sorted(RBAC_GET_EXPECTATIONS.keys()):
        actual_roles = set(RBAC_GET_EXPECTATIONS[rule].by_role.keys())
        if actual_roles != expected_roles:
            role_mismatches.append(
                f"{rule}: roles={sorted(actual_roles)}, expected={sorted(expected_roles)}"
            )

    assert not role_mismatches, (
        "RBAC_GET_EXPECTATIONS must define statuses for every role. "
        "Fix role mappings:\n" + "\n".join(role_mismatches)
    )


def test_rbac_mutating_contract_tracks_all_protected_mutating_route_methods():
    protected_mutating = _protected_mutating_route_methods()
    expected = set(RBAC_MUTATING_EXPECTATIONS.keys())
    exempt = set(RBAC_MUTATING_EXEMPTIONS.keys())

    overlap = sorted(expected & exempt)
    missing = sorted(protected_mutating - expected - exempt)
    stale = sorted((expected | exempt) - protected_mutating)

    assert not overlap, (
        "Mutating RBAC route methods cannot be both expected and exempt. "
        + ", ".join(_format_route_method_case(case) for case in overlap)
    )
    assert not missing, (
        "Protected mutating route methods missing RBAC contract decisions. "
        "Add each case to RBAC_MUTATING_EXPECTATIONS or RBAC_MUTATING_EXEMPTIONS: "
        + ", ".join(_format_route_method_case(case) for case in missing)
    )
    assert not stale, (
        "Mutating RBAC contract contains route methods that no longer exist. "
        "Remove stale entries: "
        + ", ".join(_format_route_method_case(case) for case in stale)
    )

    expected_roles = set(RBAC_ROLES)
    role_mismatches: list[str] = []
    method_mismatches: list[str] = []
    for rule, method in sorted(RBAC_MUTATING_EXPECTATIONS.keys()):
        expectation = RBAC_MUTATING_EXPECTATIONS[(rule, method)]
        actual_roles = set(expectation.by_role.keys())
        if actual_roles != expected_roles:
            role_mismatches.append(
                f"{method} {rule}: roles={sorted(actual_roles)}, expected={sorted(expected_roles)}"
            )
        if expectation.method != method:
            method_mismatches.append(
                f"{method} {rule}: expectation.method={expectation.method}"
            )

    assert not role_mismatches, (
        "RBAC_MUTATING_EXPECTATIONS must define gate outcomes for every role. "
        "Fix role mappings:\n" + "\n".join(role_mismatches)
    )
    assert not method_mismatches, (
        "RBAC_MUTATING_EXPECTATIONS keys must match expectation.method values. "
        "Fix method mappings:\n" + "\n".join(method_mismatches)
    )


@pytest.mark.parametrize(
    "rule,method",
    _route_method_cases(),
    ids=[f"{method} {rule}" for rule, method in _route_method_cases()],
)
def test_route_contract_smoke(rule: str, method: str, route_app):
    expectation = ROUTE_EXPECTATIONS[rule]

    client = route_app.test_client()
    request_fn = getattr(client, method.lower())
    response = request_fn(
        expectation.sample_path,
        headers=dict(expectation.headers),
        follow_redirects=False,
    )

    expected_status = expectation.methods[method]
    assert response.status_code == expected_status


@pytest.mark.parametrize(
    "rule,role",
    _rbac_route_cases(),
    ids=[f"{role} {rule}" for rule, role in _rbac_route_cases()],
)
def test_rbac_get_contract(rule: str, role: str, route_app, route_app_context):
    _seed_rbac_contract_data()
    expectation = RBAC_GET_EXPECTATIONS[rule]
    if rule == "/device/<the_device>/users/<the_user>":
        # Ensure at least one DEV user exists for this concrete sample path.
        _client_for_profile("dev", route_app)
    client = _client_for_profile(role, route_app)

    response = client.get(
        _resolve_seeded_device_sample_path(expectation.sample_path),
        headers=dict(expectation.headers),
        follow_redirects=False,
    )
    expected_status = expectation.by_role[role]
    if rule == "/json/v1/log/<id>":
        try:
            seeded_sched_log_id()
        except AssertionError:
            expected_status = 404
    assert response.status_code == expected_status


@pytest.mark.parametrize(
    "rule,method,role",
    _rbac_mutating_route_cases(),
    ids=[
        f"{role} {method} {rule}" for rule, method, role in _rbac_mutating_route_cases()
    ],
)
def test_rbac_mutating_contract(
    rule: str, method: str, role: str, route_app, route_app_context
):
    _seed_rbac_contract_data()
    expectation = RBAC_MUTATING_EXPECTATIONS[(rule, method)]
    client = _client_for_profile(role, route_app)
    request_fn = getattr(client, expectation.method.lower())

    response = request_fn(
        _resolve_seeded_device_sample_path(expectation.sample_path),
        headers=dict(expectation.headers),
        follow_redirects=False,
    )
    should_pass_gate = expectation.by_role[role]
    if should_pass_gate:
        assert response.status_code != 403
    else:
        assert response.status_code == 403


def test_mutating_route_methods_have_explicit_behavior_policy():
    mutating_cases = set(_mutating_route_method_cases())
    required = set(BEHAVIOR_TEST_REQUIREMENTS.keys())
    exempt = set(BEHAVIOR_TEST_EXEMPTIONS.keys())

    overlap = sorted(required & exempt)
    missing_policy = sorted(mutating_cases - required - exempt)
    stale_policy = sorted((required | exempt) - mutating_cases)

    assert not overlap, (
        "Route methods cannot be both required and exempt in behavior policy: "
        + ", ".join(_format_route_method_case(case) for case in overlap)
    )
    assert not missing_policy, (
        "Mutating route methods are missing behavior policy decisions. "
        "Add each case to BEHAVIOR_TEST_REQUIREMENTS or BEHAVIOR_TEST_EXEMPTIONS: "
        + ", ".join(_format_route_method_case(case) for case in missing_policy)
    )
    assert not stale_policy, (
        "Behavior policy contains route methods that no longer exist. "
        "Remove stale entries: "
        + ", ".join(_format_route_method_case(case) for case in stale_policy)
    )


def test_required_behavior_route_methods_have_marked_tests():
    required = set(BEHAVIOR_TEST_REQUIREMENTS.keys())
    covered = _covers_route_markers_from_tests()
    missing = sorted(required - covered)

    assert not missing, (
        "Required behavior route methods are missing @pytest.mark.covers_route tests. "
        "Add at least one test per case: "
        + ", ".join(_format_route_method_case(case) for case in missing)
    )


def test_robots_txt_body_shape(route_client):
    response = route_client.get("/robots.txt")
    assert response.status_code == 200
    assert "Disallow: /" in response.get_data(as_text=True)
