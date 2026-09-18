"""Exercise source/list/citation controls with isolated synthetic packs and native Tk."""

import json
import shutil
import sys
import time
from pathlib import Path
from unittest.mock import patch

from pack_editor_scenarios import put, saved, wait

from loan_tape.intake import IntakeStore
from loan_tape.ui import LoanTapeApp, create_root


def open_content(root, editor, mode, *, new=False, index=0):
    editor.tabs.select(2 if mode == "source" else 3)
    page = editor.content_pages
    if not new:
        page.trees[mode].selection_set(str(index))
    root.update()
    page.buttons[mode][0 if new else 1].invoke()
    root.update()
    assert editor.content_dialog is not None
    return editor.content_dialog


def apply_content(root, editor, dialog):
    dialog.apply_button.invoke()
    root.update()
    assert dialog.closed, dialog.status.get()
    assert editor.content_dialog is None


def add_source(root, editor):
    dialog = open_content(root, editor, "source", new=True)
    put(
        dialog.inputs,
        id="review.source",
        title="Reviewed synthetic dictionary",
        version="2026",
        uri="urn:synthetic:review",
        sha256="a" * 64,
    )
    apply_content(root, editor, dialog)


def run(scenario):
    source = Path(__file__).resolve().parents[1] / "packs" / "example-loans"
    shutil.copytree(source, Path("packs/example-loans"))
    root = create_root()
    root.withdraw()
    app = LoanTapeApp(root, IntakeStore(Path("inputs")))
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    app.packs_button.invoke()
    manager = app.pack_manager
    wait(root, lambda: manager.busy)
    store = manager.store
    base = store.available_pack("example.loans")
    pin = store.activate(base.id)
    manager.refresh()
    wait(root, lambda: manager.busy)
    manager.edit_button.invoke()
    editor = manager.editor
    assert editor is not None and not editor.dirty()
    try:
        if scenario == "sources":
            dialog = open_content(root, editor, "source", new=True)
            put(
                dialog.inputs,
                id="review.source",
                title="Synthetic source",
                version="2026",
                uri="urn:synthetic:source",
                sha256="bad hash",
            )
            dialog.apply_button.invoke()
            root.update()
            assert not dialog.closed and "hexadecimal" in dialog.status.get()
            assert len(editor.documents["sources.json"]) == len(base.sources)
            assert editor.dirty()
            put(dialog.inputs, sha256="a" * 64)
            apply_content(root, editor, dialog)
            index = len(editor.documents["sources.json"]) - 1
            dialog = open_content(root, editor, "source", index=index)
            put(dialog.inputs, title="Revised source title", sha256="")
            apply_content(root, editor, dialog)
            # An unrelated pending field edit survives opening/applying a source dialog.
            put(editor.inputs, label="Pending field label")
            dialog = open_content(root, editor, "source", index=index)
            put(dialog.inputs, version="2027")
            apply_content(root, editor, dialog)
            assert editor._field()["label"] == "Pending field label"
            saved(root, manager, editor)
            updated = store.available_pack(base.id)
            record = next(s for s in updated.sources if s.id == "review.source")
            assert (record.title, record.version, record.sha256) == (
                "Revised source title",
                "2027",
                None,
            )
            assert updated.fields[0].label == "Pending field label"
        elif scenario == "codes":
            # Pending category edits can create their missing list without being discarded.
            put(editor.inputs, data_type="category")
            dialog = open_content(root, editor, "codes", new=True)
            put(dialog.inputs, id="review.status")
            put(dialog.rows.inputs, value="001", label="First", definition="Literal first code")
            dialog.rows.add_button.invoke()
            put(dialog.rows.inputs, value="001", label="Duplicate", definition="Must be corrected")
            dialog.apply_button.invoke()
            assert not dialog.closed and "already exists" in dialog.status.get()
            put(
                dialog.rows.inputs,
                value=" ND1\n",
                label="Multiline\nlabel",
                definition="Retain spaces\nand newlines",
            )
            apply_content(root, editor, dialog)
            assert editor._field()["data_type"] == "category"
            for choice in editor.code_choices:
                assert "review.status" in choice.cget("values")
            put(
                editor.inputs,
                code_list="review.status",
                missing_code_list="review.status",
                missing_codes="001",
            )
            editor.apply_button.invoke()
            assert editor.documents["fields.json"][0]["code_list"] == "review.status"
            index = len(editor.documents["code_lists.json"]) - 1
            dialog = open_content(root, editor, "codes", index=index)
            dialog.rows.remove_button.invoke()
            dialog.apply_button.invoke()
            assert not dialog.closed and "missing_codes" in dialog.status.get()
            assert len(editor.documents["code_lists.json"][index]["codes"]) == 2
            with patch("loan_tape.pack_content_ui.messagebox.askokcancel", return_value=True):
                dialog.cancel_button.invoke()
            editor.content_pages.trees["codes"].selection_set(str(index))
            root.update()
            editor.content_pages.buttons["codes"][2].invoke()
            assert "still used by fields loan_id" in editor.status.get()
            saved(root, manager, editor)
            pack = store.available_pack(base.id)
            codes = next(c for c in pack.code_lists if c.id == "review.status").codes
            assert [c.value for c in codes] == ["001", " ND1\n"]
            assert codes[1].label == "Multiline\nlabel"
            # Reopening and changing only pack metadata preserves every literal code.
            manager.edit_button.invoke()
            editor = manager.editor
            dialog = open_content(root, editor, "codes", index=index)
            assert not dialog.dirty()
            apply_content(root, editor, dialog)
            put(editor.metadata, version="1.1.0")
            saved(root, manager, editor)
            assert store.available_pack(base.id).code_lists == pack.code_lists
        elif scenario == "citations":
            add_source(root, editor)
            editor.citations_button.invoke()
            dialog = editor.content_dialog
            dialog.references.add_button.invoke()
            put(
                dialog.references.inputs,
                source="review.source",
                locator="Fields!B3:D3\nReviewed page 2",
            )
            apply_content(root, editor, dialog)
            index = next(
                i
                for i, s in enumerate(editor.documents["sources.json"])
                if s["id"] == "review.source"
            )
            editor.content_pages.trees["source"].selection_set(str(index))
            root.update()
            editor.content_pages.buttons["source"][2].invoke()
            assert "still cited by field loan_id" in editor.status.get()
            # Add a list-level citation as well, without reauthoring its existing code meanings.
            dialog = open_content(root, editor, "codes")
            dialog.tabs.select(1)
            dialog.references.add_button.invoke()
            put(dialog.references.inputs, source="review.source", locator="Codebook, page 4")
            apply_content(root, editor, dialog)
            saved(root, manager, editor)
            updated = store.available_pack(base.id)
            assert updated.fields[0].references[-1].locator == "Fields!B3:D3\nReviewed page 2"
            assert updated.code_lists[0].references[-1].locator == "Codebook, page 4"
            assert updated.code_lists[0].codes == base.code_lists[0].codes
        elif scenario == "closing":
            dialog = open_content(root, editor, "codes", new=True)
            put(dialog.rows.inputs, value="Unsaved value")
            assert dialog.dirty() and editor.dirty()
            editor.save_button.invoke()
            assert not editor.busy
            with patch("loan_tape.pack_content_ui.messagebox.askokcancel", return_value=False):
                dialog.cancel_button.invoke()
                app.request_exit()
            assert not dialog.closed and not editor.closed and not app.closing
            assert dialog.rows.inputs["value"].get("1.0", "end-1c") == "Unsaved value"
            with patch("loan_tape.pack_content_ui.messagebox.askokcancel", return_value=True):
                dialog.cancel_button.invoke()
            assert not editor.dirty() and store.available_pack(base.id) == base
            # An applied addition is still just a pack draft and can be discarded as a whole.
            add_source(root, editor)
            assert editor.dirty()
            with patch("loan_tape.pack_editor_ui.messagebox.askokcancel", return_value=True):
                assert manager.close()
            assert store.available_pack(base.id) == base
        elif scenario == "removal":
            add_source(root, editor)
            editor.content_pages.trees["source"].selection_set(
                str(len(editor.documents["sources.json"]) - 1)
            )
            root.update()
            editor.content_pages.buttons["source"][2].invoke()
            assert len(editor.documents["sources.json"]) == len(base.sources)
            dialog = open_content(root, editor, "codes", new=True)
            put(dialog.inputs, id="unused.list")
            put(dialog.rows.inputs, value="0", label="Zero code", definition="Zero is literal text")
            apply_content(root, editor, dialog)
            editor.content_pages.trees["codes"].selection_set(
                str(len(editor.documents["code_lists.json"]) - 1)
            )
            root.update()
            editor.content_pages.buttons["codes"][2].invoke()
            assert len(editor.documents["code_lists.json"]) == len(base.code_lists)
            # The automatic provenance source remains visibly protected.
            index = len(editor.documents["sources.json"]) - 1
            editor.content_pages.trees["source"].selection_set(str(index))
            root.update()
            assert editor.content_pages.buttons["source"][1].instate(["disabled"])
            assert editor.content_pages.buttons["source"][2].instate(["disabled"])
        elif scenario.startswith("layout"):
            root.deiconify()
            if scenario.endswith("scaled"):
                root.tk.call("tk", "scaling", 2.0)
            editor.window.geometry("820x580")
            for mode in ("source", "codes"):
                dialog = open_content(root, editor, mode, new=True)
                dialog.window.geometry("660x580")
                pages = dialog.tabs.tabs() if mode == "codes" else [None]
                for page in pages:
                    if page is not None:
                        dialog.tabs.select(page)
                    root.update()
                    widgets = [dialog.apply_button, dialog.cancel_button, dialog.status_label]
                    if mode == "codes":
                        form = dialog.rows if page == pages[0] else dialog.references
                        widgets += [
                            form.tree,
                            form.add_button,
                            form.apply_button,
                            form.remove_button,
                        ]
                    for widget in widgets:
                        assert widget.winfo_ismapped()
                        assert widget.winfo_width() > 10 and widget.winfo_height() > 10
                        assert widget.winfo_rootx() >= dialog.window.winfo_rootx()
                        assert (
                            widget.winfo_rootx() + widget.winfo_width()
                            <= dialog.window.winfo_rootx() + dialog.window.winfo_width()
                        )
                        assert (
                            widget.winfo_rooty() + widget.winfo_height()
                            <= dialog.window.winfo_rooty() + dialog.window.winfo_height()
                        )
                dialog.cancel_button.invoke()
            assert not editor.dirty()
        else:
            raise AssertionError(scenario)
        assert store.snapshot(pin) == base and store.pins() == (pin,)
        # All preserved files remain valid JSON even after failed content edits.
        for file in Path("packs/example-loans").glob("*.json"):
            json.loads(file.read_text(encoding="utf-8"))
    finally:
        with patch("loan_tape.pack_editor_ui.messagebox.askokcancel", return_value=True):
            app.close()
        deadline = time.monotonic() + 10
        while not app.closed:
            root.update()
            assert time.monotonic() < deadline
            time.sleep(0.01)
    assert not errors, errors


if __name__ == "__main__":
    run(sys.argv[1])
