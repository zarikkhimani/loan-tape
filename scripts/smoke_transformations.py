"""Exercise the transformation foundation from the installed wheel using fictional data."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from openpyxl import Workbook  # type: ignore[import-untyped]

from loan_tape.column_definitions import ColumnDefinition, DefinitionScope, snapshot_field
from loan_tape.intake import IntakeStore
from loan_tape.pack_format import load_pack
from loan_tape.packs import Catalog
from loan_tape.ranges import parse_range
from loan_tape.selection import SavedTable, SourceSelection
from loan_tape.transformation_excel import (
    load_transformation,
    publish_transformation,
    read_transformation_snapshot,
)
from loan_tape.transformations import (
    CellProposal,
    TransformationApproval,
    TransformationOperation,
    derived_text_values,
    preview_transformation,
)
from loan_tape.workspace_reset import reset_file_session


def main() -> None:
    pack = load_pack(Path(__file__).resolve().parents[1] / "packs/example-loans")
    field = replace(
        pack.fields[0],
        id="borrower_name",
        data_type="text",
        entity="borrower",
        label="Borrower name",
        definition="Synthetic source-supplied borrower name.",
    )
    catalog = Catalog("synthetic", (replace(pack, fields=(*pack.fields, field)),))
    with TemporaryDirectory(prefix="transformation-smoke-", dir=Path.cwd()) as temporary:
        root = Path(temporary)
        source = root / "original.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Loans"
        sheet.append(["Borrower", "Loan ID"])
        sheet.append([" Acme ", "0001234567890123456789"])
        sheet.append(["Beta", "0002"])
        workbook.save(source)
        workbook.close()
        before = source.read_bytes()
        store = IntakeStore(root / "inputs")
        record = store.save_path(source)
        saved = Path(str(store.describe(record)["saved_path"]))
        table = SavedTable(
            "1" * 32,
            "Synthetic loans",
            SourceSelection(str(record["sha256"]), "Loans", parse_range("A1:B3"), 1),
        )
        definition = ColumnDefinition(
            1, "Borrower", snapshot_field(catalog, catalog.get_field("example.loans:borrower_name"))
        )
        scope = DefinitionScope(table.id, table.name, table.selection, (definition,))
        snapshot = read_transformation_snapshot(saved, table, scope, catalog)
        preview = preview_transformation(
            snapshot,
            TransformationOperation("synthetic-review", "1.0.0", "literal-proposal", "1.0.0"),
            (CellProposal(2, 1, " Acme ", "Acme", "reviewed-name", "Synthetic reviewed example."),),
        )
        approval = TransformationApproval(
            preview.id,
            ((2, 1),),
            "Smoke test",
            "Explicit fictional example.",
            datetime.now(UTC).isoformat(),
        )
        revision, path = publish_transformation(
            saved, table, scope, catalog, preview, approval, artifact_root=root / "artifacts"
        )
        assert load_transformation(path, saved, table, scope, catalog) == revision
        assert derived_text_values(revision) == ((2, 1, "Acme"),)
        assert saved.read_bytes() == before == source.read_bytes()
        assert preview.to_dict()["reconciliation"]["mapped_cell_count"] == 2
        reset_file_session(store, "2" * 32, root / "artifacts")
        assert not path.exists() and not saved.exists()
        assert source.read_bytes() == before
    print("Installed-wheel transformation evidence, approval, replay and session cleanup passed.")


if __name__ == "__main__":
    main()
