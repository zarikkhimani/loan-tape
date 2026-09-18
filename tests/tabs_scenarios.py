"""Exercise real Tk tabs with synthetic sources and isolated reader substitutes."""

import sys
import time
import tkinter as tk
from pathlib import Path
from threading import Event
from unittest.mock import patch

from desktop_scenarios import dispatch_drop, wait_for_copy, wait_for_preview
from openpyxl import Workbook

from loan_tape.inspection import InspectionError, read_preview
from loan_tape.intake import IntakeStore
from loan_tape.ui import LoanTapeApp, create_root


def wait(root, condition):
    deadline = time.monotonic() + 8
    while not condition():
        root.update()
        assert time.monotonic() < deadline, "Tab operation did not complete"
        time.sleep(0.01)
    root.update()


def click_tab(app, index, *, close=False):
    app.root.deiconify()
    app.root.update()
    # Find the actual native tab bounds rather than assuming text/pixel widths.
    y = 12
    positions = []
    for x in range(app.tabs.winfo_width()):
        try:
            if app.tabs.index(f"@{x},{y}") == index:
                positions.append(x)
        except tk.TclError:
            pass
    assert positions
    x = positions[-1] - 14 if close else positions[0] + 20
    app.tabs.event_generate("<ButtonPress-1>", x=x, y=y)
    app.tabs.event_generate("<ButtonRelease-1>", x=x, y=y)
    app.root.update()


