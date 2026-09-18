import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt" and not os.environ.get("DISPLAY"), reason="Native GUI required")
def test_column_definition_editor(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("column_definition_ui_scenario.py")),
            str(tmp_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
