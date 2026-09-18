"""Native content editing runs against temporary synthetic sources in fresh processes."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt" and not os.environ.get("DISPLAY"), reason="Needs a display")
@pytest.mark.parametrize(
    "scenario", ["sources", "codes", "citations", "closing", "removal", "layout", "layout_scaled"]
)
def test_pack_content_editor(scenario, tmp_path):
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("pack_content_scenarios.py")), scenario],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 0, result.stdout + result.stderr
