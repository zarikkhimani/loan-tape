"""XML full-column review through the existing native dialogs."""

import sys
import time
from pathlib import Path
from threading import Event
from unittest.mock import patch

from desktop_scenarios import wait_for_column, wait_for_copy, wait_for_preview

from loan_tape.column_profile import ColumnAccumulator
from loan_tape.intake import IntakeStore
from loan_tape.ui import LoanTapeApp, create_root


def wait_check(app):
    child = app.inspector.column_checker
    child.window.withdraw()
    deadline = time.monotonic() + 10
    while child.busy and not child.closed:
        app.root.update()
        assert time.monotonic() < deadline, "XML check did not finish"
        time.sleep(0.01)
    app.root.update()


def clean_files():
    for folder in ("column-inspection", "column-checks"):
        path = Path(".artifacts") / folder
        assert not path.exists() or not list(path.iterdir())


def run(scenario, work):
    source = work / "review.xml"
    source.write_text(
        "<loans>"
        + "".join(
            f'<loan id="{row:06}">'
            + "".join(f"<f{n}>{row}:{n}</f{n}>" for n in range(1, 11))
            + f"<amount>{'0.0000' if row <= 20 else ' N/A '}</amount><due>{'2026-09-17' if row < 70 else '2023-02-29'}</due></loan>"
            for row in range(1, 71)
        )
        + "</loans>",
        encoding="utf-8",
    )
    before = source.read_bytes()
    root = create_root()
    root.withdraw()
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    app = LoanTapeApp(root, IntakeStore(work / "inputs"))
    try:
        app.add_file(source)
        wait_for_copy(app)
        app.inspect_file()
        wait_for_preview(app)
        panel = app.inspector
        nav = panel.xml_navigation
        panel._select_column(0, entire=True)
        assert panel.column_button.instate(["disabled"]) and panel.check_button.instate(
            ["disabled"]
        )
        nav.name.set("Loans")
        nav.save_button.invoke()
        assert panel.column_button.instate(["!disabled"])
        nav.name.set("Unsaved name")
        assert panel.column_button.instate(["disabled"]) and panel.check_button.instate(
            ["disabled"]
        )
        nav.name.set(nav.clean_name)
        nav.edge(True)
        wait_for_preview(app)
        panel._select_column(1, entire=True)
        assert panel.preview.start_column == 11 and "amount" in panel.headers[1].text
        assert "records 1" in panel.cell_summary.get()
        if scenario == "review":
            panel.column_button.invoke()
            wait_for_column(app)
            child = panel.column_inspector
            assert child.profile.total_rows == 70 and child.profile.column == 12
            assert dict(child.profile.counts)["Text"] == 70
            assert "XML /loans/loan" in child.scope_label.cget("text")
            assert child.jump_button.cget("text") == "Jump to record"
            child.tabs.select(child.repeated.master)
            child.repeated.selection_set("repeat-0")
            child._selected()
            assert "loan[21]/amount[1]" in child.detail.get("1.0", "end")
            child.jump_button.invoke()
            wait_for_preview(app)
            assert child.closed and panel.table.selection() == ("21",)
            assert panel.preview.start_column == 12 and panel.preview.start_row == 21
            assert "loan[21]/amount[1]" in panel.cell_text.get("1.0", "end")
            panel.check_button.invoke()
            check = panel.column_checker
            check.window.withdraw()
            check.expected.set("Number")
            assert "plain decimal text" in check.hint.cget("text")
            check.run_button.invoke()
            wait_check(app)
            report = check.report
            assert report.finding_count == 50 and report.profile.total_rows == 70
            assert report.rules.number_format == "Plain decimal text"
            assert len(check.grid.get_children()) == 20
            check.next.invoke()
            assert check.offset == 20 and check.grid.get_children()[0] == "41"
            check.next.invoke()
            assert check.offset == 40 and check.grid.get_children()[-1] == "70"
            check.grid.selection_set("70")
            check._selected()
            assert "loan[70]/amount[1]" in check.detail.get("1.0", "end")
            assert "State: Present" in check.detail.get("1.0", "end")
            check.jump_button.invoke()
            wait_for_preview(app)
            assert check.closed and report._closed
            assert panel.table.selection() == ("70",) and panel.preview.start_column == 12
            clean_files()
            nav.go(1, 13)
            wait_for_preview(app)
            panel._select_column(0, entire=True)
            panel.check_button.invoke()
            check = panel.column_checker
            check.window.withdraw()
            assert "Excel dates only" not in check.date_selector.cget("values")
            check.expected.set("Date")
            check.run_button.invoke()
            wait_check(app)
            assert check.report.finding_count == 1 and check.report.page()[0].cell.row == 70
            old = check.report
            check.required.set(False)
            assert check.report is None and old._closed
            check.close()
            clean_files()
            nav.new_button.invoke()
            assert panel.column_button.instate(["disabled"]) and panel.check_button.instate(
                ["disabled"]
            )
        elif scenario == "changed":
            panel.check_button.invoke()
            check = panel.column_checker
            check.window.withdraw()
            Path(app.saved_path.get()).write_bytes(before.replace(b"0.0000", b"9.0000"))
            check.expected.set("Number")
            check.run()
            wait_check(app)
            assert check.report is None and "changed" in check.status.get()
            clean_files()
            check.close()
        elif scenario == "scope":
            panel.column_button.invoke()
            wait_for_column(app)
            child = panel.column_inspector
            child.examples.selection_set("example-0")
            child._selected()
            nav.name.set("Renamed")
            nav.save()
            child.jump_selected()
            assert not child.closed and "data set changed" in child.status.get()
            child.close()
        elif scenario in ("cancel", "shutdown"):
            started = Event()
            original = ColumnAccumulator.add

            def slow(acc, cell, key, **kwargs):
                original(acc, cell, key, **kwargs)
                if cell.row == 1:
                    started.set()
                    assert app.inspector.column_checker.cancelled.wait(5)

            with patch.object(ColumnAccumulator, "add", slow):
                panel.check_button.invoke()
                check = panel.column_checker
                check.window.withdraw()
                check.expected.set("Number")
                check.run()
                deadline = time.monotonic() + 6
                while not started.is_set():
                    root.update()
                    time.sleep(0.01)
                    assert time.monotonic() < deadline
                app.close() if scenario == "shutdown" else check.close()
                while app.workers.active_names():
                    root.update()
                    time.sleep(0.01)
                    assert time.monotonic() < deadline
                clean_files()
        else:
            raise AssertionError(scenario)
        assert not errors, errors
        assert source.read_bytes() == before
        if scenario == "shutdown":
            assert not Path(app.saved_path.get()).exists()
        elif scenario != "changed":
            assert Path(app.saved_path.get()).read_bytes() == before
    finally:
        if not app.closed:
            if app.inspector and app.inspector.xml_navigation:
                nav = app.inspector.xml_navigation
                nav.name.set(nav.clean_name)
            app.close()
            deadline = time.monotonic() + 5
            while not app.closed:
                root.update()
                time.sleep(0.01)
                assert time.monotonic() < deadline


if __name__ == "__main__":
    run(sys.argv[1], Path(sys.argv[2]))
