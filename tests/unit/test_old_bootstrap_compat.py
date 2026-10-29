import os
import subprocess
import sys
from pathlib import Path

import pytest

RUN_OLD_BOOTSTRAP_COMPAT = os.getenv(
    "OLD_BOOTSTRAP_COMPAT_RUN", ""
).strip().lower() in {"1", "true", "yes"}
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(
    not RUN_OLD_BOOTSTRAP_COMPAT,
    reason="Set OLD_BOOTSTRAP_COMPAT_RUN=true to verify old-bootstrap compatibility.",
)
def test_current_bootstrap_accepts_old_bootstrap_data_in_pre_and_post_018_modes():
    script = PROJECT_ROOT / "scripts" / "verify-old-bootstrap-compat.py"
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=1800,
        check=False,
    )
    output = "\n".join(part for part in (proc.stdout, proc.stderr) if part).strip()
    assert proc.returncode == 0, output
