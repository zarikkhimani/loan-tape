"""Native controls: real suggestions, literal drafts, explicit approvals and teardown."""

import os
import sys
from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import patch
from weakref import ref

from text_cleanup_support import prepare
from text_cleanup_ui_scenario import choose, preview, wait

from loan_tape.column_definitions import (
    ColumnRules,
    definition_for_column,
    save_column_definition,
    snapshot_field,
)
from loan_tape.excel_compare import ComparisonSkipped
from loan_tape.transformations import derived_text_values
from loan_tape.ui import LoanTapeApp, create_root
from loan_tape.workbook_index import ScanCancelled


def fill(root, widget, text):
    widget.delete("1.0", "end")
    widget.insert("1.0", text)
    root.update()


def bounds(root, editor):
    editor.window.deiconify()
    editor.window.geometry("860x740")
    root.update()
    right = editor.window.winfo_rootx() + editor.window.winfo_width()
    bottom = editor.window.winfo_rooty() + editor.window.winfo_height()
    for widget in (
        editor.source_text,
        editor.target_text,
        editor.rule_grid,
        editor.candidates,
        editor.find_button,
        editor.candidate_button,
        editor.use_button,
        editor.status_label,
    ):
        assert widget.winfo_height() >= 20, (widget, widget.winfo_height())
        assert widget.winfo_rootx() + widget.winfo_width() <= right, widget
        assert widget.winfo_rooty() + widget.winfo_height() <= bottom, widget
    editor.window.withdraw()


