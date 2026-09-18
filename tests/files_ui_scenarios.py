"""Exercise file details, real opening gestures, and compact/scaled Files layouts."""

import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from desktop_scenarios import wait_for_copy, wait_for_preview

from loan_tape.intake import IntakeStore
from loan_tape.ui import LoanTapeApp, create_root


def run(scenario, work):
    root = create_root()
    root.withdraw()
    if scenario == "scaled":
        root.tk.call("tk", "scaling", 2.0)
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    app = LoanTapeApp(root, IntakeStore(work / "inputs"))
    try:
        root.geometry("760x720+0+0")
        root.deiconify()
        root.update()
        assert app.empty_state.winfo_ismapped()
        assert app.inspect_button.instate(["disabled"])
        assert app.inspect_button.cget("text") == "Open file"
        assert not app.file_details.winfo_ismapped()
        sources = []
        for i in range(2):
            folder = work / str(i)
            folder.mkdir()
            source = folder / "Portfolio.csv"
            source.write_text(f"id,balance\n000{i},100\n", encoding="utf-8")
            sources.append(source)
            app.add_file(source)
            wait_for_copy(app)
        root.update()
        assert not app.empty_state.winfo_ismapped()
        assert len(app.history.get_children()) == 2
        assert app.saved_heading.cget("text") == "2 session files"
        if scenario == "details":
            app.details_button.invoke()
            root.update()
            assert app.file_details.winfo_ismapped()
            chosen = app.history.get_children()[-1]
            app.history.selection_set(chosen)
            root.update()
            expected = app.records[chosen]["original_path"]
            app.original_button.invoke()
            assert root.clipboard_get() == expected
            app.saved_button.invoke()
            assert Path(root.clipboard_get()).read_bytes() == Path(expected).read_bytes()
            app.refresh()
            root.update()
            assert app.history.selection() == (chosen,)
            assert app.file_details.winfo_ismapped()
            app.details_button.invoke()
            root.update()
            assert not app.file_details.winfo_ismapped()
            assert app.original_path.get() == expected
            app.details_button.invoke()
            with patch.object(app.store, "list_files", return_value=[]):
                app.refresh()
            root.update()
            assert app.empty_state.winfo_ismapped()
            assert not app.file_details.winfo_ismapped()
            assert app.details_button.instate(["disabled"])
        elif scenario == "open":
            # Double-clicking a heading or empty space must not open the old selection.
            app._open_row(SimpleNamespace(x=20, y=5))
            assert app.inspector is None
            app.history.focus_force()
            root.update()
            app.history.event_generate("<Return>")
            wait_for_preview(app)
            first = app.inspector.path
            app.tabs.select(app.files_page)
            root.deiconify()
            root.update()
            other = next(
                key
                for key in app.records
                if Path(app.store.describe(app.records[key])["saved_path"]) != first
            )
            x, y, width, height = app.history.bbox(other)
            # Run the registered row action at a real row coordinate.
            app._open_row(SimpleNamespace(x=x + 20, y=y + height // 2))
            wait_for_preview(app)
            assert app.inspector.path != first
            assert app.inspector.path.name == first.name
            assert app.tabs.select() == str(app.inspector.frame)
        elif scenario == "formats":
            assert app.capability.get() == "Preview only · Complete-column review unavailable"
            assert app.inspect_button.cget("text") == "Open file"
            assert not app.inspect_button.instate(["disabled"])
            cases = (
                (".xlsx", "Full workbook review available", True),
                (".xlsm", "Full workbook review available", True),
                (".xml", "XML review and XSD validation available", True),
                (".xls", "Preserved only · In-app preview unavailable", False),
                (".xlsb", "Preserved only · In-app preview unavailable", False),
            )
            for extension, capability, can_preview in cases:
                source = work / f"capability{extension}"
                source.write_bytes(b"synthetic non-empty source")
                app.add_file(source)
                wait_for_copy(app)
                root.update()
                assert app.capability.get() == capability
                assert app.inspect_button.instate(["!disabled"] if can_preview else ["disabled"])
                assert app.inspect_button.cget("text") == (
                    "Open file" if can_preview else "Preview unavailable"
                )
                assert Path(app.saved_path.get()).read_bytes() == source.read_bytes()
            assert app.inspector is None
            assert app._open_selected() == "break"
            assert app.inspector is None
            assert "preserved, but in-app preview is unavailable" in app.status.get()
            assert str(app.status_label.cget("foreground")) == "#a1342d"
        else:
            for show_details in (False, True):
                if show_details:
                    app.details_button.invoke()
                root.update()
                assert app.history.winfo_height() >= 140
                widgets = [
                    app.browse_button,
                    app.details_button,
                    app.inspect_button,
                    app.capability_label,
                    app.packs_button,
                    app.exit_button,
                    app.session_label,
                    app.drop_title,
                ]
                if show_details:
                    widgets += [app.original_button, app.saved_button]
                for widget in widgets:
                    assert widget.winfo_ismapped(), widget
                    assert widget.winfo_rootx() >= root.winfo_rootx(), widget
                    assert (
                        widget.winfo_rootx() + widget.winfo_width()
                        <= root.winfo_rootx() + root.winfo_width()
                    ), widget
                    assert (
                        widget.winfo_rooty() + widget.winfo_height()
                        <= root.winfo_rooty() + root.winfo_height()
                    ), widget
        for source in sources:
            assert source.read_text().startswith("id,balance\n000")
        assert not errors, errors
    finally:
        app.close()
        deadline = time.monotonic() + 10
        while not app.closed:
            root.update()
            assert time.monotonic() < deadline
            time.sleep(0.01)


if __name__ == "__main__":
    run(sys.argv[1], Path(sys.argv[2]))
