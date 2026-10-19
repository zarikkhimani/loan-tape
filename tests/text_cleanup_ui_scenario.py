"""Exercise real native controls, scoped application and owned-worker shutdown."""

import os
import sys
import time
from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import patch
from weakref import ref

from text_cleanup_support import prepare

from loan_tape.column_definitions import ColumnRules, definition_for_column, save_column_definition
from loan_tape.excel_compare import ComparisonSkipped
from loan_tape.transformations import derived_text_values
from loan_tape.ui import LoanTapeApp, create_root
from loan_tape.workbook_index import ScanCancelled


def wait(root, predicate):
    deadline = time.monotonic() + 15
    while not predicate():
        root.update()
        assert time.monotonic() < deadline, "Text cleanup scenario timed out"
        time.sleep(0.01)


def preview(root, window):
    window.preview_button.invoke()
    wait(root, lambda: not window.busy)
    assert window.review is not None, window.status.get()


def choose(window, cell):
    window.grid.selection_set(cell)
    window.include_button.invoke()


def run(scenario, work):
    os.chdir(work)
    source, saved, intake, table, store = prepare(work, ["CafÃ© Holdings"] * 211)
    original = source.read_bytes()
    root = create_root()
    root.withdraw()
    app = LoanTapeApp(root, intake)
    app.pack_store = store
    release = Event()
    try:
        app.inspect_file()
        panel = app.inspector
        root.withdraw()
        wait(root, lambda: not panel.busy)
        assert panel.navigator.table_for_inspection() == table
        assert panel.cleanup_button.instate(["disabled"])
        panel._select_column(0)
        panel.cleanup_button.invoke()
        window = panel.text_cleanup
        window.window.withdraw()
        assert window.review is None and not window.selected
        if scenario == "review":
            root.deiconify()
            window.window.deiconify()
            window.window.geometry("860x640")
            root.update()
            right = window.window.winfo_rootx() + window.window.winfo_width()
            bottom = window.window.winfo_rooty() + window.window.winfo_height()
            for widget in (
                window.preview_button,
                window.cancel_button,
                window.apply_button,
                window.window.winfo_children()[0].winfo_children()[-1],
            ):
                assert widget.winfo_width() > 10 and widget.winfo_height() > 10
                assert widget.winfo_rootx() + widget.winfo_width() <= right
                assert widget.winfo_rooty() + widget.winfo_height() <= bottom
            window.window.withdraw()
            root.withdraw()
            preview(root, window)
            assert len(window.grid.get_children()) == 200
            assert window.review.preview.to_dict()["reconciliation"]["changed"] == 211
            window.grid.selection_set("2:1")
            root.update()
            assert not window.selected and window.apply_button.instate(["disabled"])
            assert "Original evidence" in window.detail.get("1.0", "end")
            window.include_button.invoke()
            window.next.invoke()
            assert len(window.grid.get_children()) == 11
            window.grid.selection_set("212:1")
            root.update()
            window.jump_button.invoke()
            wait(root, lambda: not panel.busy)
            assert (
                panel.preview.start_row <= 212 < panel.preview.start_row + len(panel.preview.rows)
            )
            window.include_button.invoke()
            assert window.selected == {(2, 1), (212, 1)}
            window.apply_button.invoke()
            assert not window.busy and "reviewer" in window.status.get().lower()
            window.reviewer.set("Synthetic reviewer")
            window.justification.set("Checked both source cells.")
            window.apply_button.invoke()
            wait(root, lambda: not window.busy)
            assert window.applied, window.status.get()
            assert derived_text_values(window.parent) == (
                (2, 1, "Café Holdings"),
                (212, 1, "Café Holdings"),
            )
            assert source.read_bytes() == original == saved.read_bytes()
            assert len(list((work / ".artifacts/transformations").glob("*.json"))) == 1
            parent = window.parent
            retired_window = ref(window)
            window.close()
            panel.open_text_cleanup()
            window = panel.text_cleanup
            app.workers.active_names()
            assert retired_window() is None, "Closed cleanup window retained UI callbacks"
            window.window.withdraw()
            assert window.parent == parent
            preview(root, window)
            assert window.review.preview.to_dict()["reconciliation"]["changed"] == 209
            choose(window, "3:1")
            window.normalize.set(True)
            assert window.review is None and not window.selected
            preview(root, window)
            choose(window, "3:1")
            store.deactivate("loan.text")
            wait(root, lambda: not window.allowed)
            assert window.review is None and not window.selected
            store.activate("loan.text")
            wait(root, lambda: window.allowed)
            preview(root, window)
            choose(window, "3:1")
            definition = definition_for_column(table, 1)
            save_column_definition(
                table, replace(definition, rules=ColumnRules(missing_tokens=("N/A", "UNKNOWN")))
            )
            wait(root, lambda: window.review is None)
            assert not window.selected
            window.start_from_source()
            assert window.parent is None and table.id not in panel.text_revisions
            preview(root, window)
            assert window.review.preview.to_dict()["reconciliation"]["changed"] == 211
            panel.navigator.range_text.set("A1:B100")
            wait(root, lambda: not window.allowed)
            assert window.review is None and window.preview_button.instate(["disabled"])
            app.close()
            wait(root, lambda: app.closed)
        else:
            started, cleaning = Event(), Event()

            def paused(*args, cancelled, **kwargs):
                started.set()
                assert cancelled.wait(5)
                cleaning.set()
                assert release.wait(5)
                raise ScanCancelled("Synthetic cancellation")

            if scenario == "apply-shutdown":
                preview(root, window)
                choose(window, "2:1")
                window.reviewer.set("Synthetic reviewer")
                window.justification.set("Shutdown coverage.")
                target = "loan_tape.text_cleanup_ui.apply_excel_text"
                action = window.apply_button.invoke
            else:
                target = "loan_tape.text_cleanup_ui.review_excel_text"
                action = window.preview_button.invoke
            with patch(target, side_effect=paused):
                action()
                wait(root, started.is_set)
                if scenario == "cancel-preview":
                    window.cancel_button.invoke()
                    assert cleaning.wait(5)
                    assert window.review is None and not window.selected
                    release.set()
                    wait(root, lambda: not window.busy)
                else:
                    app.close()
                    assert app.closing and not app.closed and window.closed
                    assert cleaning.wait(5)
                    assert app.workers.active_names() and saved.exists()
                    release.set()
                    wait(root, lambda: app.closed)
            if scenario == "cancel-preview":
                preview(root, window)
                app.close()
                wait(root, lambda: app.closed)
        assert not app.workers.active_names()
        assert not saved.exists() and intake.list_files() == []
        assert not list((work / ".artifacts/transformations").glob("*"))
        assert source.read_bytes() == original
        print(f"{scenario}: native cleanup workflow and session teardown passed")
    finally:
        release.set()
        if not app.closed:
            app.close()
            wait(root, lambda: app.closed)


if __name__ == "__main__":
    # The cleanup UI is independent of optional Office startup. The dedicated
    # Excel smoke still executes the actual owned-process integration.
    with patch(
        "loan_tape.excel_compare.read_xlwings_preview",
        side_effect=ComparisonSkipped(
            "Optional Excel comparison is outside this cleanup UI scenario."
        ),
    ):
        run(sys.argv[1], Path(sys.argv[2]))
