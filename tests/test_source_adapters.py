"""Actual CSV/XML reads, text engines, replay, publication and stale-input guards."""

import csv
import hashlib
import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from loan_tape import source_adapters, source_records
from loan_tape.column_definitions import ColumnDefinition, ColumnRules, snapshot_field
from loan_tape.inspection import InspectionError
from loan_tape.intake import IntakeStore
from loan_tape.packs import PackStore
from loan_tape.source_adapters import (
    AdapterScope,
    apply_review,
    create_csv_scope,
    create_xml_scope,
    export_audit,
    load_scopes,
    read_snapshot,
    review_source,
    save_mapping,
    save_scope,
    scope_path,
)
from loan_tape.source_records import read_csv_records, read_xml_records
from loan_tape.text_cleanup import TextCleanupSettings
from loan_tape.text_rule_types import ExactRule, ExactRulesSettings
from loan_tape.transformations import TransformationApproval, derived_text_values, replay_revision
from loan_tape.workspace_reset import reset_file_session
from loan_tape.xml_preview import read_xml_preview
from loan_tape.xml_selection import SavedXmlTable, XmlDataSet, XmlSelections, save_xml_selections

REPO = Path(__file__).parents[1]


def dictionary(work):
    store = PackStore(REPO / "packs", work / ".artifacts/packs")
    store.activate("loan.text")
    store.activate("example.loans")
    return store


def mapping(source, scope, store, column=1, field="loan.text:borrower_name"):
    catalog = store.catalog()
    definition = ColumnDefinition(
        column,
        scope.metadata["headers"][column - 1],
        snapshot_field(catalog, catalog.get_field(field)),
        rules=ColumnRules(missing_tokens=("N/A",)),
    )
    return save_mapping(source, scope, definition, column, store)


def xml_scope(source):
    preview = read_xml_preview(source, None, None)
    table = SavedXmlTable(
        "e" * 32,
        "Whole XML loans",
        preview.source_sha256,
        preview.record_group_paths[0],
        preview.selected_record_group,
        preview.record_count,
        preview.field_count,
    )
    save_xml_selections(
        XmlSelections(
            table.source_sha256, (XmlDataSet(table.id, table.name, table.group_path),), table.id
        )
    )
    return table, create_xml_scope(source, table)


def csv_scope(work, values=None):
    source = work / "loans.csv"
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Borrower", "Borrower", "ID"])
        for index, value in enumerate(values or ["CafÃ©", "0", "N/A", "", " \t", "=SUM(A1:A2)"]):
            writer.writerow([value, "Other", "000" + str(index).zfill(25)])
    scope = create_csv_scope(source, "CSV loans", "utf-8-sig", ",", True)
    return source, scope


