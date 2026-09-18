"""Stage-one XML uses the existing native preview and worker lifecycle."""

import sys
import time
from pathlib import Path
from threading import Event
from unittest.mock import patch

from desktop_scenarios import dispatch_drop, wait_for_copy, wait_for_preview

from loan_tape.intake import IntakeStore
from loan_tape.preview_ui import PreviewPanel
from loan_tape.ui import LoanTapeApp, create_root
from loan_tape.xml_preview import _Target


def run(scenario: str, work: Path) -> None:
    root = create_root()
    root.withdraw()
    failures = []
    root.report_callback_exception = lambda *error: failures.append(error)
    app = LoanTapeApp(root, IntakeStore(work / "inputs"))
    source = work / "sample.xml"
    payload = b'<root><loans><loan id="0001"><balance>100.00</balance></loan><loan id="0002"><balance>0</balance></loan></loans><fees><fee>5</fee><fee>6</fee></fees></root>'
    source.write_bytes(payload)
    try:
        if scenario == "preview":
            with patch(
                "loan_tape.ui.filedialog.askopenfilename", return_value=str(source)
            ) as choose:
                app.browse()
                assert "*.xml" in choose.call_args.kwargs["filetypes"][0][1]
            wait_for_copy(app)
            with patch(
                "loan_tape.preview_ui.read_parallel_preview",
                side_effect=AssertionError("XML must not use the Excel reader"),
            ):
                app.inspect_file()
                wait_for_preview(app)
                inspector = app.inspector
                assert isinstance(inspector, PreviewPanel)
                assert inspector.navigator is None
                assert inspector.xml_group_selector is not None
                assert inspector.zoom.get() == "80%"
                assert inspector.open_excel_button.instate(["disabled"])
                assert inspector.open_excel_button.winfo_manager() == ""
                assert not inspector.table.get_children()
                assert "Choose a record group" in inspector.status.get()
                inspector.xml_group.set("/root/loans/loan")
                inspector.xml_group_selector.event_generate("<<ComboboxSelected>>")
                root.update()
                wait_for_preview(app)
                assert inspector.table.item("1", "values") == ("0001", "100.00")
                assert inspector.table.heading("A", "text").endswith("@id")
                assert "2 records" in inspector.status.get()
                inspector.table.selection_set("1")
                inspector._selection()
                assert "/root[1]/loans[1]/loan[1]/@id" in inspector.cell_text.get("1.0", "end")
                inspector.xml_group.set("/root/fees/fee")
                inspector.xml_group_selector.event_generate("<<ComboboxSelected>>")
                root.update()
                wait_for_preview(app)
                assert inspector.table.item("2", "values") == ("6",)
                with patch(
                    "loan_tape.preview_ui.open_in_excel",
                    side_effect=AssertionError("Do not launch XML in Excel"),
                ):
                    inspector._open_in_excel()
            assert source.read_bytes() == payload
            assert Path(app.saved_path.get()).read_bytes() == payload
        elif scenario == "error":
            source.write_bytes(b"<loans><loan>100</wrong></loans>")
            assert dispatch_drop(app, [source]) == "copy"
            wait_for_copy(app)
            app.inspect_file()
            wait_for_preview(app)
            assert app.inspector.preview is None
            assert not app.inspector.table.get_children()
            assert "Could not parse XML" in app.inspector.status.get()
        elif scenario == "close":
            source.write_bytes(b"<r><v>text</v></r>")
            app.add_file(source)
            wait_for_copy(app)
            started = Event()
            original = _Target.data

            def slow(target, value):
                started.set()
                assert target.cancelled.wait(5), "Close did not cancel XML parsing"
                original(target, value)

            with patch.object(_Target, "data", slow):
                app.inspect_file()
                app.root.withdraw()
                deadline = time.monotonic() + 5
                while not started.is_set():
                    root.update()
                    assert time.monotonic() < deadline
                    time.sleep(0.01)
                app.close()
                while not app.closed:
                    root.update()
                    assert time.monotonic() < deadline
                    time.sleep(0.01)
                assert not app.workers.active_names()
        else:
            raise AssertionError(scenario)
        assert not failures, failures
    finally:
        if not app.closed:
            app.close()
            deadline = time.monotonic() + 5
            while not app.closed:
                root.update()
                assert time.monotonic() < deadline
                time.sleep(0.01)


if __name__ == "__main__":
    run(sys.argv[1], Path(sys.argv[2]))
