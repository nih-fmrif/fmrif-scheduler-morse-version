from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


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


def test_fast_pytest_tasks_use_target_aware_wrapper():
    pixi_data = tomllib.loads((REPO_ROOT / "pixi.toml").read_text(encoding="utf-8"))
    tasks = pixi_data["tasks"]

    assert tasks["serve"] == "bash scripts/serve.sh"
    assert tasks["serve-gunicorn"] == "APP_SERVER=gunicorn bash scripts/serve.sh"
    assert (
        tasks["test-unit"]
        == 'python3 scripts/run-target-aware-pytest-suite.py unit tests/unit "not route"'
    )
    assert (
        tasks["test-unit-xdist"]
        == 'python3 scripts/run-target-aware-pytest-suite.py unit tests/unit "not route" -- -n auto'
    )
    assert (
        tasks["test-routes"]
        == "python3 scripts/run-target-aware-pytest-suite.py routes tests/unit route"
    )


def test_wrapper_uses_default_target_when_no_explicit_selector_is_present():
    module = _load_wrapper_module()

    assert module.build_command("routes", "tests/unit", "route", ["-q"]) == [
        "bash",
        "scripts/run-isolated-test-suite.sh",
        "routes",
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
