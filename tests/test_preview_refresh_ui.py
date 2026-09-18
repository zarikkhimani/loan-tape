"""Native regressions for the worksheet workspace and its recovery states."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt" and not os.environ.get("DISPLAY"), reason="Native GUI required")
@pytest.mark.parametrize("scenario", ["workbook", "xml", "states"])
@pytest.mark.parametrize("scale", [1.33, 2.0])
def test_preview_workspace(scenario, scale, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("preview_refresh_scenarios.py")),
            scenario,
            str(scale),
            str(tmp_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
