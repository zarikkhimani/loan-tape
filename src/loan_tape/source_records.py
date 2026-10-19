"""Complete bounded CSV/XML populations with native, source-bound coordinates."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any

from loan_tape._date_json import canonical
from loan_tape.inspection import CancellableReader, InspectionError, PreviewCell
from loan_tape.intake import MAX_FILE_BYTES
from loan_tape.transformations import MAX_CELLS, MAX_RESULT_BYTES, _retain
from loan_tape.workbook_index import _digest, check_cancelled
from loan_tape.xml_preview import _parse, _Target
from loan_tape.xml_selection import SavedXmlTable, load_xml_selections

CSV_ENCODINGS = ("utf-8-sig", "cp1252", "utf-16")
CSV_DELIMITERS = (",", ";", "\t", "|")
MAX_FIELDS = 2048


@dataclass(frozen=True)
class SourceRecords:
    """Only complete reads are returned; originals remain the lexical byte evidence."""

    metadata_json: str
    rows: tuple[tuple[dict[str, Any], ...], ...]


def _identity(path: Path, cancelled: Event | None) -> str:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise InspectionError("Source exceeds the 100 MiB intake limit.")
    return _digest(path, cancelled)


def _state(raw: str | None, presence: str) -> str:
    if presence != "Present":
        return {"Absent": "absent", "Empty element": "empty_element", "Explicit nil": "nil"}[
            presence
        ]
    if raw == "":
        return "empty_text"
    if raw is not None and raw.isspace():
        return "whitespace_text"
    return "text"


def _cell(raw: str | None, presence: str, source: dict[str, Any]) -> dict[str, Any]:
    return {
        "state": _state(raw, presence),
        "evidence": _retain({"raw": raw, "presence": presence, "source": source}),
    }


def read_csv_records(
    path: Path,
    encoding: str,
    delimiter: str,
    header: bool,
    *,
    cancelled: Event | None = None,
) -> SourceRecords:
    """Whole-file scope; CSV record numbers differ from physical lines for quoted newlines."""
    if path.suffix.lower() != ".csv":
        raise InspectionError("CSV scope requires a CSV source.")
    if encoding not in CSV_ENCODINGS or delimiter not in CSV_DELIMITERS or type(header) is not bool:
        raise ValueError("Choose an explicit encoding, separator and header convention.")
    identity = _identity(path, cancelled)
    records: list[tuple[tuple[str, ...], int, int]] = []
    width = size = 0
    try:
        with io.TextIOWrapper(
            CancellableReader(path, cancelled), encoding=encoding, newline=""
        ) as stream:
            reader = csv.reader(stream, delimiter=delimiter, strict=True)
            previous_line = 0
            for values in reader:
                check_cancelled(cancelled)
                width = max(width, len(values))
                size += sum(len(value.encode("utf-8")) for value in values)
                if width > MAX_FIELDS or (len(records) + 1) * max(1, width) > MAX_CELLS:
                    raise InspectionError(
                        "CSV exceeds the 200,000 complete-cell or 2,048-field limit."
                    )
                if size > MAX_RESULT_BYTES:
                    raise InspectionError("CSV decoded values exceed the evidence memory limit.")
                records.append((tuple(values), previous_line + 1, reader.line_num))
                previous_line = reader.line_num
    except (csv.Error, UnicodeError) as error:
        raise InspectionError(
            f"CSV encoding or structure failed; no complete result: {error}"
        ) from error
    if not records or not width or (header and len(records) < 2):
        raise InspectionError("Choose a CSV containing data records and at least one field.")
    if header and len(records[0][0]) != width:
        raise InspectionError(
            "The selected header must cover every field, including fields on later records."
        )
    labels = records[0][0] if header else ("",) * width
    rows = []
    evidence_size = 0
    for row, (record_values, first_line, last_line) in enumerate(records, 1):
        check_cancelled(cancelled)
        cells = tuple(
            _cell(
                record_values[column - 1] if column <= len(record_values) else None,
                "Present" if column <= len(record_values) else "Absent",
                {
                    "format": "csv",
                    "source_sha256": identity,
                    "record": row,
                    "field": column,
                    "first_line": first_line,
                    "last_line": last_line,
                    "record_field_count": len(record_values),
                },
            )
            for column in range(1, width + 1)
        )
        evidence_size += len(canonical(cells).encode("utf-8"))
        if evidence_size > MAX_RESULT_BYTES:
            raise InspectionError("CSV evidence exceeds the 128 MiB limit.")
        rows.append(cells)
    if _identity(path, cancelled) != identity:
        raise InspectionError("CSV source changed during reading.")
    metadata = {
        "format": "csv",
        "source_sha256": identity,
        "options": {
            "encoding": encoding,
            "delimiter": delimiter,
            "header": header,
            "quotechar": '"',
            "doublequote": True,
            "strict": True,
        },
        "record_count": len(rows),
        "field_count": width,
        "headers": labels,
        "first_data_record": 2 if header else 1,
        "header_evidence": rows[0] if header else None,
    }
    return SourceRecords(canonical(metadata), tuple(rows))


def check_xml_table(table: SavedXmlTable) -> None:
    saved = load_xml_selections(table.source_sha256)
    if not any(
        item.id == table.id and item.name == table.name and item.group_path == table.group_path
        for item in saved.data_sets
    ):
        raise ValueError("XML data set changed or was removed; save the current group first.")


def read_xml_records(
    path: Path, table: SavedXmlTable, *, cancelled: Event | None = None
) -> SourceRecords:
    """Reuse the protected XML parser, retaining namespace aliases plus their exact URIs."""
    if path.suffix.lower() != ".xml":
        raise InspectionError("XML scope requires an XML source.")
    check_xml_table(table)
    if table.record_count * table.field_count > MAX_CELLS:
        raise InspectionError("XML group exceeds the 200,000 complete-cell limit.")
    discovery = _Target(cancelled, table.group_path, collect_preview=False)
    identity = _parse(path, discovery)
    candidates = [key for key, value in discovery.groups.items() if value.repeated]
    if not candidates:
        candidates = [next(iter(discovery.groups))]
    if discovery.problem:
        raise InspectionError(discovery.problem)
    if (
        identity != table.source_sha256
        or table.group_path not in candidates
        or discovery.records != table.record_count
        or len(discovery.fields) != table.field_count
    ):
        raise InspectionError("XML source or complete group dimensions changed.")
    fields = tuple(discovery.fields)
    rows: list[tuple[dict[str, Any], ...]] = []
    size = 0

    def visit(row: int, location: str, values: dict[str, PreviewCell]) -> None:
        nonlocal size
        check_cancelled(cancelled)
        if row != len(rows) + 1 or row > table.record_count:
            raise InspectionError("XML records no longer match the complete group.")
        cells = []
        for column, key in enumerate(fields, 1):
            cell = values.get(key)
            presence = cell.presence if cell else "Absent"
            if presence not in {"Present", "Absent", "Empty element", "Explicit nil"}:
                raise InspectionError("Unsupported XML presence state.")
            assert presence is not None
            cells.append(
                _cell(
                    cell.text if cell is not None else None,
                    presence,
                    {
                        "format": "xml",
                        "source_sha256": identity,
                        "record": row,
                        "field": column,
                        "record_path": location,
                        "field_path": key,
                        "node_path": cell.source_path if cell else None,
                    },
                )
            )
        size += len(canonical(cells).encode("utf-8"))
        if size > MAX_RESULT_BYTES:
            raise InspectionError("XML evidence exceeds the 128 MiB limit.")
        rows.append(tuple(cells))

    target = _Target(cancelled, table.group_path, collect_preview=False, on_full_record=visit)
    if _parse(path, target) != identity or _identity(path, cancelled) != identity:
        raise InspectionError("XML source changed during reading.")
    if target.problem:
        raise InspectionError(target.problem)
    if len(rows) != table.record_count or tuple(target.fields) != fields:
        raise InspectionError("Incomplete XML group coverage.")
    check_xml_table(table)
    return SourceRecords(
        canonical(
            {
                "format": "xml",
                "source_sha256": identity,
                "options": {
                    "group_path": table.group_path,
                    "group_label": table.group_label,
                    "namespaces": discovery.namespaces,
                },
                "record_count": len(rows),
                "field_count": len(fields),
                "headers": fields,
                "first_data_record": 1,
                "header_evidence": None,
            }
        ),
        tuple(rows),
    )
