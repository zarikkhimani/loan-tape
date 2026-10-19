"""Publish a complete reviewed text result to a separate, validated Excel workbook."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from threading import Event
from uuid import uuid4

from loan_tape.date_runs import SavedDateRun, load_date_run
from loan_tape.inspection import InspectionError
from loan_tape.packs import PackStore
from loan_tape.recipe_execution import recipe_scope
from loan_tape.selection import SavedTable, load_tables
from loan_tape.text_export_excel import validate_output, write_excel
from loan_tape.text_export_payload import build_text_export
from loan_tape.transformations import TransformationRevision
from loan_tape.workbook_index import _digest, check_cancelled


@dataclass(frozen=True)
class TextExport:
    path: Path
    sha256: str
    writer: str
    writer_version: str
    revision_id: str
    date_run_id: str | None
    row_counts: tuple[tuple[str, int], ...]


def export_text_revision(
    source: Path,
    table: SavedTable,
    store: PackStore,
    revision: TransformationRevision,
    target: Path,
    *,
    date_run: SavedDateRun | None = None,
    cancelled: Event | None = None,
    timeout: float = 120,
) -> TextExport:
    """Publish only this approved revision; unapproved previews/drafts cannot be exported."""
    check_cancelled(cancelled)
    if sys.platform != "win32":
        raise InspectionError("Text export requires Windows and desktop Microsoft Excel.")
    source, target = source.resolve(), target.resolve()
    if target.suffix.lower() != ".xlsx":
        raise ValueError("Choose a new .xlsx output file.")
    if target.exists() or target == source:
        raise FileExistsError("Existing files and original sources are not overwritten.")
    scope, catalog = recipe_scope(table), store.catalog()

    def guard() -> None:
        check_cancelled(cancelled)
        if (
            table not in load_tables(table.selection.workbook_sha256).tables
            or recipe_scope(table) != scope
            or store.catalog() != catalog
            or _digest(source, cancelled) != table.selection.workbook_sha256
        ):
            raise ValueError(
                "Source, saved data set, mappings or dictionary changed during export."
            )
        if date_run is not None and load_date_run(date_run.path, cancelled=cancelled) != date_run:
            raise ValueError("The selected date run changed during export.")

    guard()
    expected_writer = version("xlwings")
    payload = build_text_export(
        source,
        table,
        scope,
        catalog,
        revision,
        date_run=date_run,
        writer_version=expected_writer,
        cancelled=cancelled,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.stem}.{uuid4().hex}.tmp.xlsx")
    linked = False
    try:
        writer = write_excel(payload, staging, cancelled=cancelled, timeout=timeout)
        if writer != expected_writer:
            raise InspectionError("Excel writer version differs from the recorded export version.")
        counts = validate_output(staging, payload, cancelled=cancelled)
        guard()
        os.link(staging, target)
        linked = True
        check_cancelled(cancelled)
        if validate_output(target, payload, cancelled=cancelled) != counts:
            raise InspectionError("Published output differs from the validated staging workbook.")
        guard()
        digest = _digest(target, cancelled)
    except BaseException:
        # A competing file created after preflight belongs to its creator, never to us.
        if linked and target.exists() and staging.exists() and os.path.samefile(target, staging):
            target.unlink()
        raise
    finally:
        staging.unlink(missing_ok=True)
    return TextExport(
        target, digest, "xlwings", writer, revision.id, date_run.id if date_run else None, counts
    )
