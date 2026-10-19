"""Fresh source binding, stepwise review, and all-or-nothing recipe publication."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any

from loan_tape._date_json import canonical
from loan_tape.column_definitions import DefinitionScope, definitions_for_table
from loan_tape.pack_format import object_keys, parse_json
from loan_tape.packs import PackStore
from loan_tape.recipe_context import validate_binding
from loan_tape.recipes import Recipe, operation_settings, relocate_operation, snapshot_schema
from loan_tape.selection import SavedTable, load_tables
from loan_tape.text_cleanup import TextCleanupReview, preview_text_cleanup
from loan_tape.text_rule_types import ExactRulesSettings
from loan_tape.text_rules import preview_exact_rules
from loan_tape.transformation_excel import publish_revision, read_transformation_snapshot
from loan_tape.transformations import (
    CellProposal,
    TransformationApproval,
    TransformationOperation,
    TransformationPreview,
    TransformationRevision,
    TransformationSnapshot,
    apply_transformation,
    preview_transformation,
    replay_revision,
)
from loan_tape.workbook_index import check_cancelled


@dataclass(frozen=True)
class RecipeBinding:
    document_json: str

    def __post_init__(self) -> None:
        if len(self.document_json.encode("utf-8")) > 4096:
            raise ValueError("Recipe binding exceeds its 4 KiB limit.")
        object.__setattr__(
            self,
            "document_json",
            canonical(validate_binding(parse_json(self.document_json, "recipe binding"))),
        )

    def to_dict(self) -> dict[str, Any]:
        return parse_json(self.document_json, "recipe binding")  # type: ignore[no-any-return]

    @property
    def id(self) -> str:
        return hashlib.sha256(self.document_json.encode("utf-8")).hexdigest()


def bind_recipe(
    recipe: Recipe,
    snapshot: TransformationSnapshot,
    *,
    profile: str,
    context: str,
    reviewer: str,
    confirmed: bool,
) -> RecipeBinding:
    if confirmed is not True:
        raise ValueError("Explicitly confirm the template, mappings and reporting context first.")
    if (
        profile != recipe.to_dict()["profile"]
        or snapshot_schema(snapshot) != recipe.to_dict()["schema"]
    ):
        raise ValueError(
            "Recipe template, mapped schema or dictionary meaning differs. Review and map this source explicitly; do not guess a binding."
        )
    return RecipeBinding(
        canonical(
            {
                "format_version": 1,
                "recipe_fingerprint": recipe.fingerprint,
                "snapshot_id": snapshot.id,
                "profile": profile,
                "context": context,
                "reviewer": reviewer,
                "confirmed_at_utc": datetime.now(UTC).isoformat(),
            }
        )
    )


def check_binding(recipe: Recipe, binding: RecipeBinding, snapshot: TransformationSnapshot) -> None:
    data = binding.to_dict()
    if (
        data["recipe_fingerprint"] != recipe.fingerprint
        or data["snapshot_id"] != snapshot.id
        or data["profile"] != recipe.to_dict()["profile"]
        or snapshot_schema(snapshot) != recipe.to_dict()["schema"]
    ):
        raise ValueError(
            "Recipe, source, mappings or context binding changed. Discard this run and bind again."
        )


def bound_operation(
    recipe: Recipe, binding: RecipeBinding, snapshot: TransformationSnapshot, index: int
) -> TransformationOperation:
    check_binding(recipe, binding, snapshot)
    if type(index) is not int or not 0 <= index < len(recipe.steps):
        raise ValueError("Recipe step is outside its ordered plan.")
    operation = recipe.steps[index]
    relative, _ = operation_settings(operation)
    column = snapshot.to_dict()["dataset"]["selection"]["area"]["min_column"] + relative - 1
    operation = relocate_operation(operation, column)
    parameters = parse_json(operation.parameters_json, "operation")
    data = recipe.to_dict()
    parameters["recipe"] = {
        "id": data["id"],
        "version": data["version"],
        "fingerprint": recipe.fingerprint,
        "binding_id": binding.id,
        "binding": binding.to_dict(),
        "step": index + 1,
        "total": len(recipe.steps),
    }
    return replace(operation, parameters_json=canonical(parameters))


def _check_history(
    snapshot: TransformationSnapshot,
    recipe: Recipe,
    binding: RecipeBinding,
    parent: TransformationRevision | None,
    count: int,
    cancelled: Event | None,
) -> None:
    check_binding(recipe, binding, snapshot)
    steps = []
    if parent is not None:
        parent = replay_revision(snapshot, parent.document_json, cancelled=cancelled)
        steps = parent.to_dict()["steps"]
    if len(steps) != count:
        raise ValueError("Recipe requires the complete, ordered prior approvals from this run.")
    for index, step in enumerate(steps):
        if TransformationOperation(**step["preview"]["operation"]) != bound_operation(
            recipe, binding, snapshot, index
        ):
            raise ValueError("Recipe prior steps or binding do not match the current run.")


def preview_recipe_step(
    snapshot: TransformationSnapshot,
    recipe: Recipe,
    binding: RecipeBinding,
    *,
    parent: TransformationRevision | None = None,
    cancelled: Event | None = None,
) -> TransformationPreview:
    check_cancelled(cancelled)
    index = len(parent.to_dict()["steps"]) if parent else 0
    _check_history(snapshot, recipe, binding, parent, index, cancelled)
    operation = bound_operation(recipe, binding, snapshot, index)
    column, settings = operation_settings(operation)
    plain = (
        preview_exact_rules(snapshot, column, settings, parent=parent, cancelled=cancelled)
        if isinstance(settings, ExactRulesSettings)
        else preview_text_cleanup(snapshot, column, settings, parent=parent, cancelled=cancelled)
    )
    return preview_transformation(
        snapshot,
        operation,
        tuple(CellProposal(**p) for p in plain.to_dict()["proposals"]),
        parent=parent,
        cancelled=cancelled,
    )


def recipe_scope(table: SavedTable) -> DefinitionScope:
    return DefinitionScope(table.id, table.name, table.selection, definitions_for_table(table))


def bind_excel_recipe(
    source: Path,
    table: SavedTable,
    store: PackStore,
    recipe: Recipe,
    *,
    profile: str,
    context: str,
    reviewer: str,
    confirmed: bool,
    cancelled: Event | None = None,
) -> RecipeBinding:
    snapshot = read_transformation_snapshot(
        source, table, recipe_scope(table), store.catalog(), cancelled=cancelled
    )
    return bind_recipe(
        recipe, snapshot, profile=profile, context=context, reviewer=reviewer, confirmed=confirmed
    )


def review_excel_recipe(
    source: Path,
    table: SavedTable,
    store: PackStore,
    recipe: Recipe,
    binding: RecipeBinding,
    *,
    parent: TransformationRevision | None = None,
    cancelled: Event | None = None,
) -> TextCleanupReview:
    scope = recipe_scope(table)
    snapshot = read_transformation_snapshot(
        source, table, scope, store.catalog(), cancelled=cancelled
    )
    preview = preview_recipe_step(snapshot, recipe, binding, parent=parent, cancelled=cancelled)
    return TextCleanupReview(snapshot, preview, scope)


def approve_excel_recipe_step(
    source: Path,
    table: SavedTable,
    store: PackStore,
    recipe: Recipe,
    binding: RecipeBinding,
    review: TextCleanupReview,
    approval: TransformationApproval,
    *,
    parent: TransformationRevision | None = None,
    cancelled: Event | None = None,
) -> tuple[TransformationRevision, Path | None]:
    current = review_excel_recipe(
        source, table, store, recipe, binding, parent=parent, cancelled=cancelled
    )
    if current != review:
        raise ValueError("Recipe preview changed. Discard this run and review again.")
    revision = apply_transformation(
        current.snapshot, current.preview, approval, parent=parent, cancelled=cancelled
    )
    if len(revision.to_dict()["steps"]) < len(recipe.steps):
        return revision, None
    return publish_excel_recipe(
        source, table, store, recipe, binding, revision, cancelled=cancelled
    )


def publish_excel_recipe(
    source: Path,
    table: SavedTable,
    store: PackStore,
    recipe: Recipe,
    binding: RecipeBinding,
    revision: TransformationRevision,
    *,
    cancelled: Event | None = None,
) -> tuple[TransformationRevision, Path]:
    scope, catalog = recipe_scope(table), store.catalog()
    snapshot = read_transformation_snapshot(source, table, scope, catalog, cancelled=cancelled)
    _check_history(snapshot, recipe, binding, revision, len(recipe.steps), cancelled)
    # Re-execute every supported engine against each explicitly approved parent.
    parent = None
    for step in revision.to_dict()["steps"]:
        check_cancelled(cancelled)
        preview = preview_recipe_step(snapshot, recipe, binding, parent=parent, cancelled=cancelled)
        if preview.to_dict() != step["preview"]:
            raise ValueError("Recipe engine output changed; no result was published.")
        data = step["approval"]
        approval = TransformationApproval(
            data["preview_id"],
            tuple(tuple(v) for v in data["selected_cells"]),
            data["reviewer"],
            data["justification"],
            data["decided_at_utc"],
        )
        parent = apply_transformation(
            snapshot, preview, approval, parent=parent, cancelled=cancelled
        )
    if parent != revision:
        raise ValueError("Recipe does not match complete replay; no result was published.")

    def guard() -> None:
        check_cancelled(cancelled)
        if (
            table not in load_tables(table.selection.workbook_sha256).tables
            or recipe_scope(table) != scope
            or store.catalog() != catalog
        ):
            raise ValueError("Recipe data set, mappings or dictionary changed before publication.")

    guard()
    return publish_revision(
        source,
        table,
        scope,
        catalog,
        revision,
        cancelled=cancelled,
        before_publish=guard,
        run_context={"recipe": recipe.to_dict(), "binding": binding.to_dict()},
    )


def validate_recipe_archive(
    value: Any,
    snapshot: TransformationSnapshot,
    revision: TransformationRevision,
    *,
    cancelled: Event | None = None,
) -> None:
    data = object_keys(value, {"recipe", "binding"}, set(), "recipe run context")
    recipe, binding = Recipe(canonical(data["recipe"])), RecipeBinding(canonical(data["binding"]))
    _check_history(snapshot, recipe, binding, revision, len(recipe.steps), cancelled)