def run(scenario, work):
    root = create_root()
    root.withdraw()
    failures = []
    root.report_callback_exception = lambda *error: failures.append(error)
    app = LoanTapeApp(root, IntakeStore(work / "inputs"))
    release = Event()
    try:
        csv = work / ("Portfolio with a deliberately long but distinct filename for tabs.csv")
        csv.write_text(
            ",".join(f"Field {i}" for i in range(12))
            + "\n"
            + "\n".join(",".join(f"{row:06d}" for _ in range(12)) for row in range(35)),
            encoding="utf-8",
        )
        if scenario == "excel":
            source = work / "portfolio.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.title = "Loans"
            for row in range(1, 81):
                sheet.append([f"{row:06d}", row * 100])
            book.save(source)
            book.close()
        else:
            source = csv
        original = source.read_bytes()
        app.add_file(source)
        wait_for_copy(app)
        assert app.tabs.tabs() == (str(app.files_page),)

        if scenario == "busy":
            started, cancelled_seen = Event(), Event()

            def paused(path, *, cancelled, **kwargs):
                started.set()
                assert cancelled.wait(8)
                cancelled_seen.set()
                assert release.wait(8)
                raise InspectionError("Cancelled")

            with patch("loan_tape.preview_ui.read_parallel_preview", side_effect=paused):
                app.inspect_file()
                inspector = app.inspector
                wait(root, started.is_set)
                app.tabs.select(app.files_page)
                root.update()
                assert not inspector.cancelled.is_set()
                assert not app.workers.closing
                app.activate_preview()
                root.update()
                assert not inspector.cancelled.is_set()
                # Closing the preview must leave a concurrent intake copy alone.
                copy_started, finish_copy = Event(), Event()
                original_save = app.store.save_path

                def slow_copy(path):
                    copy_started.set()
                    assert finish_copy.wait(8)
                    return original_save(path)

                with patch.object(app.store, "save_path", side_effect=slow_copy):
                    second = work / "second.csv"
                    second.write_text("id\n0002\n")
                    app.add_file(second)
                    wait(root, copy_started.is_set)
                    app.close_preview()
                    wait(root, cancelled_seen.is_set)
                    assert inspector.closed and not app.closed
                    assert not app.workers.closing
                    assert app.worker is not None and app.worker.is_alive()
                    assert app.tabs.tabs() == (str(app.files_page),)
                    finish_copy.set()
                    wait_for_copy(app)
                    assert len(app.records) == 2
                # Retired tab work remains tracked until it finishes.
                assert "file-preview" in app.workers.active_names()
                release.set()
                wait(root, lambda: not app.workers.active_names())
            app.inspect_file()
            wait_for_preview(app)
            assert not app.inspector.closed
        else:
            with patch(
                "loan_tape.preview_ui.read_parallel_preview", side_effect=read_preview
            ) as reader:
                app.inspect_file()
                wait_for_preview(app)
                inspector = app.inspector
                assert inspector.frame.winfo_toplevel() is root
                assert app.tabs.tabs() == (
                    str(app.files_page),
                    str(inspector.frame),
                    str(app.order_panel.frame),
                )
                assert app.tabs.select() == str(inspector.frame)
                assert not any(isinstance(widget, tk.Toplevel) for widget in root.winfo_children())
                root.deiconify()
                root.update()
                inspector.zoom.set("125%")
                inspector._apply_zoom()
                if scenario == "excel":
                    nav = inspector.navigator
                    assert not nav.has_unsaved_setup()  # automatic suggestion
                    nav.header_text.set("1")
                    nav.use_range()
                    wait_for_preview(app)
                    nav.move(20, 0)
                    wait_for_preview(app)
                    nav.show_editor()
                    nav.table_name.set("Unfinished setup")
                    assert nav.has_unsaved_setup()
                    inspector._toggle_sidebar()
                else:
                    inspector.encoding.set("UTF-8")
                    inspector.delimiter.set("Comma (,)")
                root.deiconify()
                root.update()
                inspector._select_column(0, entire=True)
                inspector.table.yview_moveto(0.5)
                inspector.table.xview_moveto(0.3)
                root.update()
                state = (
                    inspector.preview,
                    inspector.table.yview(),
                    inspector.table.xview(),
                    inspector.zoom.get(),
                    inspector.whole_column,
                )
                calls = reader.call_count
                with patch(
                    "loan_tape.ui.messagebox.askokcancel",
                    side_effect=AssertionError("No prompt when switching"),
                ):
                    click_tab(app, 0)
                    assert app.tabs.select() == str(app.files_page)
                    assert not inspector.closed and not inspector.cancelled.is_set()
                    if scenario == "excel":
                        # A redraw while hidden must not lose the visible selection on return.
                        inspector.column_highlight.refresh()
                        root.update()
                    click_tab(app, 1)
                    if scenario == "excel":
                        assert inspector.column_highlight.canvas.winfo_ismapped(), (
                            inspector.column_highlight.column,
                            inspector.table.winfo_ismapped(),
                            inspector.table.xview(),
                            inspector.table.yview(),
                            inspector.table.bbox(inspector.table.get_children()[0], "A"),
                            inspector.column_highlight.pending,
                        )
                    assert app.tabs.select() == str(inspector.frame)
                    assert state == (
                        inspector.preview,
                        inspector.table.yview(),
                        inspector.table.xview(),
                        inspector.zoom.get(),
                        inspector.whole_column,
                    )
                    assert reader.call_count == calls
                    app.inspect_file()
                    assert app.inspector is inspector and reader.call_count == calls

                if scenario == "excel":
                    assert nav.table_name.get() == "Unfinished setup"
                    assert inspector.sidebar_collapsed and nav.page_area.min_row == 21
                    with patch(
                        "loan_tape.ui.messagebox.askokcancel", return_value=False
                    ) as confirm:
                        click_tab(app, 1, close=True)
                        assert not inspector.closed
                        app.request_exit()
                        assert not app.closing
                        assert confirm.call_count == 2
                    nav.use_range()
                    wait_for_preview(app)
                    assert not nav.has_unsaved_setup()
                    # The third workspace tab carries the complete data set while
                    # using the selected column as its order key.
                    click_tab(app, 2)
                    order = app.order_panel
                    wait(root, lambda: order.result is not None and not order.busy)
                    assert app.tabs.select() == str(order.frame)
                    assert order.result.total_rows == 79
                    assert order.result.total_columns == 2
                    assert len(order.grid.get_children()) == 50
                    assert order.grid["columns"] == ("A", "B")
                    order.mode.set("Descending")
                    order._mode_changed()
                    first = order.grid.get_children()[0]
                    assert order.entries[first].sort_cell.text == "000080"
                    assert order.grid.item(first, "values") == ("000080", "8000")
                    order.grid.selection_set(first)
                    order._selected()
                    order.jump_button.invoke()
                    wait_for_preview(app)
                    assert app.tabs.select() == str(inspector.frame)
                    assert inspector.table.selection() == ("80",)
                    # Nonmodal details hide with their tab and restore on return.
                    root.deiconify()
                    nav.show_details()
                    root.update()
                    assert nav.overview_window.winfo_viewable()
                    click_tab(app, 0)
                    assert not nav.overview_window.winfo_viewable()
                    click_tab(app, 1)
                    assert nav.overview_window.winfo_viewable()
                    nav.overview_window.withdraw()
                    saved_table = nav.table_for_inspection()
                    app.tabs.select(app.files_page)
                    inspector._jump_to_column_row(saved_table, 1, 30)
                    assert app.tabs.select() == str(inspector.frame)
                    wait_for_preview(app)
                    assert inspector.table.selection() == ("30",)
                    # Sidebar wheel bindings must be removed with the panel.
                    binding = inspector.wheel_binding
                    assert binding and binding in root.bind("<MouseWheel>")
                    nav.show_editor()
                    nav.start_text.set("INVALID")
                    assert nav.has_unsaved_setup()
                    click_tab(app, 2)
                    assert order.result is None
                    assert "save" in order.status.get().lower()
                    click_tab(app, 1)
                    app.add_file(csv)
                    wait_for_copy(app)
                    with patch("loan_tape.ui.messagebox.askokcancel", return_value=False):
                        app.inspect_file()
                    assert app.inspector is inspector and not inspector.closed
                    with patch("loan_tape.ui.messagebox.askokcancel", return_value=True):
                        app.inspect_file()
                    wait_for_preview(app)
                    assert inspector.closed and app.inspector is not inspector
                    assert binding not in root.bind("<MouseWheel>")
                else:
                    assert inspector.encoding.get() == "UTF-8"
                    assert inspector.delimiter.get() == "Comma (,)"
                    # A drop over preview content routes feedback to Files without replacing it.
                    original_drop_zone = app.drop_zone
                    app.drop_zone = inspector.table
                    try:
                        assert dispatch_drop(app, [csv]) == "copy"
                    finally:
                        app.drop_zone = original_drop_zone
                    assert app.tabs.select() == str(app.files_page)
                    wait_for_copy(app)
                    assert app.inspector is inspector and not inspector.closed
                    app.inspect_file()  # same filename, different saved copy
                    wait_for_preview(app)
                    assert inspector.closed and app.inspector.path != inspector.path
                click_tab(app, 1, close=True)
                assert app.inspector.closed and not app.closed and not app.workers.closing
                assert app.tabs.tabs() == (str(app.files_page),)
                click_tab(app, 0, close=True)
                assert app.tabs.tabs() == (str(app.files_page),)
                app.inspect_file()
                wait_for_preview(app)
                root.deiconify()
                root.update()
                app.tabs.focus_force()
                root.update()
                app.tabs.event_generate("<Control-Tab>")
                root.update()
                assert app.tabs.select() == str(app.order_panel.frame)
                app.tabs.focus_force()
                root.update()
                app.tabs.event_generate("<Control-Tab>")
                root.update()
                assert app.tabs.select() == str(app.files_page)
                app.tabs.focus_force()
                root.update()
                app.tabs.event_generate("<Control-Shift-Tab>")
                root.update()
                assert app.tabs.select() == str(app.order_panel.frame)
                app.tabs.focus_force()
                root.update()
                app.tabs.event_generate("<Control-w>")
                root.update()
                assert app.inspector.closed and not app.closed
                assert not app.tabs._over_close(20, 200)
        assert source.read_bytes() == original
        assert not failures, failures
    finally:
        release.set()
        if not app.closed:
            app.close()
            wait(root, lambda: app.closed)


if __name__ == "__main__":
    run(sys.argv[1], Path(sys.argv[2]))
