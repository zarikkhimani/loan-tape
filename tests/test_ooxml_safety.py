"""Every workbook reader shares package-level expansion and path limits."""

import hashlib
from datetime import UTC, datetime
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from openpyxl import Workbook

from loan_tape import ooxml_safety
from loan_tape.column_order import order_data_set
from loan_tape.column_profile import inspect_column
from loan_tape.date_reader import read_excel_date_columns
from loan_tape.excel_compare import check_excel_input
from loan_tape.inspection import InspectionError, read_preview
from loan_tape.ooxml_safety import OoxmlLimits, validate_ooxml_archive
from loan_tape.ranges import parse_range
from loan_tape.selection import SavedTable, SourceSelection
from loan_tape.session import AnalysisSession
from loan_tape.workbook_index import scan_workbook


def workbook(path):
    book = Workbook()
    book.active.title = "Loans"
    book.active.append(["Date"])
    book.active.append([45000])
    book.save(path)
    book.close()


def test_unsafe_member_names_and_expansion_are_rejected(tmp_path):
    path = tmp_path / "unsafe.xlsx"
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("../outside.xml", b"x")
    with ZipFile(path) as archive, pytest.raises(ValueError, match="unsafe part name"):
        validate_ooxml_archive(archive)

    path = tmp_path / "expanded.xlsx"
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"x" * 20)
    limits = OoxmlLimits(max_total_bytes=10)
    with ZipFile(path) as archive, pytest.raises(ValueError, match="expanded-size"):
        validate_ooxml_archive(archive, limits=limits)


def test_all_source_workbook_paths_apply_the_shared_budget(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "source.xlsx"
    workbook(path)
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    selection = SourceSelection(sha256, "Loans", parse_range("A1:A2"), 1)
    table = SavedTable("1" * 32, "Loans", selection)
    session = AnalysisSession("session", datetime(2026, 9, 17, tzinfo=UTC))
    monkeypatch.setattr(ooxml_safety, "DEFAULT_LIMITS", OoxmlLimits(max_total_bytes=1))

    readers = (
        lambda: read_preview(path),
        lambda: scan_workbook(path),
        lambda: inspect_column(path, table, 1, session),
        lambda: order_data_set(path, table, 1, session),
        lambda: read_excel_date_columns(path, selection, (1,)),
        lambda: check_excel_input(path),
    )
    for reader in readers:
        with pytest.raises(InspectionError, match="expanded-size"):
            reader()
