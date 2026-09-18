"""Complete, sparse workbook discovery; never evaluate source formulas."""

from __future__ import annotations

import hashlib
import posixpath
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from xml.etree.ElementTree import Element
from zipfile import ZipFile

from defusedxml.ElementTree import fromstring, iterparse  # type: ignore[import-untyped]

from loan_tape.inspection import InspectionError
from loan_tape.ooxml_safety import validate_ooxml_archive
from loan_tape.ranges import CellRange, parse_range
from loan_tape.table_structure import (
    StructureDetector,
    TableSuggestion,
)

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MAX_SUGGESTIONS = 200


@dataclass(frozen=True)
class SheetIndex:
    name: str
    visibility: str
    bounds: CellRange | None = None
    stored_cells: int = 0
    areas: tuple[CellRange, ...] = ()
    hidden_rows: int = 0
    hidden_columns: int = 0
    merged_ranges: int = 0
    condensed: bool = False
    error: str | None = None
    tables: tuple[TableSuggestion, ...] = ()


@dataclass(frozen=True)
class WorkbookIndex:
    sha256: str
    sheets: tuple[SheetIndex, ...]

    @property
    def complete(self) -> bool:
        return all(sheet.error is None for sheet in self.sheets)


class ScanCancelled(InspectionError):
    pass


def check_cancelled(cancelled: Event | None) -> None:
    if cancelled is not None and cancelled.is_set():
        raise ScanCancelled("Workbook scan cancelled; coverage is incomplete.")


