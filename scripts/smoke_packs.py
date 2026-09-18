"""Exercise dictionary packs using the installed wheel and disposable external pack files."""

import json
import os
import shutil
import tempfile
import time
import tkinter as tk
from pathlib import Path

from loan_tape.pack_cli import main as packs_main
from loan_tape.pack_ui import PackManager
from loan_tape.packs import PackStore
from loan_tape.workers import WorkerGroup


def desktop_smoke(store: PackStore) -> None:
    if os.name != "nt" and not os.environ.get("DISPLAY"):
        print("No display: pack manager window checks skipped.")
        return
    root = tk.Tk()
    root.withdraw()
    workers = WorkerGroup()
    manager = PackManager(root, store, workers)
    callback_errors: list[object] = []
    root.report_callback_exception = lambda *args: callback_errors.append(args)

    def wait() -> None:
        deadline = time.monotonic() + 10
        while (
            manager.busy
            or workers.active_names()
            or (manager.editor is not None and manager.editor.busy)
        ):
            root.update()
            assert time.monotonic() < deadline, "Installed pack manager timed out"
            time.sleep(0.01)
        root.update()

    try:
        wait()
        assert manager.ready and len(manager.rows) == 1
        assert len(manager.fields.get_children()) == 4
        manager.activate_button.invoke()
        wait()
        assert store.pins()
        assert manager.version.get() == "Active version"
        manager.deactivate_button.invoke()
        wait()
        assert not store.pins()
        manager.copy_button.invoke()
        editor = manager.editor
        assert editor is not None
        pack_id, label = editor.metadata["id"], editor.inputs["label"]
        assert isinstance(pack_id, tk.StringVar) and isinstance(label, tk.StringVar)
        pack_id.set("custom.installed")
        label.set("Installed editor label")
        editor.content_pages.buttons["source"][0].invoke()
        dialog = editor.content_dialog
        assert dialog is not None
        for key, value in dict(
            id="installed.source",
            title="Installed source",
            version="2026",
            uri="urn:synthetic:installed",
        ).items():
            variable = dialog.inputs[key]
            assert isinstance(variable, tk.StringVar)
            variable.set(value)
        dialog.apply_button.invoke()
        assert dialog.closed, dialog.status.get()
        editor.content_pages.buttons["codes"][0].invoke()
        dialog = editor.content_dialog
        assert dialog is not None and dialog.rows is not None and dialog.references is not None
        variable = dialog.inputs["id"]
        assert isinstance(variable, tk.StringVar)
        variable.set("installed.codes")
        for key, value in dict(
            value="001", label="Exact code", definition="Preserve leading zeros."
        ).items():
            widget = dialog.rows.inputs[key]
            assert isinstance(widget, tk.Text)
            widget.insert("1.0", value)
        variable = dialog.references.inputs["source"]
        assert isinstance(variable, tk.StringVar)
        variable.set("installed.source")
        locator = dialog.references.inputs["locator"]
        assert isinstance(locator, tk.Text)
        locator.insert("1.0", "Codebook, page 2")
        dialog.apply_button.invoke()
        assert dialog.closed, dialog.status.get()
        editor.save_button.invoke()
        wait()
        assert editor.closed, editor.status.get()
        assert store.available_pack("custom.installed").fields[0].label == "Installed editor label"
        assert not store.pins()
        custom = store.available_pack("custom.installed")
        assert (
            next(source for source in custom.sources if source.id == "installed.source").title
            == "Installed source"
        )
        custom_codes = next(codes for codes in custom.code_lists if codes.id == "installed.codes")
        assert custom_codes.codes[0].value == "001"
        assert custom_codes.references[0].locator == "Codebook, page 2"
        manager.activate_button.invoke()
        wait()
        pin = store.pins()[0]
        manager.edit_button.invoke()
        editor = manager.editor
        assert editor is not None
        label = editor.inputs["label"]
        assert isinstance(label, tk.StringVar)
        label.set("Revised installed label")
        position = next(
            i
            for i, item in enumerate(editor.documents["code_lists.json"])
            if item["id"] == "installed.codes"
        )
        editor.content_pages.trees["codes"].selection_set(str(position))
        root.update()
        editor.content_pages.buttons["codes"][1].invoke()
        dialog = editor.content_dialog
        assert dialog is not None and dialog.rows is not None
        meaning = dialog.rows.inputs["definition"]
        assert isinstance(meaning, tk.Text)
        meaning.delete("1.0", "end")
        meaning.insert("1.0", "Revised local meaning.")
        dialog.apply_button.invoke()
        assert dialog.closed, dialog.status.get()
        editor.save_button.invoke()
        wait()
        assert editor.closed, editor.status.get()
        assert store.available_pack(pin.id).fields[0].label == "Revised installed label"
        assert store.snapshot(pin).fields[0].label == "Installed editor label"
        assert store.pins() == (pin,)
        assert (
            next(c for c in store.snapshot(pin).code_lists if c.id == "installed.codes")
            .codes[0]
            .definition
            == "Preserve leading zeros."
        )
        assert (
            next(c for c in store.available_pack(pin.id).code_lists if c.id == "installed.codes")
            .codes[0]
            .definition
            == "Revised local meaning."
        )
        manager.deactivate_button.invoke()
        wait()
        assert not store.pins()
        assert not callback_errors, callback_errors
    finally:
        manager.close()
        wait()
        root.destroy()
    print("Installed-wheel pack manager, fields, sources, citations, and allowed values passed.")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="pack-smoke-", dir=Path.cwd()) as temporary:
        work = Path(temporary)
        source = Path(__file__).resolve().parents[1] / "packs" / "example-loans"
        target = work / "packs" / "example-loans"
        shutil.copytree(source, target)
        store = PackStore(work / "packs", work / "state")
        assert store.catalog().fields == ()
        assert not store.state_dir.exists()
        args = ["--packs-dir", str(store.packs_dir), "--state-dir", str(store.state_dir)]
        assert packs_main([*args, "validate", str(target)]) == 0
        assert packs_main([*args, "activate", "example.loans"]) == 0
        original = store.pins()[0]
        fields_path = target / "fields.json"
        fields = json.loads(fields_path.read_text(encoding="utf-8"))
        fields[0]["label"] = "Edited ID"
        fields_path.write_text(json.dumps(fields), encoding="utf-8")
        reopened = PackStore(store.packs_dir, store.state_dir)
        assert (
            reopened.catalog().get_field("example.loans:loan_id").field.label == "Loan identifier"
        )
        assert packs_main([*args, "activate", "example.loans"]) == 0
        assert reopened.catalog().get_field("example.loans:loan_id").field.label == "Edited ID"
        assert reopened.pins()[0].fingerprint != original.fingerprint
        assert reopened.snapshot(original).fields[0].label == "Loan identifier"
        assert packs_main([*args, "deactivate", "example.loans"]) == 0
        assert reopened.catalog().fields == ()
        desktop_smoke(store)
    print("Installed-wheel pack lifecycle passed.")


if __name__ == "__main__":
    main()
