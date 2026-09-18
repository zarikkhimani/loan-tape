import json
from dataclasses import replace
from pathlib import Path

import pytest

from loan_tape.column_definitions import (
    ColumnDefinition,
    ColumnRules,
    definition_for_column,
    definition_path,
    definitions_for_table,
    load_column_definitions,
    remove_column_definition,
    save_column_definition,
    snapshot_field,
)
from loan_tape.pack_format import load_pack
from loan_tape.packs import Catalog
from loan_tape.ranges import parse_range
from loan_tape.selection import SavedTable, SourceSelection

SHA = "a" * 64


@pytest.fixture
def catalog() -> Catalog:
    pack = load_pack(Path(__file__).parents[1] / "packs" / "example-loans")
    return Catalog("default", (pack,))


@pytest.fixture
def table() -> SavedTable:
    return SavedTable(
        "1" * 32,
        "Loans",
        SourceSelection(SHA, "Tape", parse_range("A1:D10"), 1),
    )


def field(catalog: Catalog, field_id: str):
    return snapshot_field(catalog, catalog.get_field(f"example.loans:{field_id}"))


def test_saves_exact_field_snapshot_representation_and_rules(tmp_path, monkeypatch, catalog, table):
    monkeypatch.chdir(tmp_path)
    loan_id = ColumnDefinition(
        1,
        "Loan ID",
        field(catalog, "loan_id"),
        rules=ColumnRules(required=True, blank_allowed=False, unique=True),
    )
    balance = ColumnDefinition(
        2,
        "Balance",
        field(catalog, "principal_balance"),
        currency="USD",
        source_unit="whole currency units",
        rules=ColumnRules(minimum="0", missing_tokens=("N/A",), notes="Zero is a value."),
    )
    maturity = ColumnDefinition(
        3,
        "Maturity Date",
        field(catalog, "maturity_date"),
        date_formats=("YYYY-MM-DD", "M/D/YY"),
        two_digit_year_start=1970,
    )

    for definition in (loan_id, balance, maturity):
        save_column_definition(table, definition)

    assert definitions_for_table(table) == (loan_id, balance, maturity)
    assert definition_for_column(table, 2) == balance
    payload = json.loads(definition_path(SHA).read_text(encoding="utf-8"))
    saved = payload["scopes"][0]["definitions"][1]
    assert saved["field"]["data_type"] == "decimal"
    assert saved["field"]["canonical_unit"] == "currency units"
    assert saved["field"]["pack_version"] == catalog.packs[0].version
    assert saved["field"]["pack_fingerprint"] == catalog.packs[0].fingerprint
    assert saved["currency"] == "USD" and saved["source_unit"] == "whole currency units"
    assert saved["rules"]["minimum"] == "0"
    assert payload["scopes"][0]["definitions"][2]["two_digit_year_start"] == 1970
    assert load_column_definitions(SHA).for_table(table) is not None


def test_category_snapshot_freezes_allowed_code_meanings(catalog):
    status = field(catalog, "status")
    assert status.code_list == "loan_status"
    assert [(item.value, item.label) for item in status.allowed_values] == [
        ("CURRENT", "Current"),
        ("DEFAULT", "Default"),
    ]


def test_edit_remove_and_changed_scope_are_explicit(tmp_path, monkeypatch, catalog, table):
    monkeypatch.chdir(tmp_path)
    original = ColumnDefinition(1, "Loan ID", field(catalog, "loan_id"))
    updated = replace(original, rules=ColumnRules(unique=True))
    save_column_definition(table, original)
    save_column_definition(table, updated)
    assert definitions_for_table(table) == (updated,)

    changed = replace(
        table,
        selection=replace(table.selection, area=parse_range("A1:D20")),
    )
    assert definitions_for_table(changed) == ()
    save_column_definition(
        changed,
        ColumnDefinition(
            2,
            "Balance",
            field(catalog, "principal_balance"),
            currency="EUR",
            source_unit="currency units",
        ),
    )
    assert definition_for_column(table, 1) == updated
    assert definition_for_column(changed, 2).currency == "EUR"
    assert remove_column_definition(changed, 2)
    assert not remove_column_definition(changed, 2)
    assert definitions_for_table(changed) == ()
    assert definition_for_column(table, 1) == updated


@pytest.mark.parametrize(
    "build,match",
    [
        (
            lambda catalog: ColumnDefinition(1, "Date", field(catalog, "maturity_date")),
            "Date columns require",
        ),
        (
            lambda catalog: ColumnDefinition(
                1,
                "Date",
                field(catalog, "maturity_date"),
                date_formats=("M/D/YY",),
            ),
            "require an explicit year-window",
        ),
        (
            lambda catalog: ColumnDefinition(1, "ID", field(catalog, "loan_id"), currency="USD"),
            "Currency applies only",
        ),
        (
            lambda catalog: ColumnDefinition(
                1,
                "Balance",
                field(catalog, "principal_balance"),
                currency="usd",
                source_unit="currency units",
            ),
            "three-letter uppercase",
        ),
        (
            lambda catalog: ColumnDefinition(1, "Balance", field(catalog, "principal_balance")),
            "requires an explicit",
        ),
        (
            lambda catalog: ColumnDefinition(
                1,
                "Balance",
                field(catalog, "principal_balance"),
                currency="USD",
            ),
            "requires explicit source units",
        ),
        (
            lambda catalog: ColumnDefinition(
                1,
                "Balance",
                field(catalog, "principal_balance"),
                rules=ColumnRules(minimum="2", maximum="1"),
            ),
            "Minimum rule cannot exceed",
        ),
        (
            lambda catalog: ColumnDefinition(
                1,
                "ID",
                field(catalog, "loan_id"),
                rules=ColumnRules(required=True, blank_allowed=True),
            ),
            "required column",
        ),
    ],
)
def test_rejects_incompatible_or_ambiguous_settings(catalog, build, match):
    with pytest.raises(ValueError, match=match):
        build(catalog)


def test_rejects_definition_outside_scope_and_damaged_file(tmp_path, monkeypatch, catalog, table):
    monkeypatch.chdir(tmp_path)
    outside = ColumnDefinition(5, "Outside", field(catalog, "loan_id"))
    with pytest.raises(ValueError, match="outside this saved data set"):
        save_column_definition(table, outside)

    save_column_definition(table, ColumnDefinition(1, "Loan ID", field(catalog, "loan_id")))
    with pytest.raises(ValueError, match="already mapped to source column 1"):
        save_column_definition(table, ColumnDefinition(2, "Other ID", field(catalog, "loan_id")))

    target = definition_path(SHA)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(ValueError, match="could not be read"):
        load_column_definitions(SHA)
