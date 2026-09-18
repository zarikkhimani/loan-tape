"""Each native scenario runs in its own process, matching real application launches."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.name != "nt" and not os.environ.get("DISPLAY"),
    reason="Desktop integration requires a graphical display; use Xvfb on headless Linux.",
)


@pytest.mark.parametrize(
    "scenario",
    [
        "drop",
        "browse",
        "multiple",
        "invalid",
        "empty",
        "close_busy",
        "legacy",
        "restart",
        "session",
        "inspect_csv",
        "inspect_excel",
        "inspect_mapping_profile",
        "inspect_date_setup",
        "inspect_navigation",
        "inspect_tables",
        "inspect_suggestions",
        "inspect_column",
        "inspect_column_cancel",
        "inspect_column_error",
        "inspect_check_column",
        "inspect_check_cancel",
        "inspect_check_error",
        "inspect_check_delivery",
        "inspect_scan_close",
        "inspect_comparison",
        "inspect_error",
        "inspect_close_busy",
    ],
)
def test_desktop_scenario(scenario: str, tmp_path: Path) -> None:
    script = Path(__file__).with_name("desktop_scenarios.py")
    steps = ["create", "reopen"] if scenario == "restart" else [scenario]
    for step in steps:
        result = subprocess.run(
            [sys.executable, str(script), step, str(tmp_path)],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
