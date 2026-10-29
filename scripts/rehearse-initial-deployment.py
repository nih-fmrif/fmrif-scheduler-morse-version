#!/usr/bin/env python3
from __future__ import annotations

try:
    from scheduler.deployment_rehearsal import main
except ImportError as exc:
    raise SystemExit(
        "Could not import the scheduler package. "
        "Run 'pixi run rehearse-initial-deployment' or "
        "'python3 -m scheduler.deployment_rehearsal' instead."
    ) from exc


if __name__ == "__main__":
    raise SystemExit(main())
