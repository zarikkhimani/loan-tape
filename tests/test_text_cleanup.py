import json
from dataclasses import replace
from datetime import UTC, datetime
from threading import Event

import pytest
from text_cleanup_support import prepare

from loan_tape.column_definitions import ColumnRules, definition_for_column, save_column_definition
from loan_tape.text_cleanup import (
    TextCleanupSettings,
    apply_excel_text,
    cleanup_scope,
    preview_text_cleanup,
    review_excel_text,
)
from loan_tape.transformations import (
    TransformationApproval,
    apply_transformation,
    derived_text_values,
)
from loan_tape.workbook_index import ScanCancelled


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return prepare(tmp_path)


def approve(review, cells=((2, 1),)):
    return TransformationApproval(
        review.preview.id,
        cells,
        "Test reviewer",
        "Reviewed against fictional source.",
        datetime.now(UTC).isoformat(),
    )


def test_real_engine_preserves_conventions_and_records_every_setting(context):
    original, source, _, table, store = context
    before = original.read_bytes()
    review = review_excel_text(source, table, 1, TextCleanupSettings(), store)
    decisions = {
        (item["row"], item["column"]): item for item in review.preview.to_dict()["decisions"]
    }
    assert decisions[2, 1]["proposed_text"] == "Café Holdings"
    assert decisions[3, 1]["proposed_text"] == " Acme "
    assert decisions[4, 1]["proposed_text"] == "e\u0301"
    assert decisions[12, 1]["outcome"] == "unresolved"
    assert all(decisions[row, 2]["outcome"] == "ineligible" for row in range(2, 14))
    parameters = json.loads(review.preview.to_dict()["operation"]["parameters_json"])
    assert parameters["settings"] == TextCleanupSettings().config()._asdict()
    assert len(parameters["settings"]) == 16
    assert parameters["settings"]["restore_byte_a0"] is False
    assert parameters["settings"]["replace_lossy_sequences"] is False
    assert source.read_bytes() == before == original.read_bytes()


def test_unicode_normalization_is_explicit_and_settings_invalidate_review(context):
    _, source, _, table, store = context
    settings = TextCleanupSettings(False, "NFC")
    review = review_excel_text(source, table, 1, settings, store)
    rows = review.preview.to_dict()["decisions"]
    assert next(d for d in rows if (d["row"], d["column"]) == (4, 1))["proposed_text"] == "é"
    assert next(d for d in rows if (d["row"], d["column"]) == (2, 1))["outcome"] == "unchanged"
    with pytest.raises(ValueError, match="changed"):
        apply_excel_text(
            source, table, 1, TextCleanupSettings(), store, review, approve(review, ((4, 1),))
        )


def test_punctuation_html_spaces_and_line_breaks_stay_literal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    values = [
        "“Acme” &amp; Co\r\nUnit 1",
        "ﬁ fullwidth Ａ",
        "0012345678901234567890",
        "Name\u00a0suffix",
    ]
    _, source, _, table, store = prepare(tmp_path, values)
    review = review_excel_text(source, table, 1, TextCleanupSettings(), store)
    assert review.preview.to_dict()["reconciliation"]["changed"] == 0
    assert [p["proposed_text"] for p in review.preview.to_dict()["proposals"]] == values


def test_application_uses_real_engine_preserves_sources_and_parent(context):
    original, source, _, table, store = context
    before = source.read_bytes()
    review = review_excel_text(source, table, 1, TextCleanupSettings(), store)
    parent, path = apply_excel_text(
        source, table, 1, TextCleanupSettings(), store, review, approve(review)
    )
    assert path.is_file() and derived_text_values(parent) == ((2, 1, "Café Holdings"),)
    next_review = review_excel_text(
        source, table, 1, TextCleanupSettings(True, "NFC"), store, parent=parent
    )
    assert next_review.preview.to_dict()["reconciliation"]["changed"] == 1
    child, _ = apply_excel_text(
        source,
        table,
        1,
        TextCleanupSettings(True, "NFC"),
        store,
        next_review,
        approve(next_review, ((4, 1),)),
        parent=parent,
    )
    assert derived_text_values(child) == ((2, 1, "Café Holdings"), (4, 1, "é"))
    assert source.read_bytes() == before == original.read_bytes()


@pytest.mark.parametrize("changed", ["dictionary", "mapping", "source"])
def test_changed_inputs_cannot_publish(context, changed, tmp_path):
    _, source, _, table, store = context
    review = review_excel_text(source, table, 1, TextCleanupSettings(), store)
    if changed == "dictionary":
        store.deactivate("loan.text")
    elif changed == "mapping":
        definition = definition_for_column(table, 1)
        save_column_definition(
            table, replace(definition, rules=ColumnRules(missing_tokens=("N/A", "UNKNOWN")))
        )
    else:
        source.write_bytes(source.read_bytes() + b"changed")
    with pytest.raises(ValueError):
        apply_excel_text(source, table, 1, TextCleanupSettings(), store, review, approve(review))
    assert not list((tmp_path / ".artifacts/transformations").glob("*.json"))


def test_metadata_change_during_staging_blocks_publication(context, monkeypatch, tmp_path):
    import loan_tape.transformation_excel as adapter

    _, source, _, table, store = context
    review = review_excel_text(source, table, 1, TextCleanupSettings(), store)
    original = adapter.os.fsync

    def changed(fd):
        original(fd)
        store.deactivate("loan.text")

    monkeypatch.setattr(adapter.os, "fsync", changed)
    with pytest.raises(ValueError, match="dictionary"):
        apply_excel_text(source, table, 1, TextCleanupSettings(), store, review, approve(review))
    assert list((tmp_path / ".artifacts/transformations").iterdir()) == []


def test_engine_failure_unavailable_version_and_cancellation_are_explicit(context, monkeypatch):
    import loan_tape.text_cleanup as engine

    _, source, _, table, store = context
    review = review_excel_text(source, table, 1, TextCleanupSettings(), store)

    def failed(*_):
        raise RuntimeError("Synthetic engine failure")

    with monkeypatch.context() as local:
        local.setattr(engine.ftfy, "fix_and_explain", failed)
        failed_review = review_excel_text(source, table, 1, TextCleanupSettings(), store)
        assert failed_review.preview.to_dict()["reconciliation"]["failed"] > 0
        with pytest.raises(ValueError, match="Failed transformation"):
            apply_transformation(
                failed_review.snapshot, failed_review.preview, approve(failed_review, ())
            )
    with monkeypatch.context() as local:
        local.setattr(engine, "version", lambda _: "unsupported")
        with pytest.raises(ValueError, match="reviewed ftfy"):
            preview_text_cleanup(review.snapshot, 1, TextCleanupSettings())
    cancelled = Event()
    cancelled.set()
    with pytest.raises(ScanCancelled):
        preview_text_cleanup(review.snapshot, 1, TextCleanupSettings(), cancelled=cancelled)


def test_mapping_and_settings_require_explicit_eligible_choices(context):
    _, _, _, table, _ = context
    with pytest.raises(ValueError, match="excluded"):
        cleanup_scope(table, 2)
    with pytest.raises(ValueError, match="at least one"):
        TextCleanupSettings(False)
    with pytest.raises(ValueError):
        TextCleanupSettings(True, "NFKC")
