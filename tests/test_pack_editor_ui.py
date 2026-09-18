"""Each authoring scenario uses a fresh native desktop process."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt" and not os.environ.get("DISPLAY"), reason="Needs a display")
@pytest.mark.parametrize(
    "scenario", ["new", "edit", "copy", "conflict", "closing", "layout", "roundtrip"]
)
def test_pack_editor(scenario, tmp_path):
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("pack_editor_scenarios.py")), scenario],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 0, result.stdout + result.stderr
