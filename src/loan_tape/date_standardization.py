"""Source-bound date import and interpretation, independent of red-flag rules."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from loan_tape.date_parser import DateProfile, DateResult, DateSource, parse_date
from loan_tape.date_reader import DateColumnEvidence, read_excel_date_columns
from loan_tape.pack_format import load_pack_files
from loan_tape.packs import Catalog
from loan_tape.selection import SavedTable
from loan_tape.workbook_index import _digest, check_cancelled

STANDARDIZATION_VERSION = "1.0.0"
MAX_STANDARDIZED_CELLS = 200_000
STATUSES = ("valid", "ambiguous", "invalid", "missing", "unsupported", "source_error")


@dataclass(frozen=True)
class DateMapping:
    """One explicit source-to-field mapping and its interpretation profile."""

    column: int
    field_id: str
    profile: DateProfile

    def __post_init__(self) -> None:
        if type(self.column) is not int or not 1 <= self.column <= 16_384:
            raise ValueError("Original date column must be between 1 and 16,384.")
        if not isinstance(self.field_id, str) or not self.field_id:
            raise ValueError("Date mapping requires a field ID.")
        if not isinstance(self.profile, DateProfile):
            raise ValueError("Date mapping requires an explicit interpretation profile.")


@dataclass(frozen=True)
class StandardizedDateColumn:
    """Complete parser outcomes for one mapped source column."""

    column: int
    field_id: str
    status_counts: tuple[tuple[str, int], ...]
    cells: tuple[DateResult, ...]

    @property
    def valid_count(self) -> int:
        return dict(self.status_counts)["valid"]

    @property
    def unresolved_count(self) -> int:
        return len(self.cells) - self.valid_count


@dataclass(frozen=True)
class DateStandardization:
    """Immutable handoff from import/interpretation to optional red-flag review."""

    table: SavedTable
    mappings: tuple[DateMapping, ...]
    catalog: Catalog
    evidence: tuple[DateColumnEvidence, ...]
    columns: tuple[StandardizedDateColumn, ...]
    row_count: int
    cell_count: int
    all_dates_interpreted_row_count: int
    rows_with_unresolved_dates: int
    engine_version: str = STANDARDIZATION_VERSION


def standardize_dates(
    table: SavedTable,
    evidence: tuple[DateColumnEvidence, ...],
    mappings: tuple[DateMapping, ...],
    catalog: Catalog,
    *,
    cancelled: Event | None = None,
) -> DateStandardization:
    """Interpret complete retained evidence without applying any review rules."""
    check_cancelled(cancelled)
    if not isinstance(table, SavedTable) or not isinstance(catalog, Catalog):
        raise ValueError("Date standardization requires a saved data set and dictionary catalog.")
    if not isinstance(mappings, tuple) or any(not isinstance(v, DateMapping) for v in mappings):
        raise ValueError("Date mappings must be an immutable tuple of validated mappings.")
    if not isinstance(evidence, tuple) or any(
        not isinstance(v, DateColumnEvidence) for v in evidence
    ):
        raise ValueError("Date evidence must be an immutable tuple of complete columns.")
    if not mappings:
        raise ValueError("Choose at least one explicitly mapped date column.")

    ordered_mappings = tuple(sorted(mappings, key=lambda item: item.column))
    mapping_columns = [item.column for item in ordered_mappings]
    mapping_fields = [item.field_id for item in ordered_mappings]
    if len(mapping_columns) != len(set(mapping_columns)) or len(mapping_fields) != len(
        set(mapping_fields)
    ):
        raise ValueError("Each date field and source column can be mapped only once.")

    selection = table.selection
    first = selection.header_row + 1 if selection.header_row is not None else selection.area.min_row
    rows = range(first, selection.area.max_row + 1)
    if len(rows) * len(ordered_mappings) > MAX_STANDARDIZED_CELLS:
        raise ValueError(f"Date standardization exceeds the {MAX_STANDARDIZED_CELLS:,}-cell limit.")

    by_column = {item.column: item for item in evidence}
    if len(by_column) != len(evidence) or set(by_column) != set(mapping_columns):
        raise ValueError("Every mapped date column needs one complete evidence column.")
    if len({pack.id for pack in catalog.packs}) != len(catalog.packs):
        raise ValueError("Dictionary catalog has duplicate pack IDs.")
    for pack in catalog.packs:
        if load_pack_files(dict(pack.files)) != pack:
            raise ValueError("Dictionary object differs from its retained source snapshot.")

    standardized: list[StandardizedDateColumn] = []
    valid_rows: dict[int, set[int]] = {}
    for mapping in ordered_mappings:
        check_cancelled(cancelled)
        definition = catalog.get_field(mapping.field_id).field
        if definition.data_type != "date":
            raise ValueError("Mapped dictionary field is not a date.")
        column = by_column[mapping.column]
        if (
            column.selection != selection
            or not selection.area.min_column <= mapping.column <= selection.area.max_column
        ):
            raise ValueError("Date evidence belongs to a different selection or column.")
        if column.date_system not in ("1900", "1904") or len(column.cells) != len(rows):
            raise ValueError("Incomplete date evidence or invalid workbook date system.")

        parsed: list[DateResult] = []
        valid: set[int] = set()
        counts: Counter[str] = Counter()
        for row, cell in zip(rows, column.cells, strict=True):
            check_cancelled(cancelled)
            expected = DateSource(selection.workbook_sha256, row, mapping.column, selection.sheet)
            if cell.source != expected or cell.date_system not in (None, column.date_system):
                raise ValueError("Date evidence is missing, reordered or has inconsistent lineage.")
            result = parse_date(cell, mapping.profile)
            parsed.append(result)
            counts[result.status] += 1
            if result.status == "valid":
                valid.add(row)
        valid_rows[mapping.column] = valid
        standardized.append(
            StandardizedDateColumn(
                mapping.column,
                mapping.field_id,
                tuple((status, counts[status]) for status in STATUSES),
                tuple(parsed),
            )
        )

    interpreted_rows = sum(
        all(row in valid_rows[mapping.column] for mapping in ordered_mappings) for row in rows
    )
    return DateStandardization(
        table,
        ordered_mappings,
        catalog,
        tuple(by_column[mapping.column] for mapping in ordered_mappings),
        tuple(standardized),
        len(rows),
        len(rows) * len(ordered_mappings),
        interpreted_rows,
        len(rows) - interpreted_rows,
    )


def standardize_excel_dates(
    path: Path,
    table: SavedTable,
    mappings: tuple[DateMapping, ...],
    catalog: Catalog,
    *,
    cancelled: Event | None = None,
    max_rows: int = 100_000,
) -> DateStandardization:
    """Import complete mapped columns once, then publish a parser-only handoff."""
    first = (
        table.selection.header_row + 1
        if table.selection.header_row is not None
        else table.selection.area.min_row
    )
    if (table.selection.area.max_row - first + 1) * len(mappings) > MAX_STANDARDIZED_CELLS:
        raise ValueError("Selected date standardization exceeds the cell limit.")
    evidence = read_excel_date_columns(
        path,
        table.selection,
        tuple(mapping.column for mapping in mappings),
        cancelled=cancelled,
        max_rows=max_rows,
    )
    result = standardize_dates(table, evidence, mappings, catalog, cancelled=cancelled)
    if _digest(path, cancelled) != table.selection.workbook_sha256:
        raise ValueError(
            "Source changed during date standardization; no completed result was returned."
        )
    check_cancelled(cancelled)
    return result
