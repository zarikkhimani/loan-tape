"""The manual action opens the exact saved file in Excel, not its default app."""

import subprocess
from unittest.mock import patch

import pytest

from loan_tape import excel_process
from loan_tape.inspection import InspectionError


@pytest.mark.parametrize("extension", [".csv", ".xlsx"])
def test_launches_excel_with_quoted_saved_path(tmp_path, extension):
    source = tmp_path / ("Saved data & notes (1)" + extension)
    source.write_bytes(b"preserved source")
    with (
        patch.object(excel_process.sys, "platform", "win32"),
        patch.object(
            excel_process,
            "excel_executable",
            return_value=r"C:\Program Files\Microsoft Office\EXCEL.EXE",
        ),
        patch.object(excel_process.os, "startfile", create=True) as start,
    ):
        excel_process.open_in_excel(source)
        start.assert_called_once_with(
            r"C:\Program Files\Microsoft Office\EXCEL.EXE",
            "open",
            subprocess.list2cmdline([str(source.resolve())]),
        )
    assert source.read_bytes() == b"preserved source"


def test_missing_file_is_not_launched(tmp_path):
    with (
        patch.object(excel_process.sys, "platform", "win32"),
        patch.object(excel_process.os, "startfile", create=True) as start,
    ):
        with pytest.raises(FileNotFoundError, match="saved data file"):
            excel_process.open_in_excel(tmp_path / "missing.csv")
        start.assert_not_called()


def test_missing_excel_reports_failure_without_using_default_app(tmp_path):
    source = tmp_path / "data.csv"
    source.write_text("id\n0001\n")
    with (
        patch.object(excel_process.sys, "platform", "win32"),
        patch.object(
            excel_process,
            "excel_executable",
            side_effect=InspectionError("Desktop Excel is not registered"),
        ),
        patch.object(excel_process.os, "startfile", create=True) as start,
    ):
        with pytest.raises(InspectionError, match="not registered"):
            excel_process.open_in_excel(source)
        start.assert_not_called()
