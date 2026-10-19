"""Installed-wheel CSV/XML complete scopes, actual cleanup, replay and audit smoke."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from loan_tape.column_definitions import ColumnDefinition, snapshot_field
from loan_tape.intake import IntakeStore
from loan_tape.packs import PackStore
from loan_tape.source_adapters import (
    apply_review,
    create_csv_scope,
    create_xml_scope,
    export_audit,
    read_snapshot,
    review_source,
    save_mapping,
    scope_path,
)
from loan_tape.text_cleanup import TextCleanupSettings
from loan_tape.transformations import TransformationApproval, derived_text_values, replay_revision
from loan_tape.workspace_reset import reset_file_session
from loan_tape.xml_preview import read_xml_preview
from loan_tape.xml_selection import SavedXmlTable, XmlDataSet, XmlSelections, save_xml_selections


def main() -> int:
    prior = Path.cwd()
    with TemporaryDirectory(prefix="source-adapters-", dir=prior) as temporary:
        work = Path(temporary)
        os.chdir(work)
        try:
            store = PackStore(
                Path(__file__).resolve().parents[1] / "packs", work / ".artifacts/packs"
            )
            store.activate("loan.text")
            catalog = store.catalog()
            intake = IntakeStore(work / "inputs")
            for kind in ("csv", "xml"):
                source = work / ("fictional." + kind)
                source.write_text(
                    "Name,ID\nCaf\u00c3\u00a9,000000000000000000000001\nOther,000002\n"
                    if kind == "csv"
                    else "<r><loan><name>Caf\u00c3\u00a9</name><id>000000000000000000000001</id></loan>"
                    "<loan><name/><id>000002</id></loan></r>",
                    encoding="utf-8",
                )
                before = source.read_bytes()
                record = intake.save_path(source)
                saved = Path(str(intake.describe(record)["saved_path"]))
                if kind == "csv":
                    scope = create_csv_scope(saved, "CSV", "utf-8-sig", ",", True)
                    row = 2
                else:
                    preview = read_xml_preview(saved, None, None)
                    assert preview.source_sha256 and preview.selected_record_group
                    assert preview.record_count and preview.field_count
                    table = SavedXmlTable(
                        "d" * 32,
                        "XML",
                        preview.source_sha256,
                        preview.record_group_paths[0],
                        preview.selected_record_group,
                        preview.record_count,
                        preview.field_count,
                    )
                    save_xml_selections(
                        XmlSelections(
                            table.source_sha256,
                            (XmlDataSet(table.id, table.name, table.group_path),),
                            table.id,
                        )
                    )
                    scope = create_xml_scope(saved, table)
                    row = 1
                for column, field in ((1, "borrower_name"), (2, "borrower_identifier")):
                    scope = save_mapping(
                        saved,
                        scope,
                        ColumnDefinition(
                            column,
                            scope.metadata["headers"][column - 1],
                            snapshot_field(catalog, catalog.get_field("loan.text:" + field)),
                        ),
                        column,
                        store,
                    )
                settings = TextCleanupSettings()
                review = review_source(saved, scope, 1, settings, store)
                approval = TransformationApproval(
                    review.preview.id,
                    ((row, 1),),
                    "Wheel smoke",
                    "Synthetic source checked",
                    datetime.now(UTC).isoformat(),
                )
                revision, run = apply_review(saved, review, 1, settings, approval, store)
                assert derived_text_values(revision) == ((row, 1, "Caf\u00e9"),)
                assert (
                    replay_revision(read_snapshot(saved, scope, store), revision.document_json)
                    == revision
                )
                audit = export_audit(saved, scope, store, revision, work / (kind + "-audit.json"))
                assert json.loads(audit.read_text(encoding="utf-8"))["revision_id"] == revision.id
                assert source.read_bytes() == before == saved.read_bytes()
                reset_file_session(intake, "c" * 32)
                assert (
                    audit.exists()
                    and source.exists()
                    and not run.exists()
                    and not scope_path(scope.source_sha256).exists()
                )
        finally:
            os.chdir(prior)
    print(
        "Installed-wheel CSV/XML scopes, mappings, actual cleanup, replay, audit and reset passed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
