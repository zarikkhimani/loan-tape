"""Build a fictional two-step reviewed history without publishing training results."""

from datetime import UTC, datetime

from text_cleanup_support import prepare

from loan_tape.recipes import recipe_from_revision
from loan_tape.text_cleanup import TextCleanupSettings, review_excel_text
from loan_tape.text_rule_types import ExactRule, ExactRulesSettings
from loan_tape.transformations import TransformationApproval, apply_transformation


def approval(review, cells=((2, 1),)):
    return TransformationApproval(
        review.preview.id,
        cells,
        "Synthetic reviewer",
        "Reviewed fictional source cells.",
        datetime.now(UTC).isoformat(),
    )


def prepare_recipe(work):
    context = prepare(work, ["CafÃ© Holdings", "Café Group", "CafÃ© Holdings", " Acme "])
    _, source, _, table, store = context
    first = review_excel_text(source, table, 1, TextCleanupSettings(), store)
    parent = apply_transformation(first.snapshot, first.preview, approval(first))
    settings = ExactRulesSettings((ExactRule("Café Holdings", "Café Group"),))
    second = review_excel_text(source, table, 1, settings, store, parent=parent)
    revision = apply_transformation(
        second.snapshot, second.preview, approval(second), parent=parent
    )
    recipe = recipe_from_revision(
        revision,
        name="Fictional names",
        profile="Fictional loan template",
        applicability="Borrower names from the fictional template. Confirm reporting context on every run.",
    )
    return context, recipe, revision, first.snapshot
