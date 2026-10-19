"""Exercise actual Dedupe, audit export, source preservation and owned-process cleanup."""

import argparse
import json
import os
import threading
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from tempfile import TemporaryDirectory

from openpyxl import Workbook  # type: ignore[import-untyped]

from loan_tape.column_definitions import (
    ColumnDefinition,
    ColumnRules,
    save_column_definition,
    snapshot_field,
)
from loan_tape.entities import PairLabel, review_relationships
from loan_tape.entity_matching import (
    entity_scope,
    population_guard,
    publish_bytes,
    read_population,
    train_entities,
)
from loan_tape.intake import IntakeStore
from loan_tape.packs import PackStore
from loan_tape.ranges import parse_range
from loan_tape.selection import SavedTable, SourceSelection, TableSelections, save_tables
from loan_tape.workspace_reset import reset_file_session


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    options = parser.parse_args()
    runtime = options.runtime_root.resolve()
    output = options.output.resolve() if options.output else None
    packs = Path(__file__).resolve().parents[1] / "packs"
    previous = Path.cwd()
    with TemporaryDirectory(prefix="entity-smoke-", dir=previous) as temporary:
        root = Path(temporary)
        os.chdir(root)
        try:
            source = root / "fictional.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.title = "Loans"
            sheet.append(["Borrower", "Address", "Borrower ID", "Loan ID", "Reporting date"])
            companies = (
                "Alpine",
                "Birch",
                "Caf\u00e9",
                "Delta",
                "Elm",
                "Falcon",
                "Granite",
                "\u6d77\u6e2f",
                "Iris",
                "Juniper",
                "Kestrel",
                "Linden",
            )
            for number, company in enumerate(companies):
                for ending in ("Holdings", "Hldgs"):
                    sheet.append(
                        [
                            f"{company} Industrial {ending}",
                            f"{number + 10} {company} Road",
                            f"000{number:019d}",
                            f"000{sheet.max_row:019d}",
                            "2026-09-30",
                        ]
                    )
            sheet.append(["N/A", "Missing", "N/A", "0000000000000000000999", "2026-09-30"])
            sheet.row_dimensions[2].hidden = True
            book.save(source)
            book.close()
            before = source.read_bytes()
            intake = IntakeStore(root / "inputs")
            record = intake.save_path(source)
            saved = Path(str(intake.describe(record)["saved_path"]))
            table = SavedTable(
                "1" * 32,
                "Fictional borrowers",
                SourceSelection(str(record["sha256"]), "Loans", parse_range("A1:E27"), 1),
            )
            save_tables(TableSelections(table.selection.workbook_sha256, (table,), table.id))
            store = PackStore(packs, root / ".artifacts/packs")
            store.activate("loan.text")
            catalog = store.catalog()
            for col, header, field in (
                (1, "Borrower", "borrower_name"),
                (2, "Address", "borrower_address"),
                (3, "Borrower ID", "borrower_identifier"),
            ):
                save_column_definition(
                    table,
                    ColumnDefinition(
                        col,
                        header,
                        snapshot_field(catalog, catalog.get_field("loan.text:" + field)),
                        rules=ColumnRules(missing_tokens=("N/A",)),
                    ),
                )
            population = read_population(saved, table, entity_scope(table), catalog, (1, 2, 3))
            assert population.to_dict()["rows"][0]["values"]["3"] == "0" * 22
            assert population.to_dict()["population"] == {
                "eligible": 24,
                "excluded": 2,
                "total": 26,
            }
            groups = [(2 + i * 2, 3 + i * 2) for i in range(12)]
            moment = datetime.now(UTC).isoformat()
            labels = tuple(
                PairLabel(
                    a, b, "match", "Synthetic reviewer", "Constructed same-borrower fixture", moment
                )
                for a, b in groups
            )
            labels += tuple(
                PairLabel(
                    a[0],
                    b[0],
                    "distinct",
                    "Synthetic reviewer",
                    "Constructed distinct-borrower fixture",
                    moment,
                )
                for a, b in combinations(groups, 2)
            )
            guard = population_guard(saved, table, store, population, (1, 2, 3), None)
            run, path = train_entities(population, labels, 0.5, True, guard, runtime_root=runtime)
            result = run.to_dict()
            assert {tuple(g["rows"]) for g in result["engine"]["groups"]} == set(groups)
            decisions = {g["id"]: "approve" for g in result["engine"]["groups"]}
            document = review_relationships(
                run, decisions, "Synthetic reviewer", "Reviewed constructed groups only", moment
            )
            assert json.loads(document)["loan_rows_modified"] == 0
            exported = publish_bytes(root / "relationships.json", document.encode(), guard)
            assert len(json.loads(exported.read_text())["relationships"]) == 12
            assert source.read_bytes() == before == saved.read_bytes()
            if output:
                publish_bytes(output, document.encode(), guard)
            existing = set((root / ".artifacts/entity-matching").iterdir())
            for mode in ("timeout", "cancel"):
                event = threading.Event()
                timer = threading.Timer(0.5, event.set) if mode == "cancel" else None
                if timer:
                    timer.start()
                try:
                    train_entities(
                        population,
                        labels,
                        0.5,
                        True,
                        guard,
                        runtime_root=runtime,
                        cancelled=event,
                        timeout=0.01 if mode == "timeout" else 300,
                    )
                except (ValueError, OSError) as error:
                    assert (
                        "timed out" in str(error)
                        if mode == "timeout"
                        else "cancel" in str(error).lower()
                    )
                else:
                    raise AssertionError(f"Expected {mode}")
                finally:
                    if timer:
                        timer.join()
                assert set((root / ".artifacts/entity-matching").iterdir()) == existing
            reset_file_session(intake, "e" * 32)
            assert not path.exists()
            assert not (root / ".artifacts/entity-matching").exists()
            assert exported.is_file() and source.read_bytes() == before
            print(
                "Entity smoke passed: actual Dedupe, 12 reviewed groups / 24 rows, two explicit exclusions, literal loan IDs retained in unchanged sources, JSON audit, timeout/cancellation cleanup and reset. Training-fixture evidence only; no independent accuracy claim."
            )
        finally:
            os.chdir(previous)


if __name__ == "__main__":
    main()
