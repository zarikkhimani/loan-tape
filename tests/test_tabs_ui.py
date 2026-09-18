"""File tabs preserve native preview state and isolate closing from shutdown."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.name != "nt" and not os.environ.get("DISPLAY"), reason="Requires a desktop display"
)


@pytest.mark.parametrize("scenario", ["csv", "excel", "busy"])
def test_workspace_tabs(scenario, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("tabs_scenarios.py")),
            scenario,
            str(tmp_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 0, result.stdout + result.stderr
