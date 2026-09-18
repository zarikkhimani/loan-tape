"""Full-group XML field reader for the shared inspection/check pipeline."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from collections.abc import Callable
from pathlib import Path
from threading import Event

from loan_tape.column_profile import (
    ColumnAccumulator,
    ColumnExample,
    ColumnProfile,
    _check_cancelled,
    limit_xml_storage,
)
from loan_tape.inspection import InspectionError, PreviewCell
from loan_tape.session import AnalysisSession
from loan_tape.xml_preview import _parse, _Target
from loan_tape.xml_selection import SavedXmlTable

XML_KINDS = ("Absent", "Empty element", "Explicit nil", "Empty text", "Text")


def inspect_xml_column(
    path: Path,
    table: SavedXmlTable,
    column: int,
    session: AnalysisSession,
    *,
    cancelled: Event | None = None,
    progress: Callable[[str], None] = lambda message: None,
    on_cell: Callable[[ColumnExample], None] | None = None,
) -> ColumnProfile:
    if path.suffix.lower() != ".xml":
        raise InspectionError("An XML data set requires its XML source file.")
    if type(column) is not int or not 1 <= column <= table.field_count:
        raise InspectionError("Choose a field inside the saved XML data set.")
    _check_cancelled(cancelled)
    progress("Checking the complete XML group and source identity…")
    discovery = _Target(cancelled, table.group_path, collect_preview=False)
    identity = _parse(path, discovery)
    if identity != table.source_sha256:
        raise InspectionError(
            "The saved XML source changed. Add it again before inspecting columns."
        )
    if discovery.problem:
        raise InspectionError(discovery.problem)
    candidates = [key for key, value in discovery.groups.items() if value.repeated]
    if not candidates:
        candidates = [next(iter(discovery.groups))]
    if (
        table.group_path not in candidates
        or discovery.records != table.record_count
        or len(discovery.fields) != table.field_count
    ):
        raise InspectionError(
            "The saved XML group no longer matches the analysis scope. Reopen its preview."
        )
    field = tuple(discovery.fields)[column - 1]
    work = Path.cwd() / ".artifacts" / "column-inspection"
    work.mkdir(parents=True, exist_ok=True)
    rows_read = 0
    with tempfile.TemporaryDirectory(prefix="xml-column-", dir=work) as temporary:
        db = sqlite3.connect(Path(temporary) / "counts.sqlite")
        try:
            limit_xml_storage(db)
            accumulator = ColumnAccumulator(db, XML_KINDS)

            def visit(row: int, cell: PreviewCell) -> None:
                nonlocal rows_read
                _check_cancelled(cancelled)
                if row != rows_read + 1:
                    raise InspectionError("XML column records were not delivered in source order.")
                kind = (
                    cell.presence
                    if cell.presence != "Present"
                    else ("Text" if cell.text else "Empty text")
                )
                if kind not in XML_KINDS or cell.source_path is None:
                    raise InspectionError("XML field evidence is incomplete.")
                assert kind is not None
                example = ColumnExample(
                    row,
                    kind,
                    cell.text,
                    "General",
                    source_path=cell.source_path,
                    presence=cell.presence,
                )
                accumulator.add(example, json.dumps([kind, cell.text], ensure_ascii=False))
                if on_cell is not None:
                    on_cell(example)
                rows_read += 1
                if row % 10000 == 0:
                    progress(f"Read {row:,} of {table.record_count:,} XML records…")

            progress(f"Reading all {table.record_count:,} records in XML field {column}…")
            target = _Target(
                cancelled,
                table.group_path,
                collect_preview=False,
                stream_field=field,
                on_record=visit,
            )
            if _parse(path, target) != identity:
                raise InspectionError(
                    "The XML source changed during column inspection. Add it again."
                )
            if target.problem:
                raise InspectionError(target.problem)
            if rows_read != table.record_count or tuple(target.fields) != tuple(discovery.fields):
                raise InspectionError("XML column coverage does not match the saved group.")
            _check_cancelled(cancelled)
            distinct, repeated, extra, repeated_examples = accumulator.finish()
        except sqlite3.Error as error:
            raise InspectionError(
                f"XML inspection storage failed; no complete result (512 MiB limit per database). {error}"
            ) from error
        finally:
            db.close()
    _check_cancelled(cancelled)
    return ColumnProfile(
        table,
        column,
        session,
        field,
        1,
        table.record_count,
        tuple(accumulator.counts.items()),
        0,
        accumulator.whitespace,
        distinct,
        repeated,
        extra,
        tuple(accumulator.examples),
        repeated_examples,
        accumulator.text_zeroes,
    )
