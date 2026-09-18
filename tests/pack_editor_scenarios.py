"""Button-driven pack creation, field edits, recovery, and unsaved-draft protection."""

import json
import shutil
import sys
import time
import tkinter as tk
from pathlib import Path
from threading import Event
from unittest.mock import patch

from loan_tape.intake import IntakeStore
from loan_tape.pack_authoring import save_draft
from loan_tape.ui import LoanTapeApp, create_root


def wait(root, predicate):
    deadline = time.monotonic() + 10
    while predicate():
        root.update()
        assert time.monotonic() < deadline, "Editor did not finish"
        time.sleep(0.01)
    root.update()


def put(mapping, **values):
    for name, value in values.items():
        widget = mapping[name]
        if isinstance(widget, tk.Text):
            widget.delete("1.0", "end")
            widget.insert("1.0", value)
        else:
            widget.set(value)


def saved(root, manager, editor):
    editor.save_button.invoke()
    wait(root, lambda: editor.busy)
    assert editor.closed, editor.status.get()
    wait(root, lambda: manager.busy)


def run(scenario):
    shutil.copytree(Path(__file__).resolve().parents[1] / "packs", "packs")
    root = create_root()
    root.withdraw()
    app = LoanTapeApp(root, IntakeStore(Path("inputs")))
    callback_errors = []
    root.report_callback_exception = lambda *args: callback_errors.append(args)
    app.packs_button.invoke()
    manager = app.pack_manager
    wait(root, lambda: manager.busy)
    store = manager.store
    base = store.available_pack("example.loans")
    row = next(row for row in manager.rows.values() if row.pack_id == base.id)
    manager.tree.selection_set(row.key)
    root.update()
    try:
        if scenario == "new":
            manager.new_button.invoke()
            editor = manager.editor
            assert not editor.dirty()
            put(
                editor.metadata, id="custom.clo", name="Custom CLO", description="Local definitions"
            )
            put(
                editor.inputs,
                id="loan_id",
                label="Loan identifier",
                definition="Keep the supplied identifier as text.",
                data_type="identifier",
                required="Yes",
                blank_allowed="No",
            )
            saved(root, manager, editor)
            pack = store.available_pack("custom.clo")
            assert len(pack.fields) == 1
            assert pack.fields[0].data_type == "identifier"
            assert pack.fields[0].required is True and pack.fields[0].blank_allowed is False
            assert not store.pins()
            assert manager._selected().pack_id == pack.id
        elif scenario == "edit":
            pin = store.activate(base.id)
            manager.refresh()
            wait(root, lambda: manager.busy)
            manager.edit_button.invoke()
            editor = manager.editor
            assert str(editor.id_entry.cget("state")) == "readonly"
            put(editor.inputs, label="Custom loan identifier")
            editor.add_button.invoke()
            assert editor.documents["fields.json"][0]["label"] == "Custom loan identifier"
            put(
                editor.inputs,
                id="custom_amount",
                label="Custom amount",
                definition="Amount supplied for this review.",
                data_type="decimal",
                unit="currency units",
                aliases="custom balance\nreview amount",
                context="currency\nreporting_date",
            )
            saved(root, manager, editor)
            updated = store.available_pack(base.id)
            assert len(updated.fields) == 5
            assert updated.fields[-1].aliases == ("custom balance", "review amount")
            assert updated.fields[0].label == "Custom loan identifier"
            assert store.snapshot(pin) == base
            assert store.pins() == (pin,)
            assert manager._selected().status == "Active — edits available"
            manager.activate_button.invoke()
            wait(root, lambda: manager.busy)
            assert store.pins()[0].fingerprint == updated.fingerprint
            manager.edit_button.invoke()
            editor = manager.editor
            editor.remove_button.invoke()
            saved(root, manager, editor)
            assert len(store.available_pack(base.id).fields) == 4
        elif scenario == "copy":
            manager.copy_button.invoke()
            editor = manager.editor
            put(editor.metadata, id="custom.copy", name="Custom copy")
            put(editor.inputs, definition="Reviewed local meaning.")
            saved(root, manager, editor)
            copied = store.available_pack("custom.copy")
            assert copied.code_lists == base.code_lists
            assert copied.fields[0].definition == "Reviewed local meaning."
            assert store.available_pack(base.id) == base
            assert base.fingerprint in copied.sources[-2].uri
        elif scenario == "conflict":
            manager.edit_button.invoke()
            editor = manager.editor
            put(editor.inputs, label="Draft that must survive", data_type="category")
            editor.apply_button.invoke()
            assert "require a code_list" in editor.status.get()
            assert editor.documents["fields.json"][0]["label"] == base.fields[0].label
            put(editor.inputs, data_type="identifier")
            path = Path("packs/example-loans/pack.json")
            data = json.loads(path.read_text(encoding="utf-8"))
            data["name"] = "Changed outside editor"
            path.write_text(json.dumps(data), encoding="utf-8")
            editor.save_button.invoke()
            wait(root, lambda: editor.busy)
            assert not editor.closed
            assert "changed since editing began" in editor.status.get()
            assert editor._field()["label"] == "Draft that must survive"
            assert store.available_pack(base.id).name == "Changed outside editor"
            editor.copy_button.invoke()
            assert str(editor.id_entry.cget("state")) == "normal"
            put(editor.metadata, id="custom.recovered", name="Recovered draft")
            saved(root, manager, editor)
            assert (
                store.available_pack("custom.recovered").fields[0].label
                == "Draft that must survive"
            )
            assert store.available_pack(base.id).name == "Changed outside editor"
        elif scenario == "roundtrip":
            manifest = Path("packs/example-loans/pack.json")
            fields = Path("packs/example-loans/fields.json")
            meta = json.loads(manifest.read_text(encoding="utf-8"))
            values = json.loads(fields.read_text(encoding="utf-8"))
            meta["asset_classes"] = ["A multiline\nasset class"]
            values[0]["aliases"] = ["A multiline\nname"]
            values[0]["context"] = ["A multiline\ncontext"]
            manifest.write_text(json.dumps(meta), encoding="utf-8")
            fields.write_text(json.dumps(values), encoding="utf-8")
            manager.refresh()
            wait(root, lambda: manager.busy)
            manager.edit_button.invoke()
            editor = manager.editor
            assert not editor.dirty()
            put(editor.inputs, label="Edited name only")
            saved(root, manager, editor)
            pack = store.available_pack(base.id)
            assert pack.asset_classes == tuple(meta["asset_classes"])
            assert pack.fields[0].aliases == tuple(values[0]["aliases"])
            assert pack.fields[0].context == tuple(values[0]["context"])
        elif scenario == "closing":
            manager.edit_button.invoke()
            editor = manager.editor
            put(editor.inputs, label="Unsaved label")
            with patch(
                "loan_tape.pack_editor_ui.messagebox.askokcancel", return_value=False
            ) as question:
                assert not manager.close()
                app.request_exit()
                assert question.call_count == 2
                assert not app.closing and not editor.closed and not manager.closing
            with patch("loan_tape.pack_editor_ui.messagebox.askokcancel", return_value=True):
                assert manager.close()
            assert editor.closed and manager.closed
            assert store.available_pack(base.id) == base
            app.packs_button.invoke()
            manager = app.pack_manager
            wait(root, lambda: manager.busy)
            row = next(row for row in manager.rows.values() if row.pack_id == base.id)
            manager.tree.selection_set(row.key)
            root.update()
            manager.edit_button.invoke()
            editor = manager.editor
            put(editor.inputs, label="Unsaved label")
            release = Event()

            def delayed(*args, **kwargs):
                assert release.wait(8)
                return save_draft(*args, **kwargs)

            with patch("loan_tape.pack_editor_ui.save_draft", side_effect=delayed):
                try:
                    editor.save_button.invoke()
                    app.request_exit()
                    assert not app.closing and editor.busy
                    assert "in progress" in editor.status.get()
                finally:
                    release.set()
                wait(root, lambda: editor.busy)
                wait(root, lambda: manager.busy)
            assert editor.closed
            assert store.available_pack(base.id).fields[0].label == "Unsaved label"
        elif scenario == "layout":
            manager.edit_button.invoke()
            editor = manager.editor
            root.deiconify()
            manager.window.deiconify()
            editor.window.deiconify()
            editor.window.geometry("820x580")
            for page in editor.tabs.tabs():
                editor.tabs.select(page)
                root.update()
                for widget in (editor.save_button, editor.copy_button, editor.status_label):
                    assert widget.winfo_width() > 10 and widget.winfo_height() > 10
                    assert (
                        widget.winfo_rootx() + widget.winfo_width()
                        <= editor.window.winfo_rootx() + editor.window.winfo_width()
                    )
                    assert (
                        widget.winfo_rooty() + widget.winfo_height()
                        <= editor.window.winfo_rooty() + editor.window.winfo_height()
                    )
    finally:
        with patch("loan_tape.pack_editor_ui.messagebox.askokcancel", return_value=True):
            app.close()
        deadline = time.monotonic() + 10
        while not app.closed:
            root.update()
            assert time.monotonic() < deadline
            time.sleep(0.01)
    assert not callback_errors, callback_errors


if __name__ == "__main__":
    run(sys.argv[1])
