from __future__ import annotations

import ast
from pathlib import Path


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


def _module_uses_mailpit_api(tree: ast.Module) -> bool:
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module == "mailpit_api":
            return True
    return False


def _is_mailpit_xdist_group(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    path = _attribute_path(node.func)
    if path != ("pytest", "mark", "xdist_group"):
        return False
    if len(node.args) != 1:
        return False
    group = node.args[0]
    return isinstance(group, ast.Constant) and group.value == "mailpit"


def _module_has_mailpit_xdist_group(tree: ast.Module) -> bool:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "pytestmark"
            for target in node.targets
        ):
            continue
        value = node.value
        if _is_mailpit_xdist_group(value):
            return True
        if isinstance(value, (ast.List, ast.Tuple)):
            if any(_is_mailpit_xdist_group(element) for element in value.elts):
                return True
    return False


def test_mailpit_backed_test_modules_share_a_loadgroup_worker():
    tests_root = Path(__file__).resolve().parent
    violations: list[str] = []

    for path in sorted(tests_root.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if not _module_uses_mailpit_api(tree):
            continue
        if _module_has_mailpit_xdist_group(tree):
            continue
        violations.append(path.relative_to(tests_root.parent).as_posix())

    assert not violations, (
        "Mailpit-backed tests must declare pytest.mark.xdist_group('mailpit') "
        "so xdist can keep the shared inbox on one worker: " + ", ".join(violations)
    )
