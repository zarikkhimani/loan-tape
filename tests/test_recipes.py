import json
from dataclasses import replace
from threading import Event

import pytest
from recipe_support import approval, prepare_recipe
from text_cleanup_support import prepare

from loan_tape._date_json import canonical
from loan_tape.column_definitions import ColumnRules, definition_for_column, save_column_definition
from loan_tape.recipe_execution import (
    approve_excel_recipe_step,
    bind_excel_recipe,
    bind_recipe,
    publish_excel_recipe,
    recipe_scope,
    review_excel_recipe,
)
from loan_tape.recipes import Recipe, list_recipes, load_recipe, save_recipe
from loan_tape.transformation_excel import load_transformation, publish_revision
from loan_tape.transformations import apply_transformation, derived_text_values
from loan_tape.workbook_index import ScanCancelled
from loan_tape.workspace_reset import reset_file_session


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return prepare_recipe(tmp_path)


def bind(context, recipe):
    _, source, _, table, store = context
    return bind_excel_recipe(
        source,
        table,
        store,
        recipe,
        profile=recipe.to_dict()["profile"],
        context="Fictional October reporting population",
        reviewer="Recipe reviewer",
        confirmed=True,
    )


def first_step(context, recipe):
    _, source, _, table, store = context
    binding = bind(context, recipe)
    review = review_excel_recipe(source, table, store, recipe, binding)
    revision, path = approve_excel_recipe_step(
        source, table, store, recipe, binding, review, approval(review)
    )
    assert path is None
    return binding, revision


def test_persistence_is_explicit_versioned_and_survives_exit(prepared, tmp_path):
    context, recipe, _, _ = prepared
    original, source, intake, _, _ = context
    before = original.read_bytes()
    assert list_recipes() == ()
    path = save_recipe(recipe)
    assert load_recipe(path) == recipe
    data = recipe.to_dict()
    assert set(data) == {
        "format_version",
        "id",
        "version",
        "name",
        "profile",
        "applicability",
        "schema",
        "steps",
    }
    assert (
        "selected_cells" not in recipe.document_json and "source_sha256" not in recipe.document_json
    )
    assert json.loads(data["steps"][1]["parameters_json"])["rules"][0]["source"] == "Café Holdings"
    with pytest.raises(ValueError, match="already exists"):
        save_recipe(recipe)
    next_version = Recipe(canonical({**data, "version": "1.0.1"}))
    second = save_recipe(next_version)
    assert second != path and len(list_recipes()) == 2
    reset_file_session(intake, "2" * 32)
    assert not source.exists() and path.exists() and second.exists()
    assert load_recipe(path) == recipe and original.read_bytes() == before
    assert not list((tmp_path / ".artifacts/transformations").glob("*"))


def test_step_approvals_stage_then_publish_one_complete_recipe(prepared, tmp_path):
    context, recipe, _, _ = prepared
    original, source, _, table, store = context
    before = source.read_bytes()
    binding, parent = first_step(context, recipe)
    assert derived_text_values(parent) == ((2, 1, "Café Holdings"),)
    assert not list((tmp_path / ".artifacts/transformations").glob("*"))
    review = review_excel_recipe(source, table, store, recipe, binding, parent=parent)
    assert review.preview.to_dict()["reconciliation"]["changed"] == 1
    revision, path = approve_excel_recipe_step(
        source, table, store, recipe, binding, review, approval(review), parent=parent
    )
    assert path.is_file() and len(list(path.parent.glob("*.json"))) == 1
    assert derived_text_values(revision) == ((2, 1, "Café Group"),)
    assert (
        load_transformation(path, source, table, recipe_scope(table), store.catalog()) == revision
    )
    metadata = json.loads(
        revision.to_dict()["steps"][1]["preview"]["operation"]["parameters_json"]
    )["recipe"]
    assert metadata["step"] == 2 and metadata["fingerprint"] == recipe.fingerprint
    assert metadata["binding"]["context"] == "Fictional October reporting population"
    assert metadata["binding_id"] == binding.id
    assert original.read_bytes() == before == source.read_bytes()


