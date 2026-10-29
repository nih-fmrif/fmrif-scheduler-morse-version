from __future__ import annotations

import importlib.util
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPENDENCY_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)"
    r"(?:\[(?P<extras>[A-Za-z0-9_.\-, ]+)\])?"
    r"(?P<specifier>.*)$"
)


def _load_wrapper_module():
    script_path = REPO_ROOT / "scripts" / "run-target-aware-pytest-suite.py"
    spec = importlib.util.spec_from_file_location(
        "run_target_aware_pytest_suite",
        script_path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _normalize_project_dependencies(raw_dependencies: list[str]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for raw_dependency in raw_dependencies:
        match = DEPENDENCY_RE.match(raw_dependency.strip())
        assert match is not None, raw_dependency
        name = match.group("name").strip().lower()
        extras = match.group("extras")
        specifier = match.group("specifier").strip()
        assert specifier, raw_dependency
        if extras:
            normalized[name] = {
                "version": specifier,
                "extras": [part.strip() for part in extras.split(",") if part.strip()],
            }
        else:
            normalized[name] = specifier
    return normalized


def test_fast_pytest_tasks_use_target_aware_wrapper():
    pixi_data = tomllib.loads((REPO_ROOT / "pixi.toml").read_text(encoding="utf-8"))
    pyproject_data = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    tasks = pixi_data["tasks"]
    environments = pixi_data["environments"]
    default_pypi_deps = pixi_data.get("pypi-dependencies", {})
    dev_pypi_deps = pixi_data["feature"]["dev"]["pypi-dependencies"]
    project_pypi_deps = _normalize_project_dependencies(
        pyproject_data["project"]["dependencies"]
    )
    project_dev_pypi_deps = _normalize_project_dependencies(
        pyproject_data["project"]["optional-dependencies"]["dev"]
    )
    alembic_config = pyproject_data["tool"]["alembic"]

    assert tasks["serve"] == "bash scripts/serve.sh"
    assert tasks["serve-gunicorn"] == "APP_SERVER=gunicorn bash scripts/serve.sh"
    assert pixi_data["workspace"]["requires-pixi"] == ">=0.66.0"
    assert environments["default"]["features"] == []
    assert environments["dev"]["features"] == ["dev"]
    assert default_pypi_deps == project_pypi_deps
    assert dev_pypi_deps == project_dev_pypi_deps
    assert alembic_config == {
        "script_location": "%(here)s/scheduler/alembic",
        "version_locations": ["%(here)s/scheduler/alembic/versions"],
        "prepend_sys_path": ["%(here)s"],
    }
    assert tasks["install-js"] == "pixi run -e dev npm ci --no-optional"
    assert tasks["pre-commit-install"] == "bash scripts/install-pre-commit-hook.sh"
    assert (
        tasks["pre-commit"] == "pixi run -e dev bash -lc 'pre-commit run --all-files'"
    )
    assert tasks["check-db-health"] == "python3 scripts/check-db-health.py"
    assert tasks["check-db-posture"] == "python3 scripts/check-db-posture.py"
    assert (
        tasks["rehearse-initial-deployment"]
        == "python3 -m scheduler.deployment_rehearsal"
    )
    assert (
        tasks["test-unit"]
        == 'pixi run -e dev python3 scripts/run-target-aware-pytest-suite.py unit tests/unit "not route"'
    )
    assert (
        tasks["test-unit-xdist"]
        == 'pixi run -e dev python3 scripts/run-target-aware-pytest-suite.py unit tests/unit "not route" -- -n auto --dist loadgroup'
    )
    assert (
        tasks["test-routes"]
        == "pixi run -e dev python3 scripts/run-target-aware-pytest-suite.py routes tests/unit route"
    )
    assert (
        tasks["test-routes-xdist"]
        == "pixi run -e dev python3 scripts/run-target-aware-pytest-suite.py routes tests/unit route -- -n auto --dist loadgroup"
    )
    assert tasks["run-db-backup"] == "python3 scripts/run-db-backup.py"
    assert tasks["run-db-restore-drill"] == "python3 scripts/run-db-restore-drill.py"


def test_wrapper_uses_default_target_when_no_explicit_selector_is_present():
    module = _load_wrapper_module()

    assert module.build_command("routes", "tests/unit", "route", ["-q"]) == [
        "bash",
        "scripts/run-isolated-test-suite.sh",
        "routes",
        "python3",
        "-m",
        "pytest",
        "tests/unit",
        "-m",
        "route",
        "-q",
    ]


def test_wrapper_drops_default_target_when_explicit_selector_is_present():
    module = _load_wrapper_module()

    assert module.build_command(
        "routes",
        "tests/unit",
        "route",
        ["tests/unit/test_device_mutating_routes.py", "-q"],
    ) == [
        "bash",
        "scripts/run-isolated-test-suite.sh",
        "routes",
        "python3",
        "-m",
        "pytest",
        "-m",
        "route",
        "tests/unit/test_device_mutating_routes.py",
        "-q",
    ]


def test_dockerfile_uses_pixi_managed_environment_without_ad_hoc_pip_installs():
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "pixi.sh/install.sh" in dockerfile
    assert '"${PIXI_HOME}/bin/pixi" install' in dockerfile
    assert "--manifest-path /app/pixi.toml" in dockerfile
    assert "--environment default" in dockerfile
    assert "COPY pixi.toml ." in dockerfile
    assert "COPY pixi.lock ." not in dockerfile
    assert "pip install" not in dockerfile
    assert "uv sync" not in dockerfile


def test_entrypoint_uses_pyproject_backed_alembic_runner():
    entrypoint = (REPO_ROOT / "entrypoint.sh").read_text(encoding="utf-8")

    assert '"$python_bin" -m scheduler.alembic_runner upgrade head' in entrypoint
