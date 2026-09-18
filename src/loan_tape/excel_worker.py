"""Private process for read-only xlwings access to a preflighted temporary copy."""

from __future__ import annotations

import atexit
import importlib
import json
import sys
import time
from contextlib import redirect_stdout
from dataclasses import asdict
from pathlib import Path

from loan_tape.inspection import MAX_COLUMNS, MAX_ROWS, FilePreview, PreviewCell, _text
from loan_tape.ranges import CellRange, parse_range


def read_with_excel(
    path: Path, sheet: str | None, excel_pid: int, area: CellRange | None = None
) -> FilePreview:
    xw = importlib.import_module("xlwings")
    # The pinned xlwings Windows backend registers a machine-wide zombie sweep.
    # Our parent owns exact process handles; never run that unrelated-process sweep.
    backend = importlib.import_module("xlwings._xlwindows")
    atexit.unregister(backend.cleanup)
    while True:
        try:
            app = xw.apps[excel_pid]
            break
        except KeyError:
            time.sleep(0.05)  # The parent enforces timeout/cancellation during startup.
    app.visible = False
    try:
        app.api.AutomationSecurity = 3  # ForceDisable, only in this disposable instance.
        app.enable_events = False
        app.display_alerts = False
        # Excel requires a workbook before setting calculation mode.
        blank = app.books.add()
        app.calculation = "manual"
        app.api.CalculateBeforeSave = False
        if app.api.AutomationSecurity != 3 or app.enable_events or app.calculation != "manual":
            raise RuntimeError("Excel inspection settings could not be established.")
        book = app.books.open(
            str(path),
            update_links=False,
            read_only=True,
            password="",
            write_res_password="",
            ignore_read_only_recommended=True,
            notify=False,
            add_to_mru=False,
        )
        try:
            sheets = tuple(str(item.name) for item in book.sheets)
            selected = sheet or sheets[0]
            worksheet = book.sheets[selected]
            last = worksheet.used_range.last_cell
            height, width = int(last.row), int(last.column)
            if area:
                region = worksheet.range(
                    (area.min_row, area.min_column),
                    (
                        min(area.max_row, area.min_row + MAX_ROWS - 1),
                        min(area.max_column, area.min_column + MAX_COLUMNS - 1),
                    ),
                )
                height, width = area.row_count, area.column_count
            else:
                region = worksheet.range((1, 1), (min(height, MAX_ROWS), min(width, MAX_COLUMNS)))
            matrix = region.options(ndim=2, err_to_str=True).value
            rows = tuple(tuple(PreviewCell(_text(value)) for value in row) for row in matrix)
            if area is None and height == width == 1 and rows[0][0].text == "":
                rows = ()
                width = 0
            return FilePreview(
                rows=rows,
                column_count=min(width, MAX_COLUMNS),
                more_rows=height > MAX_ROWS,
                more_columns=width > MAX_COLUMNS,
                start_row=area.min_row if area else 1,
                start_column=area.min_column if area else 1,
                sheets=sheets,
                selected_sheet=selected,
                reading_note="Excel values read through xlwings from a temporary copy. Read-only; no recalculation or updates.",
            )
        finally:
            book.close()
            blank.close()
    finally:
        # Avoid App.quit()/its context manager: those also invoke global cleanup.
        # The parent job enforces shutdown if this particular COM call stalls.
        app.api.Quit()


def main() -> None:
    try:
        with redirect_stdout(sys.stderr):
            preview = read_with_excel(
                Path(sys.argv[1]),
                sys.argv[2] or None,
                int(sys.argv[3]),
                parse_range(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] else None,
            )
        payload: dict[str, object] = {"preview": asdict(preview)}
    except Exception:
        payload = {
            "error": "Excel comparison failed. Check that Excel can start and the workbook is readable."
        }
    Path(sys.argv[5]).write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")


if __name__ == "__main__":
    main()