@pytest.fixture
def work(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def approve(review, keys=((2, 1),)):
    return TransformationApproval(
        review.preview.id,
        keys,
        "Synthetic reviewer",
        "Checked source",
        datetime.now(UTC).isoformat(),
    )


def test_csv_complete_evidence_and_replay(work):
    source, scope = csv_scope(work, ["CafÃ©"] * 61 + ["A\r\nB", "N/A", "0", "", " \t"])
    before = source.read_bytes()
    store = dictionary(work)
    for column, field in (
        (1, "loan.text:borrower_name"),
        (2, "loan.text:facility_name"),
        (3, "loan.text:borrower_identifier"),
    ):
        scope = mapping(source, scope, store, column, field)
    snapshot = read_snapshot(source, scope, store)
    data = snapshot.to_dict()
    assert data["dataset"]["format"] == "csv" and "selection" not in data["dataset"]
    assert data["fields"][1]["header"]["occurrence"] == 2
    assert data["population"] == {
        "first_row": 2,
        "row_count": 66,
        "mapped_cell_count": 198,
        "selected_column_count": 3,
        "unmapped_column_count": 0,
    }
    multiline = next(item for item in data["cells"] if (item["row"], item["column"]) == (63, 1))
    assert multiline["evidence"]["raw"] == "A\r\nB"
    assert multiline["evidence"]["source"]["first_line"] == 63
    assert multiline["evidence"]["source"]["last_line"] == 64
    assert data["cells"][2]["evidence"]["raw"] == "0" * 28
    settings = TextCleanupSettings()
    review = review_source(source, scope, 1, settings, store)
    counts = review.preview.to_dict()["reconciliation"]
    assert counts["changed"] == 61 and counts["mapped_cell_count"] == 198
    revision, path = apply_review(
        source, review, 1, settings, approve(review, ((2, 1), (62, 1))), store
    )
    assert derived_text_values(revision) == ((2, 1, "Café"), (62, 1, "Café"))
    assert replay_revision(snapshot, revision.document_json) == revision
    assert json.loads(path.read_text())["revision_id"] == revision.id
    exact = ExactRulesSettings((ExactRule("Café", "Cafe Holdings"),))
    second = review_source(source, scope, 1, exact, store, parent=revision)
    final, _ = apply_review(source, second, 1, exact, approve(second), store, parent=revision)
    assert (
        dict(((row, col), text) for row, col, text in derived_text_values(final))[(2, 1)]
        == "Cafe Holdings"
    )
    assert len(final.to_dict()["steps"]) == 2
    export = export_audit(source, scope, store, final, work / "audit.json")
    assert (
        json.loads(export.read_text())["revision"]["snapshot"]["cells"][0]["evidence"]["raw"]
        == "CafÃ©"
    )
    with pytest.raises(ValueError, match="existing"):
        export_audit(source, scope, store, final, export)
    assert source.read_bytes() == before


def test_csv_empty_absent_ragged_headerless_and_no_coercion(work):
    source = work / "raw.csv"
    source.write_bytes(b'"",00000000000000000000001,0\r\nN/A\r\n\r\n"=1+1", ,0.00\r\n')
    records = read_csv_records(source, "utf-8-sig", ",", False)
    assert [cell["state"] for cell in records.rows[0]] == ["empty_text", "text", "text"]
    assert [cell["state"] for cell in records.rows[1]] == ["text", "absent", "absent"]
    assert all(cell["state"] == "absent" for cell in records.rows[2])
    assert records.rows[3][0]["evidence"]["raw"] == "=1+1"
    assert records.rows[3][1]["state"] == "whitespace_text"
    assert records.rows[3][2]["evidence"]["raw"] == "0.00"
    assert json.loads(records.metadata_json)["first_data_record"] == 1


@pytest.mark.parametrize(
    "encoding,delimiter",
    [("utf-8-sig", ","), ("cp1252", ";"), ("utf-16", "\t"), ("utf-8-sig", "|")],
)
def test_csv_conventions_literal_unicode_and_quotes(work, encoding, delimiter):
    source = work / "data.csv"
    with source.open("w", encoding=encoding, newline="") as stream:
        csv.writer(stream, delimiter=delimiter).writerows([["Name", "ID"], ['Café "A"', "00001"]])
    scope = create_csv_scope(source, "Reviewed conventions", encoding, delimiter, True)
    assert load_scopes(scope.source_sha256) == (scope,)
    assert (
        read_csv_records(source, encoding, delimiter, True).rows[1][0]["evidence"]["raw"]
        == 'Café "A"'
    )


@pytest.mark.parametrize(
    "content,error",
    [
        (b'name,id\nA,1\n"broken', "structure"),
        (b"name,id\nA,1\n\xff,2", "encoding"),
        (b"name\nA,1\n", "header"),
        (b"name,id\n", "data records"),
        (b"", "data records"),
    ],
)
def test_csv_failure_never_saves_partial_scope(work, content, error):
    source = work / "bad.csv"
    source.write_bytes(content)
    with pytest.raises(InspectionError, match=error):
        create_csv_scope(source, "Bad", "utf-8-sig", ",", True)
    assert not (work / ".artifacts/source-adapters").exists()
    assert source.read_bytes() == content


def test_xml_full_group_namespace_missingness_and_actual_cleanup(work):
    source = work / "loans.xml"
    source.write_text(
        '<r xmlns:a="urn:one" xmlns:b="urn:two" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<loan id="00001"><a:name>CafÃ©</a:name><b:name>Other</b:name></loan>'
        '<loan id=""><a:name/><b:name xsi:nil="true"/></loan>'
        "<loan><a:name> </a:name><b:name>0</b:name></loan>"
        "<loan><a:name>N/A</a:name><late>last</late></loan></r>",
        encoding="utf-8",
    )
    before = source.read_bytes()
    table, scope = xml_scope(source)
    store = dictionary(work)
    labels = scope.metadata["headers"]
    first_name = next(i for i, text in enumerate(labels, 1) if text.endswith(":name"))
    second_name = next(
        i for i, text in enumerate(labels, 1) if text.endswith(":name") and i != first_name
    )
    for column in (1, first_name, second_name):
        scope = mapping(
            source,
            scope,
            store,
            column,
            "loan.text:borrower_identifier" if column == 1 else "loan.text:borrower_name",
        )
    records = read_xml_records(source, table)
    assert records.rows[1][0]["state"] == "empty_text"
    assert records.rows[2][0]["state"] == "absent"
    assert records.rows[1][first_name - 1]["state"] == "empty_element"
    assert records.rows[1][second_name - 1]["state"] == "nil"
    assert records.rows[0][-1]["state"] == "absent"
    assert set(scope.metadata["options"]["namespaces"]) >= {"urn:one", "urn:two"}
    settings = TextCleanupSettings()
    review = review_source(source, scope, first_name, settings, store)
    assert review.preview.to_dict()["reconciliation"]["row_count"] == 4
    assert any(cell["state"] == "missing_token" for cell in review.snapshot.to_dict()["cells"])
    revision, _ = apply_review(
        source, review, first_name, settings, approve(review, ((1, first_name),)), store
    )
    assert derived_text_values(revision) == ((1, first_name, "Café"),)
    assert replay_revision(read_snapshot(source, scope, store), revision.document_json) == revision
    cell = review.snapshot.to_dict()["cells"][1]
    assert cell["evidence"]["source"]["node_path"].endswith(":name[1]")
    assert source.read_bytes() == before


@pytest.mark.parametrize(
    "change", ["bytes", "mapping", "dictionary", "approval", "proposal", "cancel"]
)
def test_stale_inputs_and_tampering_publish_nothing(work, change):
    source, scope = csv_scope(work)
    store = dictionary(work)
    scope = mapping(source, scope, store)
    settings = TextCleanupSettings()
    review = review_source(source, scope, 1, settings, store)
    approval = approve(review)
    event = Event()
    if change == "bytes":
        source.write_bytes(source.read_bytes() + b"Another,Other,0000\r\n")
    elif change == "mapping":
        save_mapping(source, scope, None, 1, store)
    elif change == "dictionary":
        store.deactivate("loan.text")
    elif change == "approval":
        approval = replace(approval, preview_id="f" * 64)
    elif change == "proposal":
        data = review.preview.to_dict()
        data["decisions"][0]["proposed_text"] = "Invented"
        review = replace(review, preview=replace(review.preview, document_json=json.dumps(data)))
    else:
        event.set()
    with pytest.raises(ValueError):
        apply_review(source, review, 1, settings, approval, store, cancelled=event)
    assert not list((work / ".artifacts/transformations").glob("*.json"))


def test_bounds_and_oversize_tokens_are_explicit(work, monkeypatch):
    source, scope = csv_scope(work, ["x" * 17000])
    store = dictionary(work)
    scope = mapping(source, scope, store)
    review = review_source(source, scope, 1, TextCleanupSettings(), store)
    assert review.preview.to_dict()["reconciliation"]["unresolved"] == 1
    assert review.snapshot.to_dict()["cells"][0]["evidence"]["raw"]["retained"] is False
    monkeypatch.setattr(source_records, "MAX_CELLS", 2)
    with pytest.raises(InspectionError, match="limit"):
        read_csv_records(source, "utf-8-sig", ",", True)


def test_atomic_publication_race_postguard_rollback_and_settings_lock(work, monkeypatch):
    source, scope = csv_scope(work)
    store = dictionary(work)
    scope = mapping(source, scope, store)
    settings = TextCleanupSettings()
    review = review_source(source, scope, 1, settings, store)
    revision, _ = apply_review(source, review, 1, settings, approve(review), store)
    target = work / "race.json"
    actual_link = os.link

    def race(staging, destination):
        Path(destination).write_bytes(b"competing file")
        actual_link(staging, destination)

    with monkeypatch.context() as patch:
        patch.setattr(source_adapters.os, "link", race)
        with pytest.raises(FileExistsError):
            export_audit(source, scope, store, revision, target)
    assert target.read_bytes() == b"competing file"
    target = work / "rollback.json"
    count = 0

    def guard():
        nonlocal count
        count += 1
        if count == 2:
            raise ValueError("stale at final guard")

    with pytest.raises(ValueError, match="stale"):
        source_adapters.publish_audit(target, revision, guard)
    assert not target.exists() and not list(work.glob("*.tmp"))
    with pytest.raises(ValueError, match="changed"):
        save_scope(scope)
    assert not scope_path(scope.source_sha256).with_suffix(".lock").exists()
    assert load_scopes(scope.source_sha256) == (scope,)


def test_schema_corruption_and_no_silent_fallback(work):
    source, scope = csv_scope(work)
    path = scope_path(scope.source_sha256)
    path.write_text('{"format_version":1,"format_version":1}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_scopes(scope.source_sha256)
    with pytest.raises(ValueError):
        AdapterScope(scope.id, scope.name, scope.metadata_json, ("not a mapping",))
    with pytest.raises(ValueError, match="explicit"):
        read_csv_records(source, "Automatic", ",", True)


def test_normal_exit_removes_adapter_scopes_and_runs_but_preserves_audits(work):
    source, _ = csv_scope(work)
    original = source.read_bytes()
    intake = IntakeStore(work / "inputs")
    record = intake.save_path(source)
    saved = Path(intake.describe(record)["saved_path"])
    scope = create_csv_scope(saved, "Working copy", "utf-8-sig", ",", True)
    store = dictionary(work)
    scope = mapping(saved, scope, store)
    review = review_source(saved, scope, 1, TextCleanupSettings(), store)
    revision, run = apply_review(saved, review, 1, TextCleanupSettings(), approve(review), store)
    audit = export_audit(saved, scope, store, revision, work / "kept.json")
    reset_file_session(intake, "a" * 32)
    assert not scope_path(scope.source_sha256).exists() and not run.exists() and not saved.exists()
    assert audit.exists() and source.read_bytes() == original and store.catalog().fields


def test_xml_changed_saved_group_and_unsafe_content_rejected(work):
    source = work / "loans.xml"
    source.write_text("<r><loan>A</loan><loan>B</loan></r>", encoding="utf-8")
    table, scope = xml_scope(source)
    save_xml_selections(XmlSelections(table.source_sha256))
    with pytest.raises(ValueError, match="removed"):
        read_xml_records(source, table)
    for content in (
        '<!DOCTYPE r [<!ENTITY a "secret">]><r>&a;</r>',
        "<r><loan>A</loan><loan>B</loan>",
    ):
        source.write_text(content, encoding="utf-8")
        with pytest.raises(InspectionError):
            read_xml_preview(source, None, None)
    assert scope.source_sha256 == hashlib.sha256(b"<r><loan>A</loan><loan>B</loan></r>").hexdigest()


def test_category_rules_missing_tokens_and_ineligible_identifiers(work):
    source, scope = csv_scope(work, ["current", "N/A", "0"])
    store = dictionary(work)
    scope = mapping(source, scope, store, 1, "example.loans:status")
    scope = mapping(source, scope, store, 3, "loan.text:borrower_identifier")
    settings = ExactRulesSettings((ExactRule("current", "CURRENT"),))
    review = review_source(source, scope, 1, settings, store)
    assert review.preview.to_dict()["reconciliation"]["changed"] == 1
    revision, _ = apply_review(source, review, 1, settings, approve(review), store)
    assert derived_text_values(revision) == ((2, 1, "CURRENT"),)
    for from_text, to_text in (("current", "Unknown"), ("N/A", "CURRENT")):
        with pytest.raises(ValueError):
            review_source(
                source, scope, 1, ExactRulesSettings((ExactRule(from_text, to_text),)), store
            )
    with pytest.raises(ValueError, match="text column"):
        review_source(source, scope, 3, TextCleanupSettings(), store)


def test_full_csv_width_past_preview_and_source_change_during_read(work, monkeypatch):
    source = work / "wide.csv"
    source.write_text(
        ",".join("field" for _ in range(12)) + "\n" + ",".join(str(i) for i in range(12)) + "\n",
        encoding="utf-8",
    )
    records = read_csv_records(source, "utf-8-sig", ",", True)
    assert len(records.rows[1]) == 12 and records.rows[1][11]["evidence"]["raw"] == "11"
    digest = source_records._digest
    calls = 0

    def mutate(path, event):
        nonlocal calls
        calls += 1
        if calls == 2:
            path.write_bytes(path.read_bytes() + b"late\n")
        return digest(path, event)

    monkeypatch.setattr(source_records, "_digest", mutate)
    with pytest.raises(InspectionError, match="changed"):
        create_csv_scope(source, "Changed", "utf-8-sig", ",", True)
    assert not (work / ".artifacts/source-adapters").exists()


def test_xml_adapter_rejects_repeated_and_mixed_children(work):
    for inside in ("before<name>A</name>after", "<name>A</name><name>B</name>"):
        source = work / "complex.xml"
        source.write_text(
            "<r><loan>" + inside + "</loan><loan><name>C</name></loan></r>", encoding="utf-8"
        )
        identity = hashlib.sha256(source.read_bytes()).hexdigest()
        table = SavedXmlTable("d" * 32, "Loans", identity, ("r", "loan"), "/r/loan", 2, 1)
        save_xml_selections(
            XmlSelections(identity, (XmlDataSet(table.id, table.name, table.group_path),), table.id)
        )
        with pytest.raises(InspectionError, match="Mixed|Repeated"):
            create_xml_scope(source, table)
        assert not scope_path(identity).exists()


def test_failed_settings_publication_retains_previous_and_cleans_lock(work):
    source, scope = csv_scope(work)
    before = scope_path(scope.source_sha256).read_bytes()

    def failed_guard():
        raise ValueError("Source changed at staging")

    with pytest.raises(ValueError, match="staging"):
        save_scope(replace(scope, name="Changed name"), scope, guard=failed_guard)
    assert scope_path(scope.source_sha256).read_bytes() == before
    assert not list(scope_path(scope.source_sha256).parent.glob("*.tmp"))
    assert not scope_path(scope.source_sha256).with_suffix(".lock").exists()


@pytest.mark.parametrize("operation", ["settings", "audit"])
def test_staging_collision_preserves_other_writers_files(work, monkeypatch, operation):
    source, scope = csv_scope(work)
    store = dictionary(work)
    scope = mapping(source, scope, store)
    settings = scope_path(scope.source_sha256)
    before = settings.read_bytes()
    identity = SimpleNamespace(hex="a" * 32)
    monkeypatch.setattr(source_adapters, "uuid4", lambda: identity)
    target = work / "review.json"
    staging = (
        settings.with_suffix("." + identity.hex + ".tmp")
        if operation == "settings"
        else target.with_name(scope.source_sha256 + "-" + identity.hex + ".tmp")
    )
    staging.write_bytes(b"another writer's evidence")

    with pytest.raises(FileExistsError):
        if operation == "settings":
            save_scope(replace(scope, name="New name"), scope)
        else:
            review = review_source(source, scope, 1, TextCleanupSettings(), store)
            revision = source_adapters.apply_transformation(
                review.snapshot, review.preview, approve(review)
            )
            export_audit(source, scope, store, revision, target)

    assert staging.read_bytes() == b"another writer's evidence"
    assert settings.read_bytes() == before
    assert not settings.with_suffix(".lock").exists()
    assert not target.exists()