def test_loading_and_binding_do_not_run_and_new_source_requires_confirmation(
    prepared, tmp_path, monkeypatch
):
    context, recipe, _, snapshot = prepared
    _, _, _, _, store = context
    with pytest.raises(ValueError, match="Explicitly confirm"):
        bind_recipe(
            recipe,
            snapshot,
            profile=recipe.to_dict()["profile"],
            context="October",
            reviewer="Reviewer",
            confirmed=False,
        )
    old = bind(context, recipe)
    target = tmp_path / "new-source"
    target.mkdir()
    monkeypatch.chdir(target)
    _, source, _, table, new_store = prepare(
        target, ["CafÃ© Holdings", "CafÃ© Holdings", "Café Group", "New", "Next"]
    )
    with pytest.raises(ValueError, match="binding changed"):
        review_excel_recipe(source, table, new_store, recipe, old)
    fresh = bind((None, source, None, table, new_store), recipe)
    assert fresh.id != old.id and fresh.to_dict()["snapshot_id"] != old.to_dict()["snapshot_id"]
    assert not list((target / ".artifacts/transformations").glob("*"))
    review = review_excel_recipe(source, table, new_store, recipe, fresh)
    assert review.preview.to_dict()["reconciliation"]["changed"] == 2
    assert store.catalog() == new_store.catalog()


@pytest.mark.parametrize("changed", ["missing-map", "missing-token", "dictionary", "profile"])
def test_incompatible_template_and_meanings_fail_without_guessing(prepared, changed):
    from loan_tape.column_definitions import remove_column_definition

    context, recipe, _, _ = prepared
    _, source, _, table, store = context
    profile = recipe.to_dict()["profile"]
    if changed == "missing-map":
        remove_column_definition(table, 1)
    elif changed == "missing-token":
        definition = definition_for_column(table, 1)
        save_column_definition(
            table, replace(definition, rules=ColumnRules(missing_tokens=("N/A", "UNKNOWN")))
        )
    elif changed == "dictionary":
        store.deactivate("loan.text")
    else:
        profile = "Different source template"
    with pytest.raises(ValueError):
        bind_excel_recipe(
            source,
            table,
            store,
            recipe,
            profile=profile,
            context="October",
            reviewer="Reviewer",
            confirmed=True,
        )


def test_order_changes_fingerprint_and_later_step_uses_only_chosen_values(prepared):
    context, recipe, _, _ = prepared
    _, source, _, table, store = context
    reversed_recipe = Recipe(
        canonical({**recipe.to_dict(), "steps": list(reversed(recipe.to_dict()["steps"]))})
    )
    assert reversed_recipe.fingerprint != recipe.fingerprint
    binding = bind(context, reversed_recipe)
    first = review_excel_recipe(source, table, store, reversed_recipe, binding)
    assert first.preview.to_dict()["reconciliation"]["changed"] == 0
    parent, path = approve_excel_recipe_step(
        source, table, store, reversed_recipe, binding, first, approval(first, ())
    )
    assert path is None
    second = review_excel_recipe(source, table, store, reversed_recipe, binding, parent=parent)
    revision, _ = approve_excel_recipe_step(
        source, table, store, reversed_recipe, binding, second, approval(second), parent=parent
    )
    assert derived_text_values(revision) == ((2, 1, "Café Holdings"),)
    with pytest.raises(ValueError):
        review_excel_recipe(source, table, store, recipe, binding, parent=parent)


@pytest.mark.parametrize("changed", ["source", "mapping", "recipe", "engine", "cancel"])
def test_later_failure_never_publishes_partial_history(prepared, tmp_path, monkeypatch, changed):
    context, recipe, _, _ = prepared
    _, source, _, table, store = context
    binding, parent = first_step(context, recipe)
    second = review_excel_recipe(source, table, store, recipe, binding, parent=parent)
    cancelled = Event()
    if changed == "source":
        source.write_bytes(source.read_bytes() + b"changed")
    elif changed == "mapping":
        definition = definition_for_column(table, 1)
        save_column_definition(
            table, replace(definition, rules=ColumnRules(missing_tokens=("N/A", "UNKNOWN")))
        )
    elif changed == "recipe":
        recipe = Recipe(canonical({**recipe.to_dict(), "version": "1.0.1"}))
    elif changed == "engine":
        import loan_tape.text_cleanup as engine

        actual = engine.ftfy.fix_and_explain

        def different(text, config):
            return actual("Different" if text == "CafÃ© Holdings" else text, config)

        monkeypatch.setattr(engine.ftfy, "fix_and_explain", different)
    else:
        cancelled.set()
    with pytest.raises((ValueError, ScanCancelled)):
        approve_excel_recipe_step(
            source,
            table,
            store,
            recipe,
            binding,
            second,
            approval(second),
            parent=parent,
            cancelled=cancelled,
        )
    assert not list((tmp_path / ".artifacts/transformations").glob("*"))


