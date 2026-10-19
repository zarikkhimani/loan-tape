"""Run actual text repair, spelling, exact application and replay from an installed wheel."""

import os
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from openpyxl import Workbook  # type: ignore[import-untyped]

from loan_tape.column_definitions import ColumnDefinition, save_column_definition, snapshot_field
from loan_tape.intake import IntakeStore
from loan_tape.packs import PackStore
from loan_tape.ranges import parse_range
from loan_tape.recipe_execution import (
    approve_excel_recipe_step,
    bind_excel_recipe,
    review_excel_recipe,
)
from loan_tape.recipes import load_recipe, recipe_from_revision, save_recipe
from loan_tape.selection import SavedTable, SourceSelection, TableSelections, save_tables
from loan_tape.text_cleanup import (
    TextCleanupSettings,
    apply_excel_text,
    review_excel_text,
    suggest_excel_text,
)
from loan_tape.text_export_payload import build_text_export
from loan_tape.text_rule_types import ExactRulesSettings
from loan_tape.text_rules import SpellingSettings
from loan_tape.transformation_excel import load_transformation
from loan_tape.transformations import TransformationApproval, derived_text_values
from loan_tape.workspace_reset import reset_file_session


def main() -> None:
    packs = Path(__file__).resolve().parents[1] / "packs"
    previous = Path.cwd()
    with TemporaryDirectory(prefix="text-cleanup-smoke-", dir=previous) as temporary:
        root = Path(temporary)
        os.chdir(root)
        try:
            source = root / "fictional.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.title = "Loans"
            sheet.append(["Borrower"])
            sheet.append(["CafÃ© Holdings"])
            sheet.append(["Café Group"])
            sheet.append(["e\u0301"])
            book.save(source)
            book.close()
            before = source.read_bytes()
            intake = IntakeStore(root / "inputs")
            record = intake.save_path(source)
            saved = Path(str(intake.describe(record)["saved_path"]))
            table = SavedTable(
                "1" * 32,
                "Fictional loans",
                SourceSelection(str(record["sha256"]), "Loans", parse_range("A1:A5"), 1),
            )
            save_tables(TableSelections(table.selection.workbook_sha256, (table,), table.id))
            store = PackStore(packs, root / ".artifacts/packs")
            store.activate("loan.text")
            catalog = store.catalog()
            save_column_definition(
                table,
                ColumnDefinition(
                    1,
                    "Borrower",
                    snapshot_field(catalog, catalog.get_field("loan.text:borrower_name")),
                ),
            )
            settings = TextCleanupSettings()
            review = review_excel_text(saved, table, 1, settings, store)
            assert review.preview.to_dict()["reconciliation"]["changed"] == 1
            approval = TransformationApproval(
                review.preview.id,
                ((2, 1),),
                "Smoke test",
                "Fictional source reviewed.",
                datetime.now(UTC).isoformat(),
            )
            revision, path = apply_excel_text(saved, table, 1, settings, store, review, approval)
            assert derived_text_values(revision) == ((2, 1, "Café Holdings"),)
            assert load_transformation(path, saved, table, review.scope, catalog) == revision
            suggestions = suggest_excel_text(
                saved, table, 1, "Café Holdings", SpellingSettings(0), store, parent=revision
            )
            choice = next(
                i for i, item in enumerate(suggestions.candidates) if item.text == "Café Group"
            )
            exact = ExactRulesSettings((suggestions.rule(choice),))
            rule_review = review_excel_text(saved, table, 1, exact, store, parent=revision)
            rule_approval = TransformationApproval(
                rule_review.preview.id,
                ((2, 1),),
                "Smoke test",
                "Fictional spelling replacement reviewed.",
                datetime.now(UTC).isoformat(),
            )
            child, child_path = apply_excel_text(
                saved, table, 1, exact, store, rule_review, rule_approval, parent=revision
            )
            assert derived_text_values(child) == ((2, 1, "Café Group"),)
            assert load_transformation(child_path, saved, table, review.scope, catalog) == child
            next_review = review_excel_text(
                saved, table, 1, TextCleanupSettings(True, "NFC"), store, parent=child
            )
            assert next_review.preview.to_dict()["reconciliation"]["changed"] == 1
            assert source.read_bytes() == before == saved.read_bytes()
            recipe = recipe_from_revision(
                child,
                name="Fictional names",
                profile="Fictional template",
                applicability="Borrower-name cleanup; review reporting context on each run.",
            )
            recipe_path = save_recipe(recipe)
            reset_file_session(intake, "2" * 32)
            assert not saved.exists() and not path.exists() and not child_path.exists()
            assert source.read_bytes() == before
            assert load_recipe(recipe_path) == recipe
            next_source = root / "next-fictional.xlsx"
            next_book = Workbook()
            next_sheet = next_book.active
            next_sheet.title = "Loans"
            for value in ("Borrower", "CafÃ© Holdings", "Café Group", "New Name"):
                next_sheet.append([value])
            next_book.save(next_source)
            next_book.close()
            next_before = next_source.read_bytes()
            next_record = intake.save_path(next_source)
            next_saved = Path(str(intake.describe(next_record)["saved_path"]))
            next_table = SavedTable(
                "3" * 32,
                "Next fictional loans",
                SourceSelection(str(next_record["sha256"]), "Loans", parse_range("A1:A4"), 1),
            )
            save_tables(
                TableSelections(next_table.selection.workbook_sha256, (next_table,), next_table.id)
            )
            save_column_definition(
                next_table,
                ColumnDefinition(
                    1,
                    "Borrower",
                    snapshot_field(catalog, catalog.get_field("loan.text:borrower_name")),
                ),
            )
            binding = bind_excel_recipe(
                next_saved,
                next_table,
                store,
                load_recipe(recipe_path),
                profile="Fictional template",
                context="Next fictional reporting population",
                reviewer="Smoke reviewer",
                confirmed=True,
            )
            staged = None
            for index in range(2):
                recipe_review = review_excel_recipe(
                    next_saved, next_table, store, recipe, binding, parent=staged
                )
                selected = TransformationApproval(
                    recipe_review.preview.id,
                    ((2, 1),),
                    "Smoke reviewer",
                    "Reviewed this step on the new source.",
                    datetime.now(UTC).isoformat(),
                )
                staged, published = approve_excel_recipe_step(
                    next_saved,
                    next_table,
                    store,
                    recipe,
                    binding,
                    recipe_review,
                    selected,
                    parent=staged,
                )
                if index == 0:
                    assert published is None and not list(
                        (root / ".artifacts/transformations").glob("*")
                    )
            assert staged is not None and published is not None and published.is_file()
            assert derived_text_values(staged) == ((2, 1, "Café Group"),)
            assert (
                load_transformation(published, next_saved, next_table, recipe_review.scope, catalog)
                == staged
            )
            assert next_saved.read_bytes() == next_before == next_source.read_bytes()
            payload = build_text_export(
                next_saved, next_table, recipe_review.scope, catalog, staged
            )
            assert payload["sheets"][0]["rows"][1] == ["Café Group"]
            assert payload["sheets"][2]["rows"][1][11] == recipe.to_dict()["id"]
            assert payload["revision_id"] == staged.id
            reset_file_session(intake, "4" * 32)
            assert not published.exists() and not next_saved.exists()
            assert load_recipe(recipe_path) == recipe and next_source.read_bytes() == next_before
        finally:
            os.chdir(previous)
    print(
        "Installed-wheel text engines, exact rules, recipes, fresh binding, staged application, replay, export payload and cleanup passed."
    )


if __name__ == "__main__":
    main()
