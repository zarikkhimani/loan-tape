import os
import sys
from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import patch

from text_cleanup_ui_scenario import wait
from text_export_support import prepare_export, write_fixture

from loan_tape.column_definitions import ColumnRules, definition_for_column, save_column_definition
from loan_tape.ui import LoanTapeApp, create_root
from loan_tape.workbook_index import ScanCancelled


def run(scenario, work):
    os.chdir(work)
    original, source, intake, table, store, revision, date_run = prepare_export(work)
    before = original.read_bytes()
    root = create_root()
    root.withdraw()
    app = LoanTapeApp(root, intake)
    app.pack_store = store
    release = Event()
    try:
        app.inspect_file()
        panel = app.inspector
        wait(root, lambda: not panel.busy)
        panel.text_revisions[table.id] = revision
        panel._select_column(1)
        panel.cleanup_button.invoke()
        cleanup = panel.text_cleanup
        cleanup.window.withdraw()
        cleanup.export_button.invoke()
        window = cleanup.export_window
        window.window.withdraw()
        assert not window.include_dates.get() and window.date_run is None
        assert str(cleanup.apply_button["state"]) == "disabled"
        with patch(
            "loan_tape.text_export_ui.filedialog.askopenfilename", return_value=str(date_run.path)
        ):
            window.choose_button.invoke()
            wait(root, lambda: not window.busy)
        assert window.date_run == date_run and not window.include_dates.get(), window.status.get()
        window.include_dates.set(True)
        target = work / "reviewed.xlsx"
        if scenario == "export":
            root.deiconify()
            cleanup.window.deiconify()
            window.window.deiconify()
            window.window.geometry("760x430")
            root.update()
            assert (
                window.status_label.winfo_rooty() + window.status_label.winfo_height()
                <= window.window.winfo_rooty() + window.window.winfo_height()
            )
            root.withdraw()
            cleanup.window.withdraw()
            window.window.withdraw()

            def writer(payload, staging, **kwargs):
                assert payload["date_run_id"] == date_run.id
                assert payload["sheets"][0]["rows"][2][0] == "=Reviewed Name"
                write_fixture(staging, payload)
                return "fixture"

            with (
                patch(
                    "loan_tape.text_export_ui.filedialog.asksaveasfilename",
                    return_value=str(target),
                ),
                patch("loan_tape.text_export.write_excel", side_effect=writer),
                patch("loan_tape.text_export.version", return_value="fixture"),
            ):
                window.export_button.invoke()
                wait(root, lambda: not window.busy)
            assert window.output is not None and target.exists(), window.status.get()
            assert original.read_bytes() == source.read_bytes() == before
            assert str(window.open_button["state"]) == "normal"
            with patch("loan_tape.text_export_ui.open_in_excel") as opened:
                window.open_button.invoke()
                opened.assert_called_once_with(target)
        elif scenario == "stale":
            definition = definition_for_column(table, 3)
            save_column_definition(
                table, replace(definition, rules=ColumnRules(missing_tokens=("N/A",)))
            )
            wait(root, lambda: window.invalid)
            assert str(window.export_button["state"]) == "disabled"
        else:
            started, cleaning = Event(), Event()

            def paused(*args, cancelled, **kwargs):
                started.set()
                assert cancelled.wait(5)
                cleaning.set()
                assert release.wait(5)
                raise ScanCancelled("Synthetic cancellation")

            with (
                patch(
                    "loan_tape.text_export_ui.filedialog.asksaveasfilename",
                    return_value=str(target),
                ),
                patch("loan_tape.text_export_ui.export_text_revision", side_effect=paused),
            ):
                window.export_button.invoke()
                wait(root, started.is_set)
                app.close()
                assert app.closing and not app.closed and window.closed
                assert cleaning.wait(5) and source.exists() and app.workers.active_names()
                release.set()
                wait(root, lambda: app.closed)
        if not app.closed:
            app.close()
            wait(root, lambda: app.closed)
        assert not source.exists() and not app.workers.active_names()
        assert target.exists() == (scenario == "export")
        assert original.read_bytes() == before
        print(f"{scenario}: native export, explicit dates, retention and owned shutdown passed")
    finally:
        release.set()
        if not app.closed:
            app.close()
            wait(root, lambda: app.closed)


if __name__ == "__main__":
    run(sys.argv[1], Path(sys.argv[2]))