@pytest.mark.parametrize("failure", ["cancel", "mapping", "write", "link"])
def test_recipe_publication_guard_after_staging(prepared, tmp_path, monkeypatch, failure):
    import loan_tape.transformation_excel as adapter

    context, recipe, _, _ = prepared
    _, source, _, table, store = context
    binding, parent = first_step(context, recipe)
    second = review_excel_recipe(source, table, store, recipe, binding, parent=parent)
    cancelled = Event()
    original = adapter.os.fsync

    def staged(fd):
        original(fd)
        if failure == "cancel":
            cancelled.set()
        elif failure == "mapping":
            definition = definition_for_column(table, 1)
            save_column_definition(
                table, replace(definition, rules=ColumnRules(missing_tokens=("N/A", "NEW")))
            )
        elif failure == "write":
            raise OSError("Synthetic disk failure")

    def no_link(*_):
        raise OSError("Synthetic link failure")

    monkeypatch.setattr(adapter.os, "fsync", staged)
    if failure == "link":
        monkeypatch.setattr(adapter.os, "link", no_link)
    with pytest.raises((ValueError, OSError, ScanCancelled)):
        approve_excel_recipe_step(
            source,
            table,
            store,
            recipe,
            binding,
            second,
            approval(second),
            parent=parent,
            cancelled=cancelled,
        )
    assert list((tmp_path / ".artifacts/transformations").iterdir()) == []


def test_partial_or_unrelated_history_cannot_publish(prepared):
    context, recipe, unrelated, _ = prepared
    _, source, _, table, store = context
    binding, parent = first_step(context, recipe)
    for revision in (parent, unrelated):
        with pytest.raises(ValueError, match="prior|binding"):
            publish_excel_recipe(source, table, store, recipe, binding, revision)


def test_partial_recipe_cannot_bypass_recipe_publication(prepared):
    context, recipe, _, _ = prepared
    _, source, _, table, store = context
    _, partial = first_step(context, recipe)
    with pytest.raises(ValueError, match="incomplete staged recipe"):
        publish_revision(source, table, recipe_scope(table), store.catalog(), partial)


