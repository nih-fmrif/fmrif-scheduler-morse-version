from __future__ import annotations

import pytest
from jinja2 import meta
from route_seed import seeded_template_compatibility

from scheduler import logic, model


class _TemplateFallbackValue(str):
    def __new__(cls):
        return super().__new__(cls, "")

    def __str__(self) -> str:
        return ""

    def __repr__(self) -> str:
        return ""

    def __bool__(self) -> bool:
        return False

    def __len__(self) -> int:
        return 0

    def __iter__(self):
        return iter(())

    def __contains__(self, _item) -> bool:
        return False

    def __getattr__(self, _name: str):
        return self

    def __getitem__(self, _key):
        return self

    def __call__(self, *_args, **_kwargs):
        return self

    def __int__(self) -> int:
        return 0

    def __float__(self) -> float:
        return 0.0

    def __eq__(self, _other) -> bool:
        return False

    def __lt__(self, _other) -> bool:
        return False

    def __gt__(self, _other) -> bool:
        return False

    def __le__(self, _other) -> bool:
        return False

    def __ge__(self, _other) -> bool:
        return False


_FALLBACK = _TemplateFallbackValue()


def _html_templates(app) -> list[str]:
    return sorted(
        name
        for name in app.jinja_env.list_templates()
        if name.lower().endswith(".html")
    )


def _all_undeclared_template_variables(app, templates: list[str]) -> set[str]:
    undeclared: set[str] = set()
    for template_name in templates:
        source = app.jinja_loader.get_source(app.jinja_env, template_name)[0]
        parsed = app.jinja_env.parse(source)
        undeclared.update(meta.find_undeclared_variables(parsed))
    return undeclared


def _fallback_render_context(app, undeclared: set[str]) -> dict[str, object]:
    context: dict[str, object] = {}
    app.update_template_context(context)
    for variable_name in undeclared:
        if variable_name in context or variable_name in app.jinja_env.globals:
            continue
        context[variable_name] = _FALLBACK
    return context


def test_template_validation(app_context):
    device = model.Device(id="test_scanner", label="Test Scanner")

    # Test empty templates
    errors = logic.validate_templates_before_application(device, "")
    assert "no templates to apply" in errors

    # Test invalid template
    errors = logic.validate_templates_before_application(device, "invalid_template")
    assert "invalid template codes provided" in errors


def test_normalize_template_group():
    assert logic.normalize_template_group(None) is None
    assert logic.normalize_template_group("") is None
    assert logic.normalize_template_group("(none)") is None
    assert logic.normalize_template_group("DEV") == "DEV"


@pytest.mark.route
def test_seeded_template_compatibility_flags_legacy_member(route_app_context):
    _, _, report = seeded_template_compatibility(
        archived=False,
        require_blocking=True,
        issue_code="legacy-member",
    )

    assert report["blocking"] is True
    assert any(issue["code"] == "legacy-member" for issue in report["issues"])
    assert any("stale member" in summary.lower() for summary in report["summary"])


def test_verify_template_diffs():
    institutes = [("inst1", "Institute 1")]
    groups = [("group1", "Group 1")]
    members = {"group1": [("user1", "User 1")]}

    diffs = [{"id": 1, "inst": ["old", "new"]}]
    entries = [model.TemplateEntry(id=1)]

    errors, staged = logic.verify_and_prep_template_diffs(
        diffs, entries, institutes, groups, members
    )
    assert len(errors) > 0


def test_all_templates_compile(app):
    templates = _html_templates(app)
    assert templates

    errors: list[str] = []

    for template_name in templates:
        try:
            app.jinja_env.get_template(template_name)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{template_name}: {type(exc).__name__}: {exc!s}")

    assert not errors, "Template compile failures:\n" + "\n".join(errors)


def test_all_templates_render_smoke_with_fallback_context(app):
    templates = _html_templates(app)
    undeclared_variables = _all_undeclared_template_variables(app, templates)

    errors: list[str] = []

    with app.test_request_context("/"):
        context = _fallback_render_context(app, undeclared_variables)
        for template_name in templates:
            try:
                app.jinja_env.get_template(template_name).render(dict(context))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{template_name}: {type(exc).__name__}: {exc!s}")

    assert not errors, "Template render failures:\n" + "\n".join(errors)
