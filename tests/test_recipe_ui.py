import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt" and not os.environ.get("DISPLAY"), reason="Native GUI required")
@pytest.mark.parametrize(
    "scenario", ["review", "discard", "stale", "search-shutdown", "apply-shutdown"]
)
def test_recipe_native_workflow(scenario, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("recipe_ui_scenario.py")),
            scenario,
            str(tmp_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=50,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
