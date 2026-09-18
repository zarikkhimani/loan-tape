"""Refined loan-tape exports preserve the full data set and review evidence."""

from datetime import date
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from loan_tape.date_analysis import DateBinding, DatePair, analyze_dates
from loan_tape.date_export import (
    EXPECTED_SHEETS,
    _validate_output,
    build_export_payload,
    export_date_run,
)
from loan_tape.date_parser import DateEvidence, DateProfile, DateSource
from loan_tape.date_reader import DateColumnEvidence
from loan_tape.date_runs import save_date_run
from loan_tape.inspection import InspectionError
from loan_tape.pack_format import load_pack
from loan_tape.packs import Catalog
from loan_tape.ranges import parse_range
from loan_tape.selection import SavedTable, SourceSelection
from loan_tape.workbook_index import _digest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def saved_run(tmp_path):
    pack = load_pack(ROOT / "packs/loan-dates")
    source = tmp_path / "synthetic-dates.xlsx"
    source_book = Workbook()
    source_sheet = source_book.active
    source_sheet.title = "Dates"
    source_sheet["B8"] = "Synthetic loan tape"
    source_sheet.append([])
    for cell, value in {
        "B9": "Loan ID",
        "C9": "Closing Date",
        "D9": "Maturity Date",
        "E9": "Balance",
        "B10": "0001",
        "C10": "=TODAY()",
        "D10": "2027-01-01",
        "E10": 100.25,
        "B11": "0002",
        "C11": "=DATE(2026,1,1)",
        "D11": "2028-01-01",
        "E11": 0,
    }.items():
        source_sheet[cell] = value
    source_sheet["C10"].data_type = "s"
    source_book.save(source)
    source_book.close()
    source_sha256 = _digest(source, None)
    selection = SourceSelection(source_sha256, "Dates", parse_range("B8:E11"), 9)
    table = SavedTable("b" * 32, "Synthetic dates", selection)
    closing = DateColumnEvidence(
        selection,
        3,
        "1900",
        (
            DateEvidence(
                DateSource(source_sha256, 10, 3, "Dates"),
                "text",
                "=TODAY()",
                "inlineStr",
                number_format="General",
                date_system="1900",
            ),
            DateEvidence(
                DateSource(source_sha256, 11, 3, "Dates"),
                "formula",
                "46022",
                "n",
                "46022",
                "m/d/yy",
                "1900",
                True,
                "DATE(2026,1,1)",
                (("t", "normal"),),
            ),
        ),
    )
    maturity = DateColumnEvidence(
        selection,
        4,
        "1900",
        tuple(
            DateEvidence(
                DateSource(source_sha256, row, 4, "Dates"),
                "text",
                value,
                "inlineStr",
                number_format="General",
                date_system="1900",
            )
            for row, value in ((10, "2027-01-01"), (11, "2028-01-01"))
        ),
    )
    profile = DateProfile(text_formats=("YYYY-MM-DD",), numeric_dates="excel_serial")
    analysis = analyze_dates(
        table,
        (closing, maturity),
        (
            DateBinding(3, "loan.dates:closing_date", profile),
            DateBinding(4, "loan.dates:current_maturity_date", profile),
        ),
        Catalog("default", (pack,)),
        reference_date=date(2026, 9, 17),
        pairs=(DatePair(3, 4),),
    )
    return save_date_run(analysis, tmp_path), source


def test_payload_is_complete_values_only_review_of_saved_result(saved_run):
    run, source = saved_run
    payload = build_export_payload(run, source)
    assert tuple(item["name"] for item in payload["sheets"]) == EXPECTED_SHEETS
    loan_tape = next(item for item in payload["sheets"] if item["name"] == "Loan Tape")
    assert loan_tape["header_row"] == 2
    assert loan_tape["rows"] == [
        ["Synthetic loan tape", None, None, None],
        ["Loan ID", "Closing Date", "Maturity Date", "Balance"],
        ["0001", "=TODAY()", "2027-01-01", 100.25],
        ["0002", "=DATE(2026,1,1)", "2028-01-01", 0],
    ]
    assert loan_tape["date_columns"] == [2]
    assert loan_tape["refined_date_count"] == 2
    dates = next(item for item in payload["sheets"] if item["name"] == "Date Results")
    assert len(dates["rows"]) == 4
    indexes = {name: index for index, name in enumerate(dates["headers"])}
    literal = next(row for row in dates["rows"] if row[indexes["Original value"]] == "=TODAY()")
    formula = next(row for row in dates["rows"] if row[indexes["Formula text"]])
    assert literal[indexes["Original kind"]] == "text"
    assert formula[indexes["Formula text"]] == "DATE(2026,1,1)"
    assert formula[indexes["Formula attributes"]] == '[["t","normal"]]'
    assert formula[indexes["Date system"]] == "1900"
    assert formula[indexes["Present in source"]] == "Yes"
    audit = next(item for item in payload["sheets"] if item["name"] == "Audit")
    assert ["Writer", "xlwings"] in audit["rows"]
    assert ["Analysis fingerprint", run.analysis.fingerprint] in audit["rows"]


def _write_payload_fixture(path, payload):
    book = Workbook()
    book.remove(book.active)
    for spec in payload["sheets"]:
        sheet = book.create_sheet(spec["name"])
        rows = ([spec["headers"]] if "headers" in spec else []) + spec["rows"]
        for row_number, row in enumerate(rows, start=1):
            for column_number, value in enumerate(row, start=1):
                cell = sheet.cell(row_number, column_number)
                cell.value = value
                if isinstance(value, str) and value.startswith("="):
                    cell.data_type = "s"
    book.save(path)


def test_saved_workbook_validation_reconciles_rows_and_rejects_formulas(saved_run, tmp_path):
    run, source = saved_run
    payload = build_export_payload(run, source)
    target = tmp_path / "review.xlsx"
    _write_payload_fixture(target, payload)
    counts = dict(_validate_output(target, payload))
    assert tuple(counts) == EXPECTED_SHEETS
    assert counts["Date Results"] == 5

    book = load_workbook(target)
    book["Summary"]["B2"] = "different-run"
    book.save(target)
    book.close()
    with pytest.raises(InspectionError, match="Summary!B2"):
        _validate_output(target, payload)

    _write_payload_fixture(target, payload)
    book = load_workbook(target)
    book["Date Results"]["A2"] = "=1+1"
    book.save(target)
    book.close()
    with pytest.raises(InspectionError, match="contains a formula"):
        _validate_output(target, payload)


def test_export_preflight_never_overwrites_an_existing_file(saved_run, tmp_path, monkeypatch):
    run, source = saved_run
    target = tmp_path / "existing.xlsx"
    target.write_bytes(b"keep")
    # Exercise the Windows export guard even on a Linux test runner; no writer starts.
    monkeypatch.setattr("loan_tape.date_export.sys.platform", "win32")
    with pytest.raises(FileExistsError, match="not overwritten"):
        export_date_run(run, target, source_path=source)
    assert target.read_bytes() == b"keep"


def test_export_requires_desktop_excel_platform(saved_run, tmp_path, monkeypatch):
    run, source = saved_run
    monkeypatch.setattr("loan_tape.date_export.sys.platform", "linux")
    with pytest.raises(InspectionError, match="requires Windows"):
        export_date_run(run, tmp_path / "review.xlsx", source_path=source)
