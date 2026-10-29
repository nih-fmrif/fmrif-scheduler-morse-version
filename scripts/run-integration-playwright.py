#!/usr/bin/env python3
"""Run Playwright integration tests with explicit argument normalization."""

from __future__ import annotations

import os
import sys

DEFAULT_INTEGRATION_TEST_PATH = "tests/playwright/integration"


def normalize_arguments(raw_args: list[str]) -> list[str]:
    """Normalize args in a way that mirrors the historical shell wrapper behavior."""

    args = list(raw_args)
    if args and args[0] == "--":
        args = args[1:]

    normalized: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]

        if arg == "--":
            if index + 1 < len(args):
                next_arg = args[index + 1]
                if next_arg.startswith("--") or (
                    next_arg.startswith("-") and len(next_arg) > 1
                ):
                    index += 1
                    continue
            normalized.append(arg)
            index += 1
            continue

        if arg == "--project":
            if index + 1 >= len(args):
                raise SystemExit("ERROR: --project requires a value.")
            index += 1
            normalized.append(f"--project={args[index]}")
            index += 1
            continue

        normalized.append(arg)
        index += 1

    return normalized


def main() -> int:
    args = normalize_arguments(sys.argv[1:])

    if not args:
        args = [DEFAULT_INTEGRATION_TEST_PATH]

    has_positional_arg = any(
        arg not in ("--",) and not arg.startswith("-") for arg in args
    )
    if not has_positional_arg:
        args.append(DEFAULT_INTEGRATION_TEST_PATH)

    command = ["npx", "playwright", "test", *args]
    os.execvp(command[0], command)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
