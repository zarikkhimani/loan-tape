"""Run each XML desktop case in an isolated Tk process."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt" and not os.environ.get("DISPLAY"), reason="Native GUI required")
@pytest.mark.parametrize("scenario", ["preview", "error", "close"])
def test_xml_uses_existing_preview(scenario, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("xml_desktop_scenarios.py")),
            scenario,
            str(tmp_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=25,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(os.name != "nt" and not os.environ.get("DISPLAY"), reason="Native GUI required")
@pytest.mark.parametrize("scenario", ["navigation", "settings_error", "save_failure", "changed"])
def test_xml_stage2(scenario, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("xml_stage2_scenarios.py")),
            scenario,
            str(tmp_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(os.name != "nt" and not os.environ.get("DISPLAY"), reason="Native GUI required")
@pytest.mark.parametrize("scenario", ["review", "changed", "scope", "cancel", "shutdown"])
def test_xml_stage3(scenario, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("xml_stage3_scenarios.py")),
            scenario,
            str(tmp_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(os.name != "nt" and not os.environ.get("DISPLAY"), reason="Native GUI required")
@pytest.mark.parametrize("scenario", ["invalid", "valid", "error", "cancel", "shutdown"])
def test_xml_stage4(scenario, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("xml_stage4_scenarios.py")),
            scenario,
            str(tmp_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
