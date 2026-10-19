"""Private xlwings writer for the complete reviewed text result and its evidence."""

from __future__ import annotations

import atexit
import importlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from loan_tape.date_export_worker import GREEN, NAVY, _base, _header, _sheet_window, _write_rows


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
        while len(book.sheets) > 1:
            book.sheets[-1].delete()
        for index, spec in enumerate(payload["sheets"]):
            sheet = book.sheets[0] if index == 0 else book.sheets.add(after=book.sheets[-1])
            sheet.name = spec["name"]
            rows = spec["rows"]
            width = max(map(len, rows))
            _write_rows(sheet, 1, rows, width)
            used = sheet.range((1, 1), (len(rows), width))
            _base(sheet, used)
            header = spec.get("header_row")
            if header is not None:
                _header(sheet.range((header, 1), (header, width)))
            for column in range(1, width + 1):
                size = max(
                    (len(str(row[column - 1] or "")) for row in rows[:200] if len(row) >= column),
                    default=10,
                )
                sheet.range((1, column)).column_width = min(56, max(12, size + 2))
            _sheet_window(app, sheet, header)
            sheet.api.Tab.Color = xw.utils.rgb_to_int(GREEN if index == 0 else NAVY)
        book.sheets[0].activate()
        book.api.BuiltinDocumentProperties("Title").Value = "Reviewed loan tape and text audit"
        book.api.BuiltinDocumentProperties("Subject").Value = payload["revision_id"]
        book.api.CheckCompatibility = False
        book.save(str(output))
        return str(xw.__version__)
    finally:
        if book is not None:
            book.close()
        app.api.Quit()


def main() -> None:
    try:
        payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        version = write_workbook(payload, Path(sys.argv[2]), int(sys.argv[4]))
        result = {"writer": "xlwings", "writer_version": version}
    except Exception as error:
        result = {"error": f"{type(error).__name__}: {error}"}
    Path(sys.argv[3]).write_text(json.dumps(result, ensure_ascii=True), encoding="utf-8")


if __name__ == "__main__":
    main()
