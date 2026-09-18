"""Files refresh integration checks use separate Tk interpreters and synthetic intake."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt" and not os.environ.get("DISPLAY"), reason="Native GUI required")
@pytest.mark.parametrize("scenario", ["details", "open", "formats", "layout", "scaled"])
def test_files_workspace(scenario: str, tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("files_ui_scenarios.py")),
            scenario,
            str(tmp_path),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=25,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
