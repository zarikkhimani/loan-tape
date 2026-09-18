"""Private xlwings writer used only by the owned date-export process."""

from __future__ import annotations

import atexit
import importlib
import json
import sys
import time
from collections.abc import Set
from datetime import datetime
from pathlib import Path
from typing import Any

NAVY = (31, 78, 121)
GREEN = (55, 86, 35)
PALE_BLUE = (217, 234, 247)
PALE_RED = (252, 228, 214)
PALE_AMBER = (255, 242, 204)
PALE_GREEN = (226, 239, 218)
LIGHT_GRAY = (242, 242, 242)
WHITE = (255, 255, 255)
TEXT = (38, 38, 38)
MAX_CHUNK_ROWS = 5000


def _matrix(rows: list[list[Any]], width: int) -> list[list[Any]]:
    return [row + [None] * (width - len(row)) for row in rows]


def _excel_values(rows: list[list[Any]], date_columns: Set[int]) -> list[list[Any]]:
    result = []
    for row in rows:
        values = []
        for index, value in enumerate(row):
            if isinstance(value, str):
                if not value:
                    value = None
                elif index in date_columns:
                    try:
                        value = datetime.fromisoformat(value)
                    except ValueError:
                        value = "'" + value
                else:
                    value = "'" + value
            values.append(value)
        result.append(values)
    return result


def _write_rows(
    sheet: Any,
    start: int,
    rows: list[list[Any]],
    width: int,
    *,
    date_columns: set[int] | frozenset[int] = frozenset(),
) -> None:
    if not rows:
        return
    for offset in range(0, len(rows), MAX_CHUNK_ROWS):
        chunk = _matrix(rows[offset : offset + MAX_CHUNK_ROWS], width)
        chunk = _excel_values(chunk, date_columns)
        target = sheet.range((start + offset, 1), (start + offset + len(chunk) - 1, width))
        target.value = chunk
        target.api.VerticalAlignment = -4108  # xlCenter


def _sheet_window(app: Any, sheet: Any, freeze_row: int | None = None) -> None:
    sheet.activate()
    window = app.api.ActiveWindow
    window.DisplayGridlines = False
    window.Zoom = 90
    if freeze_row is not None:
        window.FreezePanes = False
        window.SplitRow = freeze_row
        window.SplitColumn = 0
        window.FreezePanes = True


def _header(row: Any, *, fill: tuple[int, int, int] = NAVY) -> None:
    row.color = fill
    row.font.color = WHITE
    row.font.bold = True
    row.api.HorizontalAlignment = -4108  # xlCenter
    row.api.VerticalAlignment = -4108
    row.api.Borders(9).Color = 0xFFFFFF  # xlEdgeBottom


def _title(cell: Any) -> None:
    cell.font.name = "Arial"
    cell.font.size = 15
    cell.font.bold = True
    cell.font.color = NAVY


def _base(sheet: Any, used: Any) -> None:
    used.font.name = "Arial"
    used.font.size = 10
    used.font.color = TEXT
    used.api.VerticalAlignment = -4108


def _format_summary(app: Any, sheet: Any, rows: list[list[Any]]) -> None:
    width = max(map(len, rows))
    _write_rows(sheet, 1, rows, width, date_columns={4, 5})
    used = sheet.range((1, 1), (len(rows), width))
    _base(sheet, used)
    _title(sheet.range("A1"))
    for row_number, row in enumerate(rows, start=1):
        label = row[0] if row else None
        if label in {"Review summary", "Mapped columns"}:
            band = sheet.range((row_number, 1), (row_number, width))
            band.color = GREEN
            band.font.color = WHITE
            band.font.bold = True
        elif label == "Source column":
            _header(sheet.range((row_number, 1), (row_number, width)))
            if row_number < len(rows):
                sheet.range((row_number + 1, 3), (len(rows), 4)).number_format = "#,##0;(#,##0);-"
                sheet.range((row_number + 1, 5), (len(rows), 6)).number_format = "mm/dd/yy"
    sheet.range("A:A").column_width = 43
    sheet.range("B:B").column_width = 32
    sheet.range("C:D").column_width = 14
    sheet.range("E:F").column_width = 14
    sheet.range("A1:F1").api.Borders(9).Color = 0x1F4E78
    _sheet_window(app, sheet)


def _format_loan_tape(app: Any, sheet: Any, specification: dict[str, Any]) -> None:
    rows = specification["rows"]
    widths = specification["widths"]
    width = len(widths)
    date_columns = set(specification["date_columns"])
    _write_rows(sheet, 1, rows, width, date_columns=date_columns)
    last = max(1, len(rows))
    used = sheet.range((1, 1), (last, width))
    _base(sheet, used)
    header_row = specification["header_row"]
    if header_row is not None:
        _header(sheet.range((header_row, 1), (header_row, width)))
    for index, size in enumerate(widths, start=1):
        sheet.range((1, index)).column_width = size
    for column in date_columns:
        first = header_row + 1 if header_row is not None else 1
        if first <= last:
            sheet.range((first, column + 1), (last, column + 1)).number_format = "mm/dd/yy"
    _sheet_window(app, sheet, header_row)


def _format_table(
    app: Any,
    sheet: Any,
    headers: list[str],
    rows: list[list[Any]],
    *,
    date_columns: set[int],
    widths: list[int],
) -> None:
    width = len(headers)
    _write_rows(sheet, 1, [headers], width)
    _write_rows(sheet, 2, rows, width, date_columns=date_columns)
    last = max(1, len(rows) + 1)
    used = sheet.range((1, 1), (last, width))
    _base(sheet, used)
    _header(sheet.range((1, 1), (1, width)))
    _sheet_window(app, sheet, 1)
    for index, size in enumerate(widths, start=1):
        sheet.range((1, index)).column_width = size
    if rows:
        for column in date_columns:
            sheet.range((2, column + 1), (last, column + 1)).number_format = "mm/dd/yy"


