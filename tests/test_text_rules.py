"""Actual spelling comparisons, literal semantics, complete review and replay guards."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from threading import Event

import pytest
from text_cleanup_support import prepare

from loan_tape.column_definitions import (
    ColumnRules,
    definition_for_column,
    save_column_definition,
    snapshot_field,
)
from loan_tape.text_cleanup import (
    TextCleanupSettings,
    apply_excel_text,
    review_excel_text,
    suggest_excel_text,
)
from loan_tape.text_rule_types import ExactRule, ExactRulesSettings, SpellingEvidence
from loan_tape.text_rules import (
    SpellingSettings,
    preview_exact_rules,
    rule_operation,
    suggest_spellings,
)
from loan_tape.transformation_excel import load_transformation
from loan_tape.transformations import (
    CellProposal,
    TransformationApproval,
    derived_text_values,
    preview_transformation,
)
from loan_tape.workbook_index import ScanCancelled


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return prepare(
        tmp_path, ["Acme Hldings", "Acme Holdings", "Acme Holdings", " Acme Holdings ", "Other"]
    )


def approve(review, cells=((2, 1),)):
    return TransformationApproval(
        review.preview.id,
        cells,
        "Synthetic reviewer",
        "Checked fictional values.",
        datetime.now(UTC).isoformat(),
    )


def category(table, store):
    definition = definition_for_column(table, 1)
    catalog = store.catalog()
    save_column_definition(
        table,
        replace(
            definition, field=snapshot_field(catalog, catalog.get_field("example.loans:status"))
        ),
    )


def test_actual_similarity_is_deterministic_and_never_changes_data(context, tmp_path):
    original, source, _, table, store = context
    before = source.read_bytes()
    report = suggest_excel_text(source, table, 1, "Acme Hldings", SpellingSettings(85), store)
    assert report == suggest_excel_text(
        source, table, 1, "Acme Hldings", SpellingSettings(85), store
    )
    assert report.eligible_count == 5 and report.distinct_count == 4
    assert report.candidates[0].text == "Acme Holdings"
    assert report.candidates[0].count == 2 and report.candidates[0].first_row == 3
    assert 90 < report.candidates[0].score < 100
    assert [c.text for c in report.candidates] == ["Acme Holdings", " Acme Holdings "]
    assert source.read_bytes() == before == original.read_bytes()
    assert not list((tmp_path / ".artifacts/transformations").glob("*"))
    assert (
        suggest_excel_text(
            source, table, 1, "Acme Hldings", SpellingSettings(100), store
        ).candidates
        == ()
    )
    with pytest.raises(ValueError, match="not an eligible current value"):
        suggest_excel_text(source, table, 1, "acme hldings", SpellingSettings(), store)


def test_candidate_provenance_explicit_subset_and_saved_replay(context):
    original, source, _, table, store = context
    before = source.read_bytes()
    report = suggest_excel_text(source, table, 1, "Acme Holdings", SpellingSettings(0), store)
    index = next(i for i, c in enumerate(report.candidates) if c.text == "Other")
    rule = report.rule(index)
    assert rule.suggestion.scorer == "fuzz_cpp.ratio" and rule.suggestion.engine_version == "3.14.6"
    assert (
        rule.suggestion.snapshot_id == report.snapshot_id
        and rule.suggestion.corpus_id == report.corpus_id
    )
    settings = ExactRulesSettings((rule,))
    review = review_excel_text(source, table, 1, settings, store)
    assert review.preview.to_dict()["reconciliation"]["changed"] == 2
    parameters = json.loads(review.preview.to_dict()["operation"]["parameters_json"])
    assert parameters["rules"][0]["suggestion"]["threshold"] == 0
    revision, path = apply_excel_text(
        source, table, 1, settings, store, review, approve(review, ((3, 1),))
    )
    assert derived_text_values(revision) == ((3, 1, "Other"),)
    assert load_transformation(path, source, table, review.scope, store.catalog()) == revision
    assert source.read_bytes() == before == original.read_bytes()


def test_compare_normalization_does_not_normalize_rule_keys(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _, source, _, table, store = prepare(tmp_path, ["é", "E\u0301", " é ", "É"])
    literal = suggest_excel_text(source, table, 1, "é", SpellingSettings(100), store)
    assert not literal.candidates
    normalized = suggest_excel_text(
        source, table, 1, "é", SpellingSettings(100, "nfc-casefold"), store
    )
    assert [(c.text, c.score) for c in normalized.candidates] == [("E\u0301", 100.0), ("É", 100.0)]
    rule = normalized.rule(0)
    assert (rule.source, rule.target) == ("é", "E\u0301")
    assert rule.suggestion.comparison == "nfc-casefold"
    review = review_excel_text(source, table, 1, ExactRulesSettings((rule,)), store)
    assert [
        (p["row"], p["input_text"], p["proposed_text"])
        for p in review.preview.to_dict()["proposals"]
    ] == [(2, "é", "E\u0301")]


def test_exact_literals_simultaneous_mapping_and_all_cells(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    values = [
        " Acme ",
        "Acme",
        "acme",
        "ACME",
        "é",
        "e\u0301",
        "A",
        "B",
        "A\r\nB",
        "N/A",
        "",
        " \t",
        0,
        "=1+1",
        "#N/A",
        False,
    ]
    _, source, _, table, store = prepare(tmp_path, values)
    settings = ExactRulesSettings(
        (
            ExactRule(" Acme ", " Acme Ltd "),
            ExactRule("é", "É"),
            ExactRule("A", "B"),
            ExactRule("B", "C"),
            ExactRule("A\r\nB", "=literal replacement"),
        )
    )
    review = review_excel_text(source, table, 1, settings, store)
    data = review.preview.to_dict()
    assert [(p["row"], p["proposed_text"]) for p in data["proposals"]] == [
        (2, " Acme Ltd "),
        (6, "É"),
        (8, "B"),
        (9, "C"),
        (10, "=literal replacement"),
    ]
    totals = data["reconciliation"]
    assert totals["row_count"] == 17 and totals["mapped_cell_count"] == 34
    assert totals["changed"] == 5
    decisions = {(d["row"], d["column"]): d for d in data["decisions"]}
    assert all(decisions[r, 2]["outcome"] == "ineligible" for r in range(2, 19))
    assert all(decisions[r, 1]["outcome"] == "ineligible" for r in range(11, 19))
    assert all(decisions[r, 1]["outcome"] == "unchanged" for r in (3, 4, 5, 7))


def test_rules_and_ftfy_consume_only_approved_parent_values(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    original, source, _, table, store = prepare(
        tmp_path, ["CafÃ© Holdings", "Café Group", "e\u0301"]
    )
    before = source.read_bytes()
    repair = review_excel_text(source, table, 1, TextCleanupSettings(), store)
    parent, _ = apply_excel_text(
        source, table, 1, TextCleanupSettings(), store, repair, approve(repair)
    )
    report = suggest_excel_text(
        source, table, 1, "Café Holdings", SpellingSettings(0), store, parent=parent
    )
    assert report.parent_id == parent.id
    assert "CafÃ© Holdings" not in [c.text for c in report.candidates]
    settings = ExactRulesSettings((ExactRule("Café Holdings", "Café Group"),))
    rules = review_excel_text(source, table, 1, settings, store, parent=parent)
    child, path = apply_excel_text(
        source, table, 1, settings, store, rules, approve(rules), parent=parent
    )
    nfc = TextCleanupSettings(False, "NFC")
    last = review_excel_text(source, table, 1, nfc, store, parent=child)
    final, _ = apply_excel_text(
        source, table, 1, nfc, store, last, approve(last, ((4, 1),)), parent=child
    )
    assert derived_text_values(parent) == ((2, 1, "Café Holdings"),)
    assert derived_text_values(final) == ((2, 1, "Café Group"), (4, 1, "é"))
    assert load_transformation(path, source, table, rules.scope, store.catalog()) == child
    assert len(final.to_dict()["steps"]) == 3
    assert before == source.read_bytes() == original.read_bytes()


@pytest.mark.parametrize(
    "rules",
    [
        (ExactRule("A", "B"), ExactRule("A", "B")),
        (ExactRule("A", "B"), ExactRule("A", "C")),
    ],
)
def test_duplicate_and_conflicting_literal_keys_rejected(rules):
    with pytest.raises(ValueError, match="Duplicate or conflicting"):
        ExactRulesSettings(rules)


@pytest.mark.parametrize(
    "source,target",
    [("", "A"), (" \t", "A"), ("A", ""), ("A", "\n"), ("A", "A"), ("A", "é" * 8193)],
    ids=["empty-source", "blank-source", "empty-target", "blank-target", "no-op", "oversize"],
)
def test_invalid_literals_rejected(source, target):
    with pytest.raises(ValueError):
        ExactRule(source, target)


@pytest.mark.parametrize("source,target", [("N/A", "Acme"), ("Acme", "N/A")])
def test_missing_tokens_cannot_be_reinterpreted(context, source, target):
    _, saved, _, table, store = context
    with pytest.raises(ValueError, match="missing tokens"):
        review_excel_text(saved, table, 1, ExactRulesSettings((ExactRule(source, target),)), store)


def test_category_only_accepts_exact_allowed_targets_and_no_fuzzy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _, source, _, table, store = prepare(tmp_path, ["current", "CURRENT", "Default", "CURRENT "])
    category(table, store)
    settings = ExactRulesSettings(
        (ExactRule("current", "CURRENT"), ExactRule("Default", "DEFAULT"))
    )
    review = review_excel_text(source, table, 1, settings, store)
    assert review.preview.to_dict()["reconciliation"]["changed"] == 2
    revision, path = apply_excel_text(source, table, 1, settings, store, review, approve(review))
    assert derived_text_values(revision) == ((2, 1, "CURRENT"),)
    assert load_transformation(path, source, table, review.scope, store.catalog()) == revision
    for target in ("Current", "CURRENT ", "UNKNOWN"):
        with pytest.raises(ValueError, match="allowed-value"):
            preview_exact_rules(
                review.snapshot, 1, ExactRulesSettings((ExactRule("current", target),))
            )
    with pytest.raises(ValueError, match="free text"):
        suggest_spellings(review.snapshot, 1, "current", SpellingSettings())
    with pytest.raises(ValueError, match="free-text"):
        review_excel_text(source, table, 1, TextCleanupSettings(), store)


def test_exact_policy_replay_rejects_missing_or_forged_proposals(context):
    _, source, _, table, store = context
    settings = ExactRulesSettings((ExactRule("Acme Hldings", "Acme Holdings"),))
    review = review_excel_text(source, table, 1, settings, store)
    operation = rule_operation(1, settings)
    with pytest.raises(ValueError, match="every eligible literal match"):
        preview_transformation(review.snapshot, operation, ())
    with pytest.raises(ValueError, match="every eligible literal match"):
        preview_transformation(
            review.snapshot,
            operation,
            (CellProposal(2, 1, "Acme Hldings", "Wrong", "fake", "Wrong"),),
        )
    with pytest.raises(ValueError, match="version"):
        replace(operation, engine_version="99")
    with pytest.raises(ValueError):
        preview_exact_rules(review.snapshot, 2, settings)


@pytest.mark.parametrize("change", ["rules", "mapping", "dictionary", "source"])
def test_stale_reviews_never_publish(context, change, tmp_path):
    _, source, _, table, store = context
    settings = ExactRulesSettings((ExactRule("Acme Hldings", "Acme Holdings"),))
    review = review_excel_text(source, table, 1, settings, store)
    if change == "rules":
        settings = ExactRulesSettings((ExactRule("Acme Hldings", "Other"),))
    elif change == "mapping":
        definition = definition_for_column(table, 1)
        save_column_definition(
            table, replace(definition, rules=ColumnRules(missing_tokens=("N/A", "Other")))
        )
    elif change == "dictionary":
        store.deactivate("loan.text")
    else:
        source.write_bytes(source.read_bytes() + b"changed")
    with pytest.raises(ValueError):
        apply_excel_text(source, table, 1, settings, store, review, approve(review))
    assert not list((tmp_path / ".artifacts/transformations").glob("*"))


def test_exact_staging_guard(context, monkeypatch, tmp_path):
    import loan_tape.transformation_excel as adapter

    _, source, _, table, store = context
    settings = ExactRulesSettings((ExactRule("Acme Hldings", "Acme Holdings"),))
    review = review_excel_text(source, table, 1, settings, store)
    original = adapter.os.fsync

    def changed(fd):
        original(fd)
        store.deactivate("loan.text")

    monkeypatch.setattr(adapter.os, "fsync", changed)
    with pytest.raises(ValueError, match="dictionary"):
        apply_excel_text(source, table, 1, settings, store, review, approve(review))
    assert list((tmp_path / ".artifacts/transformations").iterdir()) == []


def test_candidate_paging_ties_and_cancellation(tmp_path, monkeypatch):
    import loan_tape.text_rules as engine

    monkeypatch.chdir(tmp_path)
    _, source, _, table, store = prepare(tmp_path, ["Q", *[f"Value{i:03}" for i in range(211)]])
    review = review_excel_text(source, table, 1, ExactRulesSettings(), store)
    result = suggest_spellings(review.snapshot, 1, "Q", SpellingSettings(0))
    assert len(result.page()) == 200 and len(result.page(200)) == 11
    assert [c.text for c in result.candidates] == sorted(c.text for c in result.candidates)
    assert result.eligible_count == 212
    with pytest.raises(ValueError):
        result.page(0, 201)
    with pytest.raises(ValueError):
        result.rule(-1)
    cancelled = Event()
    actual = engine.ratio

    def stop(*args, **kwargs):
        score = actual(*args, **kwargs)
        cancelled.set()
        return score

    monkeypatch.setattr(engine, "ratio", stop)
    with pytest.raises(ScanCancelled):
        suggest_spellings(review.snapshot, 1, "Q", SpellingSettings(0), cancelled=cancelled)


def test_comparison_failures_are_explicit(context, monkeypatch):
    import loan_tape.text_rules as engine

    _, source, _, table, store = context
    review = review_excel_text(source, table, 1, ExactRulesSettings(), store)
    with monkeypatch.context() as local:
        local.setattr(engine, "version", lambda _: "wrong")
        with pytest.raises(ValueError, match="RapidFuzz 3.14.6"):
            suggest_spellings(review.snapshot, 1, "Acme Hldings", SpellingSettings())

    def fail(*args, **kwargs):
        raise RuntimeError("Engine failed")

    monkeypatch.setattr(engine, "ratio", fail)
    with pytest.raises(RuntimeError, match="Engine failed"):
        suggest_spellings(review.snapshot, 1, "Acme Hldings", SpellingSettings())


def test_actual_distinct_value_limit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _, source, _, table, store = prepare(tmp_path, [f"Name{i}" for i in range(10_001)])
    with pytest.raises(ValueError, match="10,000 distinct"):
        suggest_excel_text(source, table, 1, "Name0", SpellingSettings(), store)


def test_rule_limits_and_required_provenance():
    assert len(ExactRulesSettings(tuple(ExactRule(f"A{i}", "B") for i in range(200))).rules) == 200
    with pytest.raises(ValueError, match="200"):
        ExactRulesSettings(tuple(ExactRule(f"A{i}", "B") for i in range(201)))
    with pytest.raises(ValueError, match="4 MiB"):
        ExactRulesSettings(
            tuple(ExactRule(f"{i:03}" + "A" * 16_000, "B" * 16_000) for i in range(140))
        )
    evidence = SpellingEvidence("a" * 64, None, 1, "b" * 64, 99, 85, "literal", "test-version")
    with pytest.raises(ValueError, match="SHA-256"):
        replace(evidence, snapshot_id=None)
    with pytest.raises(ValueError, match="score"):
        replace(evidence, score=float("nan"))
    with pytest.raises(ValueError, match="threshold"):
        SpellingSettings(101)
