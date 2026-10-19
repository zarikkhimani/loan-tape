"""Complete Excel evidence and atomic session-only transformation revision storage."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from threading import Event
from uuid import uuid4

from loan_tape._date_json import canonical
from loan_tape.column_definitions import DefinitionScope, snapshot_field
from loan_tape.date_parser import DateEvidence
from loan_tape.date_reader import read_excel_date_columns
from loan_tape.pack_format import object_keys, parse_json, read_text
from loan_tape.packs import Catalog
from loan_tape.ranges import CellRange
from loan_tape.recipe_context import validate_complete_recipe_history
from loan_tape.selection import SavedTable, SourceSelection
from loan_tape.transformations import (
    MAX_CELLS,
    MAX_RESULT_BYTES,
    TransformationApproval,
    TransformationPreview,
    TransformationRevision,
    TransformationSnapshot,
    apply_transformation,
    build_snapshot,
    replay_revision,
)
from loan_tape.workbook_index import _digest, check_cancelled


def read_transformation_snapshot(
    source: Path,
    table: SavedTable,
    scope: DefinitionScope,
    catalog: Catalog,
    *,
    cancelled: Event | None = None,
) -> TransformationSnapshot:
    """Read complete mapped columns; verify exact headers and active dictionary meanings."""
    check_cancelled(cancelled)
    if not scope.matches(table) or scope.table_name != table.name or not scope.definitions:
        raise ValueError("Choose the current saved data set and explicit column definitions.")
    selection = table.selection
    first = selection.header_row + 1 if selection.header_row is not None else selection.area.min_row
    if (selection.area.max_row - first + 1) * len(scope.definitions) > MAX_CELLS:
        raise ValueError("Transformation selection exceeds the mapped-cell limit.")
    for definition in scope.definitions:
        selected = catalog.get_field(definition.field.id)
        active = snapshot_field(catalog, selected)
        if active != definition.field:
            raise ValueError("Mapped dictionary meaning changed; review the mapping again.")
        if set(selected.field.missing_codes) - set(definition.rules.missing_tokens):
            raise ValueError("Dictionary missing codes require explicit mapped missing tokens.")
    headers: tuple[DateEvidence, ...] = ()
    if selection.header_row is not None:
        row = selection.header_row
        header_selection = SourceSelection(
            selection.workbook_sha256,
            selection.sheet,
            CellRange(row, selection.area.min_column, row, selection.area.max_column),
        )
        header_columns = read_excel_date_columns(
            source,
            header_selection,
            tuple(range(selection.area.min_column, selection.area.max_column + 1)),
            cancelled=cancelled,
            max_rows=1,
        )
        headers = tuple(column.cells[0] for column in header_columns)
    columns = read_excel_date_columns(
        source,
        selection,
        tuple(sorted(item.column for item in scope.definitions)),
        cancelled=cancelled,
        max_rows=MAX_CELLS,
    )
    return build_snapshot(table, scope, columns, headers, cancelled=cancelled)


def publish_transformation(
    source: Path,
    table: SavedTable,
    scope: DefinitionScope,
    catalog: Catalog,
    preview: TransformationPreview,
    approval: TransformationApproval,
    *,
    parent: TransformationRevision | None = None,
    artifact_root: Path | None = None,
    cancelled: Event | None = None,
    before_publish: Callable[[], None] | None = None,
) -> tuple[TransformationRevision, Path]:
    """Recheck current inputs, stage a complete revision and publish without replacement.

    The caller supplies current table/mapping/catalog state, never cached UI settings.
    Workers must finish before reset_file_session removes this source-bound evidence.
    """
    snapshot = read_transformation_snapshot(source, table, scope, catalog, cancelled=cancelled)
    revision = apply_transformation(snapshot, preview, approval, parent=parent, cancelled=cancelled)
    return publish_revision(
        source,
        table,
        scope,
        catalog,
        revision,
        artifact_root=artifact_root,
        cancelled=cancelled,
        before_publish=before_publish,
    )


def publish_revision(
    source: Path,
    table: SavedTable,
    scope: DefinitionScope,
    catalog: Catalog,
    revision: TransformationRevision,
    *,
    artifact_root: Path | None = None,
    cancelled: Event | None = None,
    before_publish: Callable[[], None] | None = None,
    run_context: dict[str, object] | None = None,
) -> tuple[TransformationRevision, Path]:
    """Recheck and publish one complete history; never expose intermediate recipe steps."""
    snapshot = read_transformation_snapshot(source, table, scope, catalog, cancelled=cancelled)
    revision = replay_revision(snapshot, revision.document_json, cancelled=cancelled)
    validate_complete_recipe_history(revision.to_dict()["steps"], snapshot.id)
    if run_context is not None:
        from loan_tape.recipe_execution import validate_recipe_archive

        validate_recipe_archive(run_context, snapshot, revision, cancelled=cancelled)
    root = artifact_root if artifact_root is not None else Path.cwd() / ".artifacts"
    directory = root / "transformations"
    directory.mkdir(parents=True, exist_ok=True)
    run_id = uuid4().hex
    # The fixed source-hash prefix also lets session cleanup identify interrupted staging.
    basename = table.selection.workbook_sha256 + "-" + run_id
    target, temporary = directory / (basename + ".json"), directory / (basename + ".tmp")
    encoded = canonical(
        {
            "format_version": 1,
            "revision_id": revision.id,
            "revision": revision.to_dict(),
            **({"run_context": run_context} if run_context is not None else {}),
        }
    ).encode("utf-8")
    if len(encoded) > MAX_RESULT_BYTES:
        raise ValueError("Transformation evidence exceeds the serialized result limit.")
    owns_staging = False
    try:
        with temporary.open("xb") as stream:
            owns_staging = True
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if _digest(source, cancelled) != table.selection.workbook_sha256:
            raise ValueError("Source changed before publication; no revision was published.")
        if before_publish is not None:
            before_publish()
        check_cancelled(cancelled)
        os.link(temporary, target)
    finally:
        if owns_staging:
            temporary.unlink(missing_ok=True)
    return revision, target


def load_transformation(
    path: Path,
    source: Path,
    table: SavedTable,
    scope: DefinitionScope,
    catalog: Catalog,
    *,
    cancelled: Event | None = None,
) -> TransformationRevision:
    """Re-read original evidence and replay decisions before accepting a saved revision."""
    check_cancelled(cancelled)
    envelope = object_keys(
        parse_json(read_text(path, limit=MAX_RESULT_BYTES), "transformation run"),
        {"format_version", "revision_id", "revision"},
        {"run_context"},
        "transformation run",
    )
    if type(envelope["format_version"]) is not int or envelope["format_version"] != 1:
        raise ValueError("Unsupported transformation run format.")
    snapshot = read_transformation_snapshot(source, table, scope, catalog, cancelled=cancelled)
    revision = replay_revision(snapshot, canonical(envelope["revision"]), cancelled=cancelled)
    if revision.id != envelope["revision_id"]:
        raise ValueError("Transformation revision integrity check failed.")
    validate_complete_recipe_history(revision.to_dict()["steps"], snapshot.id)
    if "run_context" in envelope:
        from loan_tape.recipe_execution import validate_recipe_archive

        validate_recipe_archive(envelope["run_context"], snapshot, revision, cancelled=cancelled)
    return revision