def test_partial_recipe_archive_cannot_load_without_recipe_context(prepared, tmp_path):
    context, recipe, _, _ = prepared
    _, source, _, table, store = context
    _, partial = first_step(context, recipe)
    path = tmp_path / "partial.json"
    path.write_text(
        canonical({"format_version": 1, "revision_id": partial.id, "revision": partial.to_dict()}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="incomplete staged recipe"):
        load_transformation(path, source, table, recipe_scope(table), store.catalog())


@pytest.mark.parametrize(
    "damage",
    [
        "script",
        "format",
        "engine",
        "path-id",
        "extra",
        "duplicate-fields",
        "no-steps",
        "too-many",
        "typed-settings",
    ],
)
def test_untrusted_recipes_are_data_only_and_strict(prepared, damage):
    _, recipe, _, _ = prepared
    data = recipe.to_dict()
    if damage == "script":
        data["steps"][0]["id"] = "python-script"
    elif damage == "format":
        data["format_version"] = 999
    elif damage == "engine":
        data["steps"][0]["engine_version"] = "99"
    elif damage == "path-id":
        data["id"] = "../escape"
    elif damage == "extra":
        data["execute"] = "arbitrary callback"
    elif damage == "duplicate-fields":
        data["schema"]["fields"].append(data["schema"]["fields"][0])
    elif damage == "no-steps":
        data["steps"] = []
    elif damage == "too-many":
        data["steps"] *= 7
    else:
        data["steps"][0]["parameters_json"] = {"bad": "type"}
    with pytest.raises(ValueError):
        Recipe(canonical(data))


def test_saved_integrity_and_malformed_library_entries_visible(prepared, tmp_path):
    _, recipe, _, _ = prepared
    path = save_recipe(recipe)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["recipe"]["name"] = "Tampered"
    path.write_text(canonical(data), encoding="utf-8")
    with pytest.raises(ValueError, match="fingerprint"):
        load_recipe(path)
    assert "Invalid:" in list_recipes()[0][1]
    path.write_text('{"format_version":1,"format_version":1}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON"):
        load_recipe(path)


def test_cancelled_save_and_collision_keep_existing_bytes(prepared, monkeypatch):
    import loan_tape.recipes as persistence

    _, recipe, _, _ = prepared
    cancelled = Event()
    actual = persistence.os.fsync

    def stop(fd):
        actual(fd)
        cancelled.set()

    monkeypatch.setattr(persistence.os, "fsync", stop)
    with pytest.raises(ScanCancelled):
        save_recipe(recipe, cancelled=cancelled)
    assert list(persistence.recipe_directory().iterdir()) == []


def test_recipe_run_archive_context_must_match_recorded_operations(prepared):
    context, recipe, _, _ = prepared
    _, source, _, table, store = context
    binding, parent = first_step(context, recipe)
    second = review_excel_recipe(source, table, store, recipe, binding, parent=parent)
    revision = apply_transformation(
        second.snapshot, second.preview, approval(second), parent=parent
    )
    _, path = publish_excel_recipe(source, table, store, recipe, binding, revision)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["run_context"]["binding"]["context"] = "Changed context"
    path.write_text(canonical(data), encoding="utf-8")
    with pytest.raises(ValueError, match="binding"):
        load_transformation(path, source, table, recipe_scope(table), store.catalog())


def test_fresh_mapping_can_bind_same_template_at_a_shifted_source_range(prepared, tmp_path):
    from openpyxl import Workbook

    from loan_tape.ranges import parse_range
    from loan_tape.selection import SavedTable, SourceSelection, TableSelections, save_tables

    context, recipe, _, _ = prepared
    _, _, intake, table, store = context
    next_source = tmp_path / "shifted.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "Moved"
    sheet["C4"], sheet["D4"] = "Borrower", "Loan ID"
    sheet["C5"], sheet["D5"] = "CafÃ© Holdings", "000000123"
    sheet["C6"], sheet["D6"] = "Café Group", "000000456"
    book.save(next_source)
    book.close()
    record = intake.save_path(next_source)
    from pathlib import Path

    saved = Path(intake.describe(record)["saved_path"])
    shifted = SavedTable(
        "3" * 32,
        "Shifted source",
        SourceSelection(record["sha256"], "Moved", parse_range("C4:D7"), 4),
    )
    save_tables(TableSelections(shifted.selection.workbook_sha256, (shifted,), shifted.id))
    for column in (1, 2):
        save_column_definition(
            shifted, replace(definition_for_column(table, column), column=column + 2)
        )
    binding = bind((next_source, saved, intake, shifted, store), recipe)
    first = review_excel_recipe(saved, shifted, store, recipe, binding)
    parent, path = approve_excel_recipe_step(
        saved, shifted, store, recipe, binding, first, approval(first, ((5, 3),))
    )
    assert path is None
    second = review_excel_recipe(saved, shifted, store, recipe, binding, parent=parent)
    final, _ = approve_excel_recipe_step(
        saved, shifted, store, recipe, binding, second, approval(second, ((5, 3),)), parent=parent
    )
    assert derived_text_values(final) == ((5, 3, "Café Group"),)


def test_save_race_never_overwrites_existing_version(prepared, monkeypatch):
    import loan_tape.recipes as persistence

    _, recipe, _, _ = prepared
    actual = persistence.os.fsync
    data = recipe.to_dict()
    target = persistence.recipe_directory() / f"{data['id']}-{data['version']}.json"

    def race(fd):
        actual(fd)
        target.write_bytes(b"existing version wins")

    monkeypatch.setattr(persistence.os, "fsync", race)
    with pytest.raises(FileExistsError):
        save_recipe(recipe)
    assert target.read_bytes() == b"existing version wins"
    assert not list(target.parent.glob("*.tmp"))
