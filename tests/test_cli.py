"""Exercise the installed CLI from a directory with no application source files."""

import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest


@pytest.mark.parametrize("arguments", [[], ["--help"]])
def test_help_describes_current_capabilities(arguments: list[str], tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "loan_tape", *arguments],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--version" in result.stdout
    assert "not implemented yet" in " ".join(result.stdout.split())
    assert "--ui" in result.stdout
    assert not list(tmp_path.iterdir())


def test_version_uses_installed_package_metadata(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "loan_tape", "--version"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.strip() == f"loan-tape {version('loan-tape')}"


def test_unsupported_file_processing_fails_without_touching_input(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.csv"
    original = b"loan_id,balance\n000123,1250\n"
    source.write_bytes(original)
    result = subprocess.run(
        [sys.executable, "-m", "loan_tape", str(source)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr
    assert source.read_bytes() == original
    assert list(tmp_path.iterdir()) == [source]
