"""Independent table definitions and compatibility with earlier saved ranges."""

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from loan_tape.ranges import parse_range
from loan_tape.selection import (
    MAX_SAVED_TABLES,
    MAX_SELECTION_FILE_BYTES,
    SavedTable,
    SourceSelection,
    TableSelections,
    load_selection,
    load_tables,
    save_selection,
    save_tables,
    selection_path,
)

SHA = "a" * 64


def table(identity, name, area, header, sheet="Loans"):
    return SavedTable(identity * 32, name, SourceSelection(SHA, sheet, parse_range(area), header))


def test_multiple_tables_edit_and_remove_without_overwriting_other_ranges(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    first = table("1", "Top", "B5:M40", 5)
    second = table("2", "Below", "B90:M200", 92)
    third = table("3", "Beside", "Z5:AK40", 5)
    settings = TableSelections(SHA, (first, second, third), second.id)
    save_tables(settings)
    assert load_tables(SHA) == settings
    assert load_tables("b" * 64).tables == ()
    updated = replace(second.selection, header_row=93)
    save_selection(updated)
    loaded = load_tables(SHA)
    assert len(loaded.tables) == 3
    assert next(t for t in loaded.tables if t.id == first.id) == first
    assert next(t for t in loaded.tables if t.id == third.id) == third
    assert load_selection(SHA) == updated
    save_tables(TableSelections(SHA, (first, third), first.id))
    assert load_tables(SHA).tables == (first, third)
    save_tables(TableSelections(SHA))
    assert load_tables(SHA).tables == ()
    assert load_selection(SHA) is None


def test_migrate_legacy_range_preserving_all_coordinates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = selection_path(SHA)
    target.parent.mkdir(parents=True)
    original = {
        "schema_version": 1,
        "workbook_sha256": SHA,
        "sheet": "Hidden loans",
        "range": "G450:AZ18400",
        "header_row": 451,
    }
    target.write_text(json.dumps(original), encoding="utf-8")
    loaded = load_tables(SHA)
    assert loaded.active.name == "Data set 1"
    assert loaded.active.selection == SourceSelection(
        SHA, "Hidden loans", parse_range("G450:AZ18400"), 451
    )
    assert json.loads(target.read_text()) == original  # Read-only migration until saved.
    second = table("2", "Second", "A2:C6", 2)
    save_tables(TableSelections(SHA, (*loaded.tables, second), second.id))
    assert load_tables(SHA).tables[0] == loaded.active
    assert json.loads(target.read_text())["schema_version"] == 2


def test_reject_invalid_header_duplicate_names_and_wrong_source():
    first = table("1", "Loans", "A3:C8", 3)
    with pytest.raises(ValueError, match="Header row"):
        table("2", "Other", "A10:C18", 3)
    with pytest.raises(ValueError, match="name"):
        TableSelections(SHA, (first, table("2", " LOANS ", "A10:C18", 10)))
    with pytest.raises(ValueError, match="source identity"):
        TableSelections("b" * 64, (first,))
    with pytest.raises(ValueError, match="active data set"):
        TableSelections(SHA, (first,), "2" * 32)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        None,
        {"schema_version": 7, "workbook_sha256": SHA},
        {"schema_version": 2, "workbook_sha256": SHA, "tables": [None], "active_id": None},
    ],
)
def test_corrupt_settings_fail_clearly(tmp_path, monkeypatch, payload):
    monkeypatch.chdir(tmp_path)
    target = selection_path(SHA)
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="Saved data set settings"):
        load_tables(SHA)


def test_reject_duplicate_keys_and_oversized_settings(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = selection_path(SHA)
    target.parent.mkdir(parents=True)
    target.write_text(
        '{"schema_version":2,"schema_version":1,"workbook_sha256":"' + SHA + '"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Saved data set settings"):
        load_tables(SHA)

    target.write_bytes(b" " * (MAX_SELECTION_FILE_BYTES + 1))
    with pytest.raises(ValueError, match="Saved data set settings"):
        load_tables(SHA)


def test_reject_excessive_saved_table_count():
    tables = tuple(
        SavedTable(
            f"{index:032x}",
            f"Data set {index}",
            SourceSelection(SHA, "Loans", parse_range("A1:B2"), 1),
        )
        for index in range(MAX_SAVED_TABLES + 1)
    )
    with pytest.raises(ValueError, match="At most"):
        TableSelections(SHA, tables)


def test_failed_atomic_save_preserves_previous_tables(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    first = table("1", "Loans", "A3:C8", 3)
    original = TableSelections(SHA, (first,), first.id)
    save_tables(original)
    with patch.object(Path, "replace", side_effect=OSError("Cannot replace")):
        with pytest.raises(OSError):
            save_tables(TableSelections(SHA))
    assert load_tables(SHA) == original
    assert list(selection_path(SHA).parent.glob("*.tmp")) == []
