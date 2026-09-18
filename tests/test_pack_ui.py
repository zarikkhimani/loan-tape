"""Run each native pack lifecycle scenario in a separate Tcl interpreter."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt" and not os.environ.get("DISPLAY"), reason="Needs a display")
@pytest.mark.parametrize("scenario", ["lifecycle", "errors", "closing", "layout"])
def test_pack_desktop(scenario: str, tmp_path: Path) -> None:
    script = Path(__file__).with_name("pack_ui_scenarios.py")
    result = subprocess.run(
        [sys.executable, str(script), scenario],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=25,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
