#!/usr/bin/env python3
from __future__ import annotations

import os
import sys


def _usage() -> str:
    return (
        "Usage:\n"
        "  run-target-aware-pytest-suite.py <suite> <default-target> <marker> [-- <pytest args...>]\n\n"
        "Policy:\n"
        "  - When explicit test selectors are supplied, they win.\n"
        "  - Default collection roots apply only when no explicit selector is present.\n"
        "  - Task interfaces must not silently widen a narrowed test request.\n"
    )


def _normalize_user_args(user_args: list[str]) -> list[str]:
    if user_args and user_args[0] == "--":
        return user_args[1:]
    return list(user_args)


def has_explicit_selector(user_args: list[str]) -> bool:
    for arg in user_args:
        normalized = arg.removeprefix("./")
        if "::" in arg:
            return True
        if arg.endswith(".py"):
            return True
        if normalized == "tests" or normalized.startswith("tests/"):
            return True
        if "/tests/" in arg:
            return True
    return False


def build_command(
    suite: str,
    default_target: str,
    marker: str,
    user_args: list[str],
) -> list[str]:
    normalized_args = _normalize_user_args(user_args)
    command = [
        "bash",
        "scripts/run-isolated-test-suite.sh",
        suite,
        "python3",
        "-m",
        "pytest",
    ]
    if has_explicit_selector(normalized_args):
        command.extend(["-m", marker, *normalized_args])
        return command
    command.extend([default_target, "-m", marker, *normalized_args])
    return command


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        sys.stderr.write(_usage())
        return 1

    suite = argv[1]
    default_target = argv[2]
    marker = argv[3]
    user_args = argv[4:]

    command = build_command(suite, default_target, marker, user_args)
    os.execvp(command[0], command)
    raise AssertionError("os.execvp should not return")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
