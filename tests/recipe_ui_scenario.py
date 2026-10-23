"""Actual native recipe save/load, per-step review, discard and owned shutdown."""

import faulthandler
import os
import sys
from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import patch
from weakref import ref

from recipe_support import prepare_recipe
from text_cleanup_ui_scenario import choose, preview, wait

from loan_tape.column_definitions import ColumnRules, definition_for_column, save_column_definition
from loan_tape.excel_compare import ComparisonSkipped
from loan_tape.recipes import list_recipes, load_recipe
from loan_tape.transformations import derived_text_values
from loan_tape.ui import LoanTapeApp, create_root
from loan_tape.workbook_index import ScanCancelled


def begin(root, manager):
    manager.context.set("Fictional October run")
    manager.reviewer.set("Recipe UI reviewer")
    assert manager.review_button.instate(["disabled"])
    manager.confirmed.set(True)
    manager.review_button.invoke()
    wait(root, lambda: not manager.busy)
    assert manager.child is not None and manager.binding is not None, manager.status.get()
    manager.child.window.withdraw()
    assert manager.child.review is None and not manager.child.selected


def run(scenario, work):
    os.chdir(work)
    context, _, seed, _ = prepare_recipe(work)
    original, source, intake, table, store = context
    before = original.read_bytes()
    root = create_root()
    root.withdraw()
    callback_errors = []
    root.report_callback_exception = lambda kind, error, traceback: callback_errors.append(
        f"{kind.__name__}: {error}"
    )
    app = LoanTapeApp(root, intake)
    app.pack_store = store
    release = Event()
    try:
        app.inspect_file()
        panel = app.inspector
        root.withdraw()
        wait(root, lambda: not panel.busy)
        panel.text_revisions[table.id] = seed
        panel._select_column(0)
        panel.cleanup_button.invoke()
        window = panel.text_cleanup
        window.window.withdraw()
        window.recipe_button.invoke()
        manager = window.recipe_window
        manager.window.withdraw()
        wait(root, lambda: not manager.busy)
        assert manager.recipe is None and not list_recipes()
        manager.name.set("Fictional recipe")
        manager.profile.set("Fictional loan template")
        manager.applicability.set("Same borrower roles; check reporting date on each tape.")
        manager.capture_button.invoke()
        wait(root, lambda: not manager.busy)
        assert manager.recipe is not None, manager.status.get()
        assert len(manager.steps.get_children()) == 2 and not list_recipes()
        initial = manager.recipe.fingerprint
        manager.steps.selection_set("1")
        manager.up_button.invoke()
        assert manager.recipe.fingerprint != initial
        manager.down_button.invoke()
        assert manager.recipe.fingerprint == initial
        manager.save_button.invoke()
        wait(root, lambda: not manager.busy)
        saved_recipe = list_recipes()[0][0]
        assert manager.library.size() == 1, manager.status.get()
        manager.library.selection_set(0)
        manager.load_button.invoke()
        wait(root, lambda: not manager.busy)
        assert manager.recipe == load_recipe(saved_recipe)
        assert manager.binding is None and not manager.confirmed.get()
        assert window.parent == seed and not list((work / ".artifacts/transformations").glob("*"))
        if scenario == "review":
            root.deiconify()
            window.window.deiconify()
            manager.window.deiconify()
            manager.window.geometry("900x790")
            root.update()
            right = manager.window.winfo_rootx() + manager.window.winfo_width()
            bottom = manager.window.winfo_rooty() + manager.window.winfo_height()
            for widget in (
                manager.steps,
                manager.detail,
                manager.review_button,
                manager.retention_label,
                manager.status_label,
            ):
                assert widget.winfo_height() > 15
                assert widget.winfo_rootx() + widget.winfo_width() <= right, widget
                assert widget.winfo_rooty() + widget.winfo_height() <= bottom, widget
            root.withdraw()
            window.window.withdraw()
            manager.window.withdraw()
        begin(root, manager)
        child = manager.child
        assert child.parent is None, (
            "A reusable recipe must begin from fresh source, not old approvals"
        )
        if scenario == "search-shutdown":
            target, action = (
                "loan_tape.recipe_run_ui.review_excel_recipe",
                child.preview_button.invoke,
            )
        else:
            preview(root, child)
            assert child.review.preview.to_dict()["reconciliation"]["changed"] == 2
            choose(child, "2:1")
            child.justification.set("Explicit first-step choice.")
            retired_window = child.window
            deletecommand = retired_window.deletecommand
            timer_errors = []

            def delete_live_command(name):
                if retired_window._tclCommands is None:
                    timer_errors.append(name)
                deletecommand(name)

            # Detect cleanup against a destroyed timer owner even when Tcl
            # happens to reject the deletion before Python sees the stale state.
            with patch.object(retired_window, "deletecommand", side_effect=delete_live_command):
                child.apply_button.invoke()
                wait(root, lambda: manager.child is not child)
            assert not timer_errors, "Recipe-step timer outlived its destroyed callback owner"
            retired = ref(child)
            child = manager.child
            app.workers.active_names()
            assert retired() is None, "Recipe step retained closed UI callbacks"
            child.window.withdraw()
            assert manager.staged is not None and window.parent == seed
            assert not list((work / ".artifacts/transformations").glob("*"))
            if scenario == "discard":
                child.reset_button.invoke()
                assert manager.staged is None and manager.binding is None and window.parent == seed
            elif scenario == "stale":
                definition = definition_for_column(table, 1)
                save_column_definition(
                    table, replace(definition, rules=ColumnRules(missing_tokens=("N/A", "UNKNOWN")))
                )
                wait(root, lambda: manager.binding is None)
                assert manager.staged is None and child.closed and window.parent == seed
            else:
                preview(root, child)
                assert child.review.preview.to_dict()["reconciliation"]["changed"] == 1
                choose(child, "2:1")
                child.justification.set("Explicit final-step choice.")
                if scenario == "apply-shutdown":
                    target, action = (
                        "loan_tape.recipe_run_ui.approve_excel_recipe_step",
                        child.apply_button.invoke,
                    )
                else:
                    child.apply_button.invoke()
                    wait(root, lambda: manager.binding is None)
                    assert child.closed and manager.staged is None
                    assert derived_text_values(window.parent) == ((2, 1, "Café Group"),)
                    assert len(list((work / ".artifacts/transformations").glob("*.json"))) == 1
                    assert original.read_bytes() == before == source.read_bytes()
                    retired_manager = ref(manager)
                    child = None
                    manager.close()
                    window.open_recipes()
                    manager = window.recipe_window
                    app.workers.active_names()
                    assert retired_manager() is None, "Recipe library retained closed callbacks"
                    manager.window.withdraw()
                    wait(root, lambda: not manager.busy)
                    assert manager.library.size() == 1
        if scenario.endswith("shutdown"):
            started, cleaning = Event(), Event()

            def paused(*args, cancelled, **kwargs):
                started.set()
                assert cancelled.wait(5)
                cleaning.set()
                assert release.wait(5)
                raise ScanCancelled("Synthetic cancellation")

            with patch(target, side_effect=paused):
                action()
                wait(root, started.is_set)
                app.close()
                assert app.closing and not app.closed and child.closed and manager.closed
                assert cleaning.wait(5) and source.exists() and app.workers.active_names()
                release.set()
                wait(root, lambda: app.closed)
        else:
            app.close()
            wait(root, lambda: app.closed)
        assert not source.exists() and not app.workers.active_names()
        assert not list((work / ".artifacts/transformations").glob("*"))
        assert (
            saved_recipe.exists()
            and load_recipe(saved_recipe).to_dict()["name"] == "Fictional recipe"
        )
        assert original.read_bytes() == before
        assert not callback_errors, callback_errors
        print(f"{scenario}: native recipes, explicit approvals and retention passed")
    finally:
        release.set()
        if not app.closed:
            app.close()
            wait(root, lambda: app.closed)


if __name__ == "__main__":
    # Recipe behavior must not depend on Office startup fitting the 15-second UI
    # wait. The separate Excel checks retain actual Office integration coverage.
    faulthandler.dump_traceback_later(35)
    try:
        with patch(
            "loan_tape.excel_compare.read_xlwings_preview",
            side_effect=ComparisonSkipped(
                "Optional Excel comparison is outside this recipe UI scenario."
            ),
        ):
            run(sys.argv[1], Path(sys.argv[2]))
    finally:
        faulthandler.cancel_dump_traceback_later()
