"""Fictional workbook and real local dictionary setup shared by cleanup scenarios."""

from pathlib import Path
from xml.etree.ElementTree import fromstring, tostring
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook

from loan_tape.column_definitions import (
    ColumnDefinition,
    ColumnRules,
    save_column_definition,
    snapshot_field,
)
from loan_tape.intake import IntakeStore
from loan_tape.packs import PackStore
from loan_tape.ranges import parse_range
from loan_tape.selection import SavedTable, SourceSelection, TableSelections, save_tables


def prepare(work: Path, values=None):
    source = work / "fictional.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "Loans"
    sheet.append(["Borrower", "Loan ID"])
    values = (
        values
        if values is not None
        else [
            "CafÃ© Holdings",
            " Acme ",
            "e\u0301",
            "N/A",
            "",
            " \t",
            0,
            "=1+1",
            "#N/A",
            False,
            "Lost \ufffd name",
        ]
    )
    for index, value in enumerate(values, 1):
        sheet.append([value, f"000{index:018d}"])
    sheet.row_dimensions[2].hidden = True
    book.save(source)
    book.close()
    # The stdlib openpyxl fixture writer translates newlines on Windows. Encode
    # literal CRs explicitly so the saved synthetic input really contains CRLF.
    if any(isinstance(value, str) and "\r" in value for value in values):
        with ZipFile(source) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        sheet_xml = fromstring(parts["xl/worksheets/sheet1.xml"])
        for row, value in enumerate(values, 2):
            if isinstance(value, str) and "\r" in value:
                sheet_xml.find(f'.//{{*}}c[@r="A{row}"]/{{*}}is/{{*}}t').text = value
        parts["xl/worksheets/sheet1.xml"] = tostring(sheet_xml).replace(b"\r", b"&#13;")
        with ZipFile(source, "w", ZIP_DEFLATED) as archive:
            for name, data in parts.items():
                archive.writestr(name, data)
    intake = IntakeStore(work / "inputs")
    record = intake.save_path(source)
    saved = Path(intake.describe(record)["saved_path"])
    table = SavedTable(
        "1" * 32,
        "Fictional loans",
        SourceSelection(record["sha256"], "Loans", parse_range(f"A1:B{len(values) + 2}"), 1),
    )
    save_tables(TableSelections(table.selection.workbook_sha256, (table,), table.id))
    store = PackStore(Path(__file__).parents[1] / "packs", work / ".artifacts/packs")
    store.activate("loan.text")
    store.activate("example.loans")
    catalog = store.catalog()
    for column, header, field_id in (
        (1, "Borrower", "loan.text:borrower_name"),
        (2, "Loan ID", "example.loans:loan_id"),
    ):
        save_column_definition(
            table,
            ColumnDefinition(
                column,
                header,
                snapshot_field(catalog, catalog.get_field(field_id)),
                rules=ColumnRules(missing_tokens=("N/A",)),
            ),
        )
    return source, saved, intake, table, store
