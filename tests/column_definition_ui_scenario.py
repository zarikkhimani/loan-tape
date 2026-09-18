"""Isolated native smoke case for the saved column-definition editor."""

import os
import sys
from pathlib import Path

from loan_tape.column_definition_ui import ColumnDefinitionWindow
from loan_tape.column_definitions import definition_for_column
from loan_tape.pack_format import load_pack
from loan_tape.packs import Catalog
from loan_tape.ranges import parse_range
from loan_tape.selection import SavedTable, SourceSelection
from loan_tape.ui import create_root


class CatalogStore:
    def __init__(self, catalog: Catalog) -> None:
        self.value = catalog

    def catalog(self, profile: str = "default") -> Catalog:
        assert profile == "default"
        return self.value


def choose(window: ColumnDefinitionWindow, field_id: str) -> None:
    label = next(
        label
        for label, item in window.fields_by_choice.items()
        if item is not None and item.id == field_id
    )
    window.meaning.set(label)
    window._select_field()


def run(work: Path) -> None:
    os.chdir(work)
    pack = load_pack(Path(__file__).parents[1] / "packs" / "example-loans")
    store = CatalogStore(Catalog("default", (pack,)))
    table = SavedTable(
        "1" * 32,
        "Loans",
        SourceSelection("a" * 64, "Tape", parse_range("A1:C10"), 1),
    )
    root = create_root()
    root.withdraw()
    callbacks = []
    try:
        editor = ColumnDefinitionWindow(
            root, table, 1, "Loan ID", store, lambda: callbacks.append("saved")
        )
        editor.window.withdraw()
        assert not editor.meaning.get()
        choose(editor, "example.loans:loan_id")
        assert "identifier" in editor.type_summary.get()
        editor.unique.set("Require unique values")
        editor.save_button.invoke()
        assert definition_for_column(table, 1).rules.unique is True
        editor.close()

        editor = ColumnDefinitionWindow(root, table, 2, "Balance", store)
        editor.window.withdraw()
        choose(editor, "example.loans:principal_balance")
        assert editor.source_unit.get() == "currency units"
        editor.save_button.invoke()
        assert "requires an explicit" in editor.status.get()
        editor.currency.set("usd")
        editor.save_button.invoke()
        saved = definition_for_column(table, 2)
        assert saved.currency == "USD" and saved.source_unit == "currency units"
        editor.close()

        editor = ColumnDefinitionWindow(root, table, 3, "Maturity", store)
        editor.window.withdraw()
        choose(editor, "example.loans:maturity_date")
        assert editor.date_format.get() == "YYYY-MM-DD"
        editor.save_button.invoke()
        assert definition_for_column(table, 3).date_formats == ("YYYY-MM-DD",)
        editor.close()

        reopened = ColumnDefinitionWindow(root, table, 2, "Balance", store)
        reopened.window.withdraw()
        assert reopened.currency.get() == "USD"
        assert "Loan principal balance" in reopened.meaning.get()
        assert reopened.remove_button.instate(["!disabled"])
        reopened.close()
        assert callbacks == ["saved"]
    finally:
        root.destroy()


if __name__ == "__main__":
    run(Path(sys.argv[1]))