def _digest(path: Path, cancelled: Event | None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            check_cancelled(cancelled)
            digest.update(chunk)
    return digest.hexdigest()


def _part(base: str, target: str) -> str:
    result = posixpath.normpath(posixpath.join(posixpath.dirname(base), target))
    if target.startswith("/"):
        result = posixpath.normpath(target).lstrip("/")
    if result.startswith("../") or ":" in result or "\\" in result:
        raise InspectionError("Workbook contains an unsupported package relationship.")
    return result


def _scan_sheet(
    archive: ZipFile,
    part: str,
    name: str,
    visibility: str,
    cancelled: Event | None,
    progress: Callable[[str], None],
) -> SheetIndex:
    bounds: CellRange | None = None
    areas: list[CellRange] = []
    count = hidden_rows = merged = 0
    hidden_columns: set[int] = set()
    band_top = band_bottom = 0
    band_columns: set[int] = set()
    condensed = False
    detector = StructureDetector()
    declared = _sheet_tables(archive, part, cancelled)
    table_ids: list[str] = []

    def finish_band() -> None:
        nonlocal condensed
        columns = sorted(band_columns)
        if not columns or condensed:
            return
        left = right = columns[0]
        for column in columns[1:] + [16385]:
            if column != right + 1 or column == 16385:
                areas.append(CellRange(band_top, left, band_bottom, right))
                left = column
                if len(areas) > MAX_SUGGESTIONS:
                    condensed = True
                    areas.clear()
                    return
            right = column

    stack: list[Element] = []
    previous_row = 0
    with archive.open(part) as source:
        for event, element in iterparse(source, events=("start", "end")):
            if event == "start":
                if not stack and element.tag != f"{{{NS}}}worksheet":
                    raise InspectionError(
                        "Unsupported worksheet XML format; this sheet was not scanned."
                    )
                stack.append(element)
                continue
            check_cancelled(cancelled)
            tag = element.tag.rsplit("}", 1)[-1]
            if tag == "row":
                row = int(element.get("r", str(previous_row + 1)))
                if not previous_row < row <= 1048576:
                    raise InspectionError(
                        "Unordered or invalid worksheet rows; scan is incomplete."
                    )
                previous_row = row
                hidden_rows += element.get("hidden") in {"1", "true"}
                columns: set[int] = set()
                text_columns: set[int] = set()
                previous_column = 0
                for cell in element.findall(f"{{{NS}}}c"):
                    ref = cell.get("r")
                    position = (
                        parse_range(ref)
                        if ref
                        else CellRange(row, previous_column + 1, row, previous_column + 1)
                    )
                    column = position.min_column
                    if (
                        position.min_row != row
                        or column <= previous_column
                        or position.row_count != 1
                        or position.column_count != 1
                    ):
                        raise InspectionError(
                            "Invalid or duplicated cell positions; scan is incomplete."
                        )
                    previous_column = column
                    stored = cell.get("t") == "inlineStr" or any(
                        child.tag.rsplit("}", 1)[-1] in {"f", "is"}
                        or (child.tag.rsplit("}", 1)[-1] == "v" and child.text is not None)
                        for child in cell
                    )
                    if stored:
                        columns.add(column)
                        if (
                            cell.get("t") in {"inlineStr", "s", "str"}
                            and cell.find(f"{{{NS}}}f") is None
                        ):
                            text_columns.add(column)
                # Declared Excel tables own their cells. Detect other tables outside
                # them so a touching plain range is not merged and discarded.
                unassigned = columns.copy()
                for table in declared:
                    area = table.area
                    if area.min_row <= row <= area.max_row:
                        unassigned = {
                            column
                            for column in unassigned
                            if not area.min_column <= column <= area.max_column
                        }
                detector.observe(row, unassigned, text_columns.intersection(unassigned))
                if columns:
                    count += len(columns)
                    low, high = min(columns), max(columns)
                    bounds = (
                        CellRange(
                            min(bounds.min_row, row),
                            min(bounds.min_column, low),
                            row,
                            max(bounds.max_column, high),
                        )
                        if bounds
                        else CellRange(row, low, row, high)
                    )
                    if band_bottom and row != band_bottom + 1:
                        finish_band()
                        band_columns.clear()
                        band_top = 0
                    band_top = band_top or row
                    band_bottom = row
                    band_columns.update(columns)
                if row % 5000 == 0:
                    progress(f"Scanning {name}: reached source row {row:,}…")
                element.clear()
                if len(stack) > 1:
                    stack[-2].remove(element)
            elif tag == "col" and element.get("hidden") in {"1", "true"}:
                first, last = int(element.get("min", "0")), int(element.get("max", "0"))
                if not 1 <= first <= last <= 16384:
                    raise InspectionError("Invalid hidden-column metadata; scan is incomplete.")
                hidden_columns.update(range(first, last + 1))
            elif tag == "tablePart":
                table_ids.append(element.attrib[f"{{{REL}}}id"])
            elif tag == "mergeCell":
                merged += 1
                element.clear()
            stack.pop()
    finish_band()
    if condensed and bounds:
        areas = [bounds]
    inferred = detector.finish()
    if _declared_tables(archive, part, table_ids, cancelled) != declared:
        raise InspectionError("Inconsistent table metadata; scan is incomplete.")
    suggestions = (*declared, *inferred)
    return SheetIndex(
        name,
        visibility,
        bounds,
        count,
        tuple(areas),
        hidden_rows,
        len(hidden_columns),
        merged,
        condensed,
        tables=tuple(
            sorted(suggestions, key=lambda item: (item.area.min_row, item.area.min_column))
        ),
    )


def _sheet_tables(
    archive: ZipFile, sheet_part: str, cancelled: Event | None
) -> tuple[TableSuggestion, ...]:
    """Read referenced table definitions before inferring the remaining cells.

    Only sheets with table relationships need this lightweight metadata pass.
    Clear each row as it is read; worksheet values are never retained here.
    """
    folder, filename = posixpath.split(sheet_part)
    rel_part = posixpath.join(folder, "_rels", filename + ".rels")
    if rel_part not in archive.namelist():
        return ()
    relations = fromstring(archive.read(rel_part))
    if not any(item.get("Type", "").endswith("/table") for item in relations):
        return ()
    ids = []
    stack: list[Element] = []
    with archive.open(sheet_part) as source:
        for event, element in iterparse(source, events=("start", "end")):
            check_cancelled(cancelled)
            if event == "start":
                stack.append(element)
                continue
            if element.tag == f"{{{NS}}}tablePart":
                ids.append(element.attrib[f"{{{REL}}}id"])
            element.clear()
            if len(stack) > 1:
                stack[-2].remove(element)
            stack.pop()
    return _declared_tables(archive, sheet_part, ids, cancelled)


def _declared_tables(
    archive: ZipFile, sheet_part: str, ids: list[str], cancelled: Event | None
) -> tuple[TableSuggestion, ...]:
    if not ids:
        return ()
    folder, filename = posixpath.split(sheet_part)
    relationships = fromstring(archive.read(posixpath.join(folder, "_rels", filename + ".rels")))
    targets = {item.get("Id"): item for item in relationships}
    tables = []
    for identity in ids:
        check_cancelled(cancelled)
        relation = targets[identity]
        if relation.get("TargetMode", "").lower() == "external" or not relation.get(
            "Type", ""
        ).endswith("/table"):
            raise InspectionError("Unsupported Excel table relationship; scan is incomplete.")
        definition = fromstring(archive.read(_part(sheet_part, relation.attrib["Target"])))
        if definition.tag != f"{{{NS}}}table":
            raise InspectionError("Unsupported Excel table definition; scan is incomplete.")
        area = parse_range(definition.attrib["ref"])
        headers = int(definition.get("headerRowCount", "1"))
        if headers not in {0, 1}:
            raise InspectionError("Unsupported Excel table header count; scan is incomplete.")
        tables.append(
            TableSuggestion(
                area,
                area.min_row if headers else None,
                definition.get("displayName", ""),
                "excel_table",
            )
        )
    return tuple(tables)


def scan_workbook(
    path: Path, *, cancelled: Event | None = None, progress: Callable[[str], None] | None = None
) -> WorkbookIndex:
    """Read all physical worksheet cells, independent of stored dimensions or position.

    Counts describe cells containing stored content/formulas, including explicit
    empty text. Style-only cells do not enlarge data bounds. Areas retain complete
    location coverage; tentative table/header suggestions are separate from it.
    """
    report = progress or (lambda message: None)
    check_cancelled(cancelled)
    before = _digest(path, cancelled)
    sheets: list[SheetIndex] = []
    with ZipFile(path) as archive:
        validate_ooxml_archive(
            archive,
            error_type=InspectionError,
            cancelled=lambda: check_cancelled(cancelled),
        )
        relationships = fromstring(archive.read("_rels/.rels"))
        office = [
            item for item in relationships if item.get("Type", "").endswith("/officeDocument")
        ]
        if len(office) != 1 or office[0].get("TargetMode", "").lower() == "external":
            raise InspectionError("Could not locate the workbook inside this file.")
        workbook_part = _part("", office[0].attrib["Target"])
        book = fromstring(archive.read(workbook_part))
        if book.tag != f"{{{NS}}}workbook":
            raise InspectionError("Unsupported workbook XML format; no complete scan is available.")
        folder, filename = posixpath.split(workbook_part)
        rels = fromstring(archive.read(posixpath.join(folder, "_rels", filename + ".rels")))
        targets = {item.get("Id"): item for item in rels}
        for sheet in book.findall(f"{{{NS}}}sheets/{{{NS}}}sheet"):
            check_cancelled(cancelled)
            name, visibility = sheet.attrib["name"], sheet.get("state", "visible")
            report(f"Scanning {name} across all source rows and columns…")
            try:
                relationship = targets[sheet.get(f"{{{REL}}}id")]
                if (
                    not relationship.get("Type", "").endswith("/worksheet")
                    or relationship.get("TargetMode", "").lower() == "external"
                ):
                    raise InspectionError("Non-worksheet tab; cell inspection is unsupported.")
                part = _part(workbook_part, relationship.attrib["Target"])
                result = _scan_sheet(archive, part, name, visibility, cancelled, report)
            except ScanCancelled:
                raise
            except Exception as error:
                message = (
                    str(error)
                    if isinstance(error, InspectionError)
                    else "Could not scan this sheet; coverage is incomplete."
                )
                result = SheetIndex(name, visibility, error=message)
            sheets.append(result)
    if not sheets:
        raise InspectionError("This workbook has no sheets to inspect.")
    if _digest(path, cancelled) != before:
        raise InspectionError("The workbook changed during discovery. Reopen Inspect file.")
    return WorkbookIndex(before, tuple(sheets))