def run(scenario, work):
    os.chdir(work)
    values = (
        ["current", "CURRENT", "CURRENT "]
        if scenario == "category"
        else ["Acme Hldings"] * 211
        + ["Acme Holdings"] * 2
        + [f"Fictional{i:03}" for i in range(211)]
    )
    original, saved, intake, table, store = prepare(work, values)
    before = original.read_bytes()
    if scenario == "category":
        catalog = store.catalog()
        definition = definition_for_column(table, 1)
        save_column_definition(
            table,
            replace(
                definition, field=snapshot_field(catalog, catalog.get_field("example.loans:status"))
            ),
        )
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
        panel._select_column(0)
        panel.cleanup_button.invoke()
        window = panel.text_cleanup
        window.window.withdraw()
        window.mode.set("Exact replacements")
        window.rule_button.invoke()
        editor = window.rule_editor
        editor.window.withdraw()
        root.update()
        assert window.preview_button.instate(["disabled"])
        assert not editor.rules.rules and not editor.suggestions
        if scenario == "review":
            root.deiconify()
            window.window.deiconify()
            bounds(root, editor)
            root.withdraw()
            window.window.withdraw()
            fill(root, editor.source_text, "Acme Hldings")
            editor.threshold.set("0")
            editor.find_button.invoke()
            wait(root, lambda: not editor.busy)
            assert editor.suggestions is not None, editor.status.get()
            assert len(editor.candidates.get_children()) == 200
            assert editor.suggestions.eligible_count == len(values)
            assert not editor.candidates.selection() and not editor.rules.rules
            assert editor.suggestions.candidates[0].text == "Acme Holdings"
            assert editor.suggestions.candidates[0].count == 2
            editor.next.invoke()
            assert len(editor.candidates.get_children()) == 12
            editor.previous.invoke()
            editor.candidates.selection_set("0")
            root.update()
            assert not editor.rules.rules
            editor.candidate_button.invoke()
            assert len(editor.rules.rules) == 1 and editor.rules.rules[0].suggestion is not None
            editor.candidate_button.invoke()
            assert "Duplicate" in editor.status.get() and len(editor.rules.rules) == 1
            editor.threshold.set("95")
            assert editor.suggestions is None
            editor.use_button.invoke()
            assert editor.closed and window.review is None and len(window.exact_settings.rules) == 1
            preview(root, window)
            assert window.review.preview.to_dict()["reconciliation"]["changed"] == 211
            assert len(window.grid.get_children()) == 200 and not window.selected
            choose(window, "2:1")
            window.next.invoke()
            choose(window, "212:1")
            window.reviewer.set("Synthetic reviewer")
            window.justification.set("Reviewed these two literal replacements.")
            window.apply_button.invoke()
            wait(root, lambda: not window.busy)
            assert window.applied, window.status.get()
            assert derived_text_values(window.parent) == (
                (2, 1, "Acme Holdings"),
                (212, 1, "Acme Holdings"),
            )
            assert saved.read_bytes() == before == original.read_bytes()
            assert len(list((work / ".artifacts/transformations").glob("*.json"))) == 1
            retired = ref(editor)
            window.rule_button.invoke()
            editor = window.rule_editor
            assert retired() is None, "Closed rule editor retained callbacks"
            editor.window.withdraw()
            editor.rule_grid.selection_set("0")
            editor.remove_button.invoke()
            assert not editor.rules.rules
            editor.close()
            assert len(window.exact_settings.rules) == 1
            window.mode.set("Repair text")
            assert window.review is None and not window.selected
            preview(root, window)
            assert window.review.preview.to_dict()["reconciliation"]["changed"] == 0
            window.start_from_source()
            assert window.parent is None
        elif scenario == "category":
            assert editor.find_button.instate(["disabled"])
            editor.show_allowed()
            assert "CURRENT" in editor.detail.get("1.0", "end")
            fill(root, editor.source_text, "current")
            fill(root, editor.target_text, "Current")
            editor.add_button.invoke()
            assert "allowed-value" in editor.status.get() and not editor.rules.rules
            fill(root, editor.target_text, "CURRENT")
            editor.add_button.invoke()
            assert len(editor.rules.rules) == 1
            editor.use_button.invoke()
            preview(root, window)
            assert window.review.preview.to_dict()["reconciliation"]["changed"] == 1
            choose(window, "2:1")
            window.reviewer.set("Category reviewer")
            window.justification.set("Checked allowed code and source meaning.")
            window.apply_button.invoke()
            wait(root, lambda: not window.busy)
            assert window.applied, window.status.get()
            assert derived_text_values(window.parent) == ((2, 1, "CURRENT"),)
        elif scenario == "stale":
            fill(root, editor.source_text, " Acme ")
            fill(root, editor.target_text, " Acme Ltd ")
            editor.add_button.invoke()
            assert editor.rules.rules[0].source == " Acme "
            definition = definition_for_column(table, 1)
            save_column_definition(
                table, replace(definition, rules=ColumnRules(missing_tokens=("N/A", "UNKNOWN")))
            )
            wait(root, lambda: editor.stale)
            assert editor.use_button.instate(["disabled"])
            editor.use_rules()
            assert not window.exact_settings.rules
            editor.close()
        else:
            started, cleaning = Event(), Event()

            def paused(*args, cancelled, **kwargs):
                started.set()
                assert cancelled.wait(5)
                cleaning.set()
                assert release.wait(5)
                raise ScanCancelled("Synthetic cancellation")

            fill(root, editor.source_text, "Acme Hldings")
            with patch("loan_tape.text_rules_ui.suggest_excel_text", side_effect=paused):
                editor.find_button.invoke()
                wait(root, started.is_set)
                if scenario == "cancel-search":
                    editor.cancel_button.invoke()
                    assert cleaning.wait(5)
                    assert not editor.rules.rules and editor.suggestions is None
                    release.set()
                    wait(root, lambda: not editor.busy)
                else:
                    app.close()
                    assert app.closing and not app.closed and editor.closed and window.closed
                    assert cleaning.wait(5)
                    assert app.workers.active_names() and saved.exists()
                    release.set()
                    wait(root, lambda: app.closed)
            if scenario == "cancel-search":
                editor.find_button.invoke()
                wait(root, lambda: not editor.busy)
                assert editor.suggestions is not None, editor.status.get()
        if not app.closed:
            app.close()
            wait(root, lambda: app.closed)
        assert not app.workers.active_names() and not saved.exists()
        assert not list((work / ".artifacts/transformations").glob("*"))
        assert original.read_bytes() == before
        print(f"{scenario}: native exact rules and spelling workflow passed")
    finally:
        release.set()
        if not app.closed:
            app.close()
            wait(root, lambda: app.closed)


if __name__ == "__main__":
    # Rule review does not depend on optional Office startup. The dedicated
    # Excel smoke still exercises the actual owned-process integration.
    with patch(
        "loan_tape.excel_compare.read_xlwings_preview",
        side_effect=ComparisonSkipped(
            "Optional Excel comparison is outside this rules UI scenario."
        ),
    ):
        run(sys.argv[1], Path(sys.argv[2]))
