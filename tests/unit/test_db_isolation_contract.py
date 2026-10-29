from __future__ import annotations

import ast
from pathlib import Path

ISOLATION_FIXTURES = {
    "app",
    "app_context",
    "client",
    "runner",
    "route_app",
    "route_app_context",
    "route_client",
}
ROUTE_FIXTURES = {
    "route_app",
    "route_app_context",
    "route_client",
}


def _attribute_path(node: ast.AST) -> tuple[str, ...] | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return tuple(reversed(parts))


def _is_pytest_route_mark(node: ast.AST) -> bool:
    if isinstance(node, ast.Call):
        return _is_pytest_route_mark(node.func)
    path = _attribute_path(node)
    return path == ("pytest", "mark", "route")


def _module_is_route_marked(tree: ast.Module) -> bool:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "pytestmark":
                if _is_pytest_route_mark(node.value):
                    return True
                if isinstance(node.value, (ast.List, ast.Tuple)):
                    for element in node.value.elts:
                        if _is_pytest_route_mark(element):
                            return True
    return False


def _function_is_route_marked(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(_is_pytest_route_mark(decorator) for decorator in node.decorator_list)


def _touches_db_state(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Attribute):
            continue
        path = _attribute_path(child)
        if path is None or not path or path[0] != "model":
            continue
        if len(path) >= 2 and path[1] == "db":
            return True
        if len(path) >= 3 and path[2] == "query":
            return True
    return False


def _imports_global_scheduler_app(tree: ast.Module) -> bool:
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module != "scheduler.app":
            continue
        if any(alias.name == "app" for alias in node.names):
            return True
    return False


def _fixture_args(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    return {
        arg.arg
        for arg in (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        )
    }


def test_db_access_tests_require_isolation_entrypoints():
    tests_root = Path(__file__).resolve().parent
    this_file = Path(__file__).name

    global_app_imports: list[str] = []
    isolation_violations: list[str] = []
    route_mark_violations: list[str] = []

    for path in sorted(tests_root.glob("test_*.py")):
        if path.name == this_file:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module_is_route = _module_is_route_marked(tree)

        if _imports_global_scheduler_app(tree):
            global_app_imports.append(path.name)

        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            fixture_args = _fixture_args(node)
            uses_route_fixture = bool(fixture_args & ROUTE_FIXTURES)
            is_route = module_is_route or _function_is_route_marked(node)
            if uses_route_fixture and not is_route:
                route_mark_violations.append(f"{path.name}::{node.name}")
            if not _touches_db_state(node):
                continue

            has_isolation_fixture = bool(fixture_args & ISOLATION_FIXTURES)
            if not (has_isolation_fixture or is_route):
                isolation_violations.append(f"{path.name}::{node.name}")

    assert not global_app_imports, (
        "Route tests must use fixture-backed app access instead of importing a "
        "module-level app singleton: " + ", ".join(sorted(global_app_imports))
    )
    assert not route_mark_violations, (
        "Tests using route fixtures must be route-marked so they do not run in "
        "pixi run test-unit: " + ", ".join(sorted(route_mark_violations))
    )
    assert not isolation_violations, (
        "Tests touching DB state must be route-marked or request an isolation "
        f"fixture ({sorted(ISOLATION_FIXTURES)}): "
        + ", ".join(sorted(isolation_violations))
    )
