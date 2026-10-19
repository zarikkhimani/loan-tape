"""Actual native field mapping, complete paging, text approval and lifecycle checks."""

import json
import os
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

from test_source_adapters import csv_scope, dictionary, xml_scope

from loan_tape import source_adapter_ui
from loan_tape.preview_ui import PreviewPanel
from loan_tape.session import start_session
from loan_tape.source_adapter_ui import SourceAdapterWindow
from loan_tape.source_adapters import load_scopes, save_mapping, scope_path
from loan_tape.transformations import derived_text_values
from loan_tape.workers import WorkerGroup


def main():
    scenario, work = sys.argv[1], Path(sys.argv[2])
    os.chdir(work)
    store = dictionary(work)
    table = None
    if scenario == "xml":
        source = work / "loans.xml"
        source.write_text(
            "<r>"
            + "".join(f'<loan id="{i:024d}"><name>CafÃ©</name></loan>' for i in range(65))
            + "</r>",
            encoding="utf-8",
        )
        table, scope = xml_scope(source)
        column = scope.metadata["headers"].index("name") + 1
    else:
        source, scope = csv_scope(work, ["CafÃ©"] * 65)
        column = 1
    before = source.read_bytes()
    root = tk.Tk()
    root.geometry("1200x900")
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    workers = WorkerGroup()
    jumps = []
    window = SourceAdapterWindow(
        root,
        source,
        store,
        workers,
        xml_table=table,
        current_xml=(lambda: table) if table else None,
        jump_xml=lambda *args: jumps.append(args),
    )

    def pump(until, limit=20):
        deadline = time.monotonic() + limit
        while not until():
            root.update()
            assert time.monotonic() < deadline, window.status.get()
            time.sleep(0.01)
        root.update()
        assert not errors, errors

    pump(lambda: not window.busy and window.records is not None)
    if scenario == "csv":
        window.window.geometry("860x700")
        root.update()
        right = window.window.winfo_rootx() + window.window.winfo_width()
        bottom = window.window.winfo_rooty() + window.window.winfo_height()
        for control in (
            window.save_button,
            window.map_button,
            window.preview_button,
            window.apply_button,
            window.audit_button,
            window.cancel_button,
        ):
            assert control.winfo_ismapped(), str(control)
            assert control.winfo_rootx() + control.winfo_width() <= right, str(control)
            assert control.winfo_rooty() + control.winfo_height() <= bottom, str(control)
    assert len(window.grid.get_children()) == 50
    assert str(window.apply_button["state"]) == "disabled"
    window.next.invoke()
    assert window.offset == 50
    window.previous.invoke()
    window.field.set(str(window.field_box["values"][column - 1]))
    window.map_button.invoke()
    editor = window.editor
    assert editor is not None
    choice = next(
        key
        for key, item in editor.fields_by_choice.items()
        if item and item.id == "loan.text:borrower_name"
    )
    editor.meaning.set(choice)
    editor._select_field()
    editor.save()
    assert editor.existing is not None, editor.status.get()
    editor.close()
    pump(lambda: str(window.preview_button["state"]) == "normal")
    assert window.scope.definitions[0].column == column

    if scenario == "shutdown":

        def slow(*args, cancelled, **kwargs):
            assert cancelled.wait(10)
            raise ValueError("cancelled")

        source_adapter_ui.review_source = slow
        window.preview_button.invoke()
        pump(lambda: bool(workers.active_names()))
        window.close()
        pump(lambda: not workers.active_names())
        assert source.read_bytes() == before
        root.destroy()
        return

    window.preview_button.invoke()
    pump(lambda: not window.busy)
    assert window.review is not None, window.status.get()
    assert window.review.preview.to_dict()["reconciliation"]["changed"] == 65
    assert not window.chosen
    first = 1 if scenario == "xml" else 2
    window.grid.selection_set(f"{first}:{column}")
    root.update()
    assert "source_sha256" in window.details.get("1.0", "end")
    window.include.invoke()
    assert window.chosen == {(first, column)}
    window.reviewer.set("Native synthetic reviewer")
    window.reason.set("Checked original literal text")

    if scenario in {"stale", "corrupt"}:
        if scenario == "corrupt":
            path = scope_path(window.scope.source_sha256)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["scopes"][0]["definitions"][0]["field"]["data_type"] = []
            path.write_text(json.dumps(data), encoding="utf-8")
        else:
            save_mapping(source, window.scope, None, column, store)
        pump(lambda: window.invalid)
        assert window.review is None and not window.chosen
        assert str(window.apply_button["state"]) == "disabled"
    else:
        window.apply_button.invoke()
        pump(lambda: not window.busy)
        assert window.parent is not None, window.status.get()
        assert derived_text_values(window.parent) == ((first, column, "Café"),)
        with patch.object(
            source_adapter_ui.filedialog, "asksaveasfilename", return_value=str(work / "audit.json")
        ):
            window.audit_button.invoke()
            pump(lambda: not window.busy)
        assert (work / "audit.json").exists(), window.status.get()
        window.mode.set("Exact replacement")
        window.exact_from.set("Café")
        window.exact_to.set("Cafe Holdings")
        window.preview_button.invoke()
        pump(lambda: not window.busy)
        assert window.review is not None
        assert len(window.grid.get_children()) == 1
        window.grid.selection_set(f"{first}:{column}")
        window.include_selected()
        window.apply_button.invoke()
        pump(lambda: not window.busy)
        assert derived_text_values(window.parent) == ((first, column, "Cafe Holdings"),)
        window.view.set("Source records")
        window.grid.selection_set(f"{first}:{column}")
        window.show_source()
        if table:
            assert jumps[-1] == (table, column, first)
        else:
            # A second saved CSV scope selects its own conventions and clears old approvals.
            window.name.set("Headerless copy of scope")
            window.header.set(False)
            window.save_button.invoke()
            pump(lambda: not window.busy and window.scope.name == "Headerless copy of scope")
            assert window.parent is None and window.scope.metadata["first_data_record"] == 1
            assert len(load_scopes(window.scope.source_sha256)) == 2
    window.close()
    pump(lambda: not workers.active_names())
    assert source.read_bytes() == before
    # Exercise the actual preview entry point and owned-dialog shutdown for CSV.
    if scenario == "csv":
        tabs = ttk.Notebook(root)
        tabs.pack(fill="both", expand=True)
        panel = PreviewPanel(
            tabs, source, start_session(), workers, lambda: None, lambda: None, store
        )
        tabs.add(panel.frame, text="Source")
        pump(lambda: not panel.busy and panel.preview is not None)
        panel.open_source_adapter()
        child = panel.source_adapter
        pump(lambda: child is not None and not child.busy and child.records is not None)
        panel.close()
        assert child.closed
        pump(lambda: not workers.active_names())
    root.destroy()


if __name__ == "__main__":
    main()
