"""Complete, source-linked, read-only data-set ordering."""

import hashlib
from datetime import UTC, datetime

import pytest
from openpyxl import Workbook

from loan_tape.column_order import ORDER_MODES, order_data_set
from loan_tape.inspection import InspectionError
from loan_tape.ranges import parse_range
from loan_tape.selection import SavedTable, SourceSelection
from loan_tape.session import AnalysisSession
from loan_tape.xml_selection import SavedXmlTable

SESSION = AnalysisSession("order-test", datetime(2026, 9, 17, tzinfo=UTC))


def table_for(path):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return SavedTable(
        "1" * 32,
        "Loans",
        SourceSelection(digest, "Loans", parse_range("A1:C9"), 1),
    )


def test_complete_data_set_keeps_rows_together_while_ordering_one_column(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "order.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "Loans"
    for row in (
        ("Value", "Borrower", "Balance"),
        ("beta", "B", 20),
        ("Alpha", "A", 10),
        (10, "ten", 100),
        (2, "two", 200),
        (None, "blank", 300),
        ("alpha", "a2", 40),
        ("0007", "id", 70),
        ("", "empty", 80),
    ):
        sheet.append(row)
    book.save(path)
    book.close()
    before = path.read_bytes()

    result = order_data_set(path, table_for(path), 1, SESSION)
    try:
        assert result.total_rows == 8
        assert result.total_columns == 3
        assert result.column_labels == ("Value", "Borrower", "Balance")
        assert result.numeric_rows == 2
        page = result.page("A–Z")
        assert tuple(row.sort_cell.text for row in page.rows) == (
            "0007",
            "10",
            "2",
            "Alpha",
            "alpha",
            "beta",
            "",
            "",
        )
        assert tuple(cell.text for cell in page.rows[0].cells) == ("0007", "id", "70")
        assert [row.sort_cell.text for row in result.page("Ascending").rows[:2]] == [
            "2",
            "10",
        ]
        assert [row.sort_cell.text for row in result.page("Descending").rows[:2]] == [
            "10",
            "2",
        ]
        window = result.page("A–Z", 2, 2, column_offset=1, column_limit=2)
        assert window.rows[0].source_row == 5
        assert tuple(cell.text for cell in window.rows[0].cells) == ("two", "200")
        assert window.column_labels == ("Borrower", "Balance")
        assert result.page("Z–A").rows[-1].sort_cell.kind in {"Blank", "Empty text"}
        assert path.read_bytes() == before
        with pytest.raises(InspectionError, match="available ordering"):
            result.page("Oldest first")
    finally:
        result.close()

    assert list((tmp_path / ".artifacts/column-order").iterdir()) == []


def test_xml_ordering_retains_every_field_and_explicit_absence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "loans.xml"
    path.write_text(
        "<root><loan><id>2</id><name>B</name></loan>"
        "<loan><id>1</id><name>A</name><balance>5</balance></loan></root>",
        encoding="utf-8",
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    table = SavedXmlTable(
        "2" * 32,
        "XML loans",
        digest,
        ("root", "loan"),
        "/root/loan",
        2,
        3,
    )

    result = order_data_set(path, table, 1, SESSION)
    try:
        page = result.page("A–Z")
        assert result.column_labels == ("id", "name", "balance")
        assert [row.source_row for row in page.rows] == [2, 1]
        assert tuple(cell.text for cell in page.rows[0].cells) == ("1", "A", "5")
        assert tuple(cell.text for cell in page.rows[1].cells) == ("2", "B", "")
        assert page.rows[1].cells[2].presence == "Absent"
        assert "absent field: balance" in (page.rows[1].cells[2].source_path or "")
    finally:
        result.close()


def test_order_modes_are_stable_user_choices():
    assert ORDER_MODES == ("A–Z", "Z–A", "Ascending", "Descending")