def _format_findings(sheet: Any, rows: list[list[Any]]) -> None:
    for row_number, row in enumerate(rows, start=2):
        severity = row[0]
        target = sheet.range((row_number, 1), (row_number, 6))
        if severity == "ERROR":
            target.color = PALE_RED
            sheet.range((row_number, 1)).font.color = (192, 0, 0)
            sheet.range((row_number, 1)).font.bold = True
        elif severity == "REVIEW":
            target.color = PALE_AMBER


def _format_audit(app: Any, sheet: Any, rows: list[list[Any]]) -> None:
    width = max(map(len, rows))
    _write_rows(sheet, 1, rows, width)
    used = sheet.range((1, 1), (len(rows), width))
    _base(sheet, used)
    _title(sheet.range("A1"))
    for row_number, row in enumerate(rows, start=1):
        if row and row[0] in {
            "Reconciliation",
            "Dictionary snapshots",
            "Calendar snapshots",
            "Calendar sources",
            "Calendar assumptions",
        }:
            band = sheet.range((row_number, 1), (row_number, width))
            band.color = GREEN
            band.font.color = WHITE
            band.font.bold = True
        if len(row) >= 4 and row[3] == "FAILED":
            sheet.range((row_number, 1), (row_number, 4)).color = PALE_RED
            sheet.range((row_number, 4)).font.color = (192, 0, 0)
            sheet.range((row_number, 4)).font.bold = True
        elif len(row) >= 4 and row[3] == "OK":
            sheet.range((row_number, 4)).color = PALE_GREEN
    for column, size in enumerate((31, 64, 72, 15, 15), start=1):
        sheet.range((1, column)).column_width = size
    _sheet_window(app, sheet, 1)


def write_workbook(payload: dict[str, Any], output: Path, excel_pid: int) -> str:
    xw = importlib.import_module("xlwings")
    backend = importlib.import_module("xlwings._xlwindows")
    atexit.unregister(backend.cleanup)
    while True:
        try:
            app = xw.apps[excel_pid]
            break
        except KeyError:
            time.sleep(0.05)
    app.visible = False
    book = None
    try:
        app.api.AutomationSecurity = 3
        app.enable_events = False
        app.display_alerts = False
        app.screen_updating = False
        book = app.books.add()
        app.calculation = "manual"
        app.api.CalculateBeforeSave = False
        if app.api.AutomationSecurity != 3 or app.enable_events or app.calculation != "manual":
            raise RuntimeError("Excel export safety settings could not be established.")
        first = book.sheets[0]
        while len(book.sheets) > 1:
            book.sheets[-1].delete()
        first.name = payload["sheets"][0]["name"]
        by_name = {first.name: first}
        for specification in payload["sheets"][1:]:
            name = specification["name"]
            by_name[name] = book.sheets.add(name, after=book.sheets[-1])
        by_name["Loan Tape"].api.Tab.Color = xw.utils.rgb_to_int(GREEN)
        by_name["Summary"].api.Tab.Color = xw.utils.rgb_to_int(NAVY)
        by_name["Findings"].api.Tab.Color = xw.utils.rgb_to_int((192, 0, 0))
        by_name["Date Results"].api.Tab.Color = xw.utils.rgb_to_int(GREEN)
        by_name["Audit"].api.Tab.Color = xw.utils.rgb_to_int((127, 127, 127))
        for spec in payload["sheets"]:
            sheet = by_name[spec["name"]]
            if spec["kind"] == "loan_tape":
                _format_loan_tape(app, sheet, spec)
            elif spec["kind"] == "summary":
                _format_summary(app, sheet, spec["rows"])
            elif spec["kind"] == "audit":
                _format_audit(app, sheet, spec["rows"])
            else:
                dates = (
                    {15}
                    if spec["name"] == "Date Results"
                    else ({5, 6} if spec["name"] == "Pair Results" else set())
                )
                widths = (
                    [
                        12,
                        12,
                        13,
                        25,
                        15,
                        24,
                        15,
                        18,
                        18,
                        13,
                        16,
                        28,
                        24,
                        13,
                        30,
                        13,
                        24,
                        20,
                        15,
                        34,
                        28,
                        20,
                        18,
                        18,
                        40,
                    ]
                    if spec["name"] == "Date Results"
                    else [12, 25, 12, 25, 12, 13, 13, 22, 18]
                    if spec["name"] == "Pair Results"
                    else [12, 27, 16, 18, 68, 72]
                )
                _format_table(
                    app, sheet, spec["headers"], spec["rows"], date_columns=dates, widths=widths
                )
                if spec["name"] == "Findings":
                    _format_findings(sheet, spec["rows"])
        by_name["Loan Tape"].activate()
        book.api.BuiltinDocumentProperties("Title").Value = "Refined loan tape and date review"
        book.api.BuiltinDocumentProperties("Subject").Value = payload["run_id"]
        book.api.CheckCompatibility = False
        book.save(str(output))
        return str(xw.__version__)
    finally:
        if book is not None:
            book.close()
        app.api.Quit()


def main() -> None:
    result_path = Path(sys.argv[3])
    try:
        payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        writer_version = write_workbook(payload, Path(sys.argv[2]), int(sys.argv[4]))
        result = {"writer": "xlwings", "writer_version": writer_version}
    except Exception as error:
        result = {
            "error": "Excel could not create the refined loan tape. No output was published.",
            "detail": f"{type(error).__name__}: {error}",
        }
    result_path.write_text(json.dumps(result, ensure_ascii=True), encoding="utf-8")


if __name__ == "__main__":
    main()
