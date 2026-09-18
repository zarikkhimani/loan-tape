"""Persist independent table definitions, preserving complete source coordinates."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from loan_tape.ranges import CellRange, parse_range

MAX_SELECTION_FILE_BYTES = 2 * 1024 * 1024
MAX_SAVED_TABLES = 1_000


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate settings key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_number(value: str) -> None:
    raise ValueError(f"Invalid non-finite number: {value}")


@dataclass(frozen=True)
class SourceSelection:
    workbook_sha256: str
    sheet: str
    area: CellRange
    header_row: int | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", self.workbook_sha256):
            raise ValueError("Invalid source identity for the selection.")
        if not isinstance(self.sheet, str) or not self.sheet:
            raise ValueError("Choose a worksheet.")
        if self.header_row is not None and (
            type(self.header_row) is not int
            or not self.area.min_row <= self.header_row <= self.area.max_row
        ):
            raise ValueError(
                "Header row must be an original worksheet row inside the selected range."
            )


def selection_path(sha256: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValueError("Invalid source identity.")
    return Path.cwd() / ".artifacts" / "selections" / (sha256 + ".json")


@dataclass(frozen=True)
class SavedTable:
    id: str
    name: str
    selection: SourceSelection

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not re.fullmatch(r"[0-9a-f]{32}", self.id):
            raise ValueError("Invalid data set identity.")
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 80:
            raise ValueError("Give the data set a name of 1 to 80 characters.")


@dataclass(frozen=True)
class TableSelections:
    workbook_sha256: str
    tables: tuple[SavedTable, ...] = ()
    active_id: str | None = None

    def __post_init__(self) -> None:
        selection_path(self.workbook_sha256)
        if len(self.tables) > MAX_SAVED_TABLES:
            raise ValueError(f"At most {MAX_SAVED_TABLES:,} data sets can be saved per workbook.")
        ids = [table.id for table in self.tables]
        names = [table.name.strip().casefold() for table in self.tables]
        if len(ids) != len(set(ids)) or len(names) != len(set(names)):
            raise ValueError("Each data set needs its own identity and name.")
        if any(table.selection.workbook_sha256 != self.workbook_sha256 for table in self.tables):
            raise ValueError("Data set source identity does not match this workbook.")
        if self.active_id is not None and self.active_id not in ids:
            raise ValueError("The active data set is missing.")

    @property
    def active(self) -> SavedTable | None:
        return next((table for table in self.tables if table.id == self.active_id), None)


def save_tables(settings: TableSelections) -> None:
    target = selection_path(settings.workbook_sha256)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix("." + uuid4().hex + ".tmp")
    try:
        temporary.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "workbook_sha256": settings.workbook_sha256,
                    "active_id": settings.active_id,
                    "tables": [
                        {
                            "id": table.id,
                            "name": table.name,
                            "sheet": table.selection.sheet,
                            "range": table.selection.area.address,
                            "header_row": table.selection.header_row,
                        }
                        for table in settings.tables
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def load_tables(sha256: str) -> TableSelections:
    target = selection_path(sha256)
    if not target.exists():
        return TableSelections(sha256)
    try:
        with target.open("rb") as handle:
            raw = handle.read(MAX_SELECTION_FILE_BYTES + 1)
        if len(raw) > MAX_SELECTION_FILE_BYTES:
            raise ValueError("Saved data set settings are too large.")
        data = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_number,
        )
        if not isinstance(data, dict) or data["workbook_sha256"] != sha256:
            raise ValueError("Selection identity does not match.")
        if type(data["schema_version"]) is not int:
            raise ValueError("Invalid settings version.")
        if data["schema_version"] == 1:
            table = SavedTable(
                "0" * 32,
                "Data set 1",
                SourceSelection(
                    sha256, data["sheet"], parse_range(data["range"]), data["header_row"]
                ),
            )
            return TableSelections(sha256, (table,), table.id)
        if data["schema_version"] != 2 or not isinstance(data["tables"], list):
            raise ValueError("Unsupported data set settings version.")
        if len(data["tables"]) > MAX_SAVED_TABLES:
            raise ValueError("Saved data set settings contain too many data sets.")
        tables = tuple(
            SavedTable(
                item["id"],
                item["name"],
                SourceSelection(
                    sha256, item["sheet"], parse_range(item["range"]), item["header_row"]
                ),
            )
            for item in data["tables"]
        )
        return TableSelections(sha256, tables, data["active_id"])
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError) as error:
        raise ValueError(
            "Saved data set settings could not be read. Choose and save the data sets again."
        ) from error


def save_selection(selection: SourceSelection) -> None:
    """Update the active selection without discarding other saved tables."""
    settings = load_tables(selection.workbook_sha256)
    active = settings.active
    table = SavedTable(
        active.id if active else uuid4().hex, active.name if active else "Data set 1", selection
    )
    others = tuple(item for item in settings.tables if item.id != table.id)
    save_tables(TableSelections(selection.workbook_sha256, (*others, table), table.id))


def load_selection(sha256: str) -> SourceSelection | None:
    """Return the active table for callers that only need one current scope."""
    active = load_tables(sha256).active
    return active.selection if active else None
