"""Exercise closing the actual main window while owned work is still cleaning up."""

import sys
import time
from pathlib import Path
from threading import Event
from unittest.mock import patch

from openpyxl import Workbook

from loan_tape.column_check import check_column
from loan_tape.inspection import InspectionError, read_preview
from loan_tape.intake import IntakeStore
from loan_tape.ui import LoanTapeApp, create_root


def wait(root, predicate):
    deadline = time.monotonic() + 10
    while not predicate():
        root.update()
        assert time.monotonic() < deadline, "Shutdown scenario timed out"
        time.sleep(0.01)


def main(scenario, work):
    source = work / "shutdown.xlsx"
    book = Workbook()
    book.active["DZ5000"] = "ID"
    book.active["DZ5001"] = "001"
    book.active["DZ5002"] = 12
    book.create_sheet("Formula")["A1"] = "=1+1"  # No desktop Excel needed in standard tests.
    book.save(source)
    book.close()
    original = source.read_bytes()
    store = IntakeStore(work / "inputs")
    record = store.save_path(source)
    saved = Path(store.describe(record)["saved_path"])
    root = create_root()
    root.withdraw()
    app = LoanTapeApp(root, store)
    started, cleanup, release = Event(), Event(), Event()

    def paused(*args, cancelled, **kwargs):
        report = None
        if scenario == "check":
            report = check_column(*args, cancelled=cancelled, **kwargs)
        started.set()
        assert cancelled.wait(5)
        cleanup.set()
        assert release.wait(5)
        if scenario == "retired":
            return read_preview(args[0], sheet=kwargs.get("sheet"), area=kwargs.get("area"))
        if report is not None:
            return report
        raise InspectionError("Cancelled for shutdown")

    try:
        target = {
            "discovery": "loan_tape.preview_ui.scan_workbook",
            "preview": "loan_tape.preview_ui.read_parallel_preview",
            "retired": "loan_tape.preview_ui.read_parallel_preview",
            "column": "loan_tape.column_ui.inspect_column",
            "check": "loan_tape.column_check_ui.check_column",
        }[scenario]
        with patch(target, side_effect=paused):
            app.inspect_file()
            inspector = app.inspector
            app.root.withdraw()
            if scenario in {"column", "check"}:
                wait(root, lambda: not inspector.busy)
                nav = inspector.navigator
                nav.range_text.set("DZ5000:DZ5002")
                nav.header_text.set("5000")
                nav.use_button.invoke()
                wait(root, lambda: not inspector.busy)
                inspector._select_column(0)
                if scenario == "column":
                    inspector.inspect_column()
                    inspector.column_inspector.window.withdraw()
                else:
                    inspector.check_column()
                    inspector.column_checker.window.withdraw()
                    inspector.column_checker.expected.set("Identifier")
                    inspector.column_checker.run()
            wait(root, started.is_set)
            if scenario == "retired":
                inspector.close()
                assert cleanup.wait(5)
            else:
                app.exit_button.invoke()
                assert app.closing and not app.closed
                assert inspector.closed
                assert cleanup.wait(5)
                assert app.workers.active_names()
                assert root.winfo_exists()
        if scenario == "retired":
            app.inspect_file()
            app.root.withdraw()
            wait(root, lambda: not app.inspector.busy)
            assert app.inspector is not inspector
            app.close()
            assert app.closing and not app.closed
            assert "file-preview" in app.workers.active_names()
        release.set()
        wait(root, lambda: app.closed)
        assert not app.workers.active_names()
        assert source.read_bytes() == original
        assert not saved.exists()
        assert store.list_files() == []
        for folder in ("column-inspection", "column-checks", "excel-comparison"):
            assert not list((work / ".artifacts" / folder).glob("*"))
        print(f"{scenario}: main window waited for all owned work and temporary cleanup")
    finally:
        release.set()
        if not app.closed:
            app.close()
            wait(root, lambda: app.closed)


if __name__ == "__main__":
    main(sys.argv[1], Path(sys.argv[2]))
