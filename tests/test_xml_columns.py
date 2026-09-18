"""Complete XML profiling and explicit checks through the shared column services."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from xml.sax.saxutils import escape

import pytest

from loan_tape import column_profile, xml_column
from loan_tape.column_check import ColumnRules, check_column
from loan_tape.column_profile import inspect_column
from loan_tape.inspection import InspectionError, read_preview
from loan_tape.session import AnalysisSession
from loan_tape.xml_selection import SavedXmlTable

SESSION = AnalysisSession("xml-test", datetime(2026, 9, 16, tzinfo=UTC))


def write_values(path, values):
    body = []
    for row, value in enumerate(values, 1):
        v = (
            "<v/>"
            if value == ("empty",)
            else '<v xsi:nil="true"/>'
            if value == ("nil",)
            else ""
            if value is None
            else f"<v>{escape(value)}</v>"
        )
        body.append(f'<item id="{row:06}">{v}</item>')
    path.write_text(
        '<r xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">' + "".join(body) + "</r>",
        encoding="utf-8",
    )
    return scope(path)


def scope(path, group=None, start_column=1):
    preview = read_preview(path, xml_group=group, xml_start_column=start_column)
    assert preview.rows and not preview.record_group_error
    table = SavedXmlTable(
        "a" * 32,
        "All records",
        preview.source_sha256,
        preview.record_group_paths[preview.record_groups.index(preview.selected_record_group)],
        preview.selected_record_group,
        preview.record_count,
        preview.field_count,
    )
    return table


def assert_cleanup():
    for name in ("column-inspection", "column-checks"):
        parent = Path(".artifacts") / name
        assert not parent.exists() or not list(parent.iterdir())


def test_full_profile_keeps_presence_text_zeroes_repetitions_and_lineage(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "values.xml"
    values = [
        "000123",
        ("empty",),
        ("nil",),
        None,
        " \t ",
        "0",
        "0.00",
        "N/A",
        "000123",
        "=SUM(A1)",
    ] * 9
    table = write_values(source, values)
    before = source.read_bytes()
    profile = inspect_column(source, table, 2, SESSION)
    assert profile.total_rows == 90 and profile.filled_cells == 63
    assert dict(profile.counts) == {
        "Absent": 9,
        "Empty element": 9,
        "Explicit nil": 9,
        "Empty text": 0,
        "Text": 63,
    }
    assert profile.numeric_zeroes == 0 and profile.text_zeroes == 9 and profile.whitespace_text == 9
    assert (
        profile.distinct_values == 6
        and profile.repeated_values == 6
        and profile.extra_occurrences == 57
    )
    assert profile.table == table and profile.session is SESSION and profile.header == "v"
    repeat = next(item for item in profile.repeated if item.text == "000123")
    assert repeat.count == 18 and repeat.row == 1
    assert repeat.source_path == "/r[1]/item[1]/v[1]" and repeat.presence == "Present"
    absent = next(item for item in profile.examples if item.kind == "Absent")
    assert "item[4]" in absent.source_path and absent.presence == "Absent"
    assert source.read_bytes() == before
    assert_cleanup()


def test_empty_attributes_and_same_named_namespace_fields_remain_distinct(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "namespaces.xml"
    source.write_text(
        '<r xmlns:a="urn:one" xmlns:b="urn:two"><item id=""><a:v>001</a:v><b:v>other</b:v></item><item><a:v>001</a:v><b:v/></item></r>'
    )
    table = scope(source)
    attr = inspect_column(source, table, 1, SESSION)
    assert dict(attr.counts)["Empty text"] == 1 and dict(attr.counts)["Absent"] == 1
    assert next(x for x in attr.examples if x.kind == "Empty text").presence == "Present"
    first = inspect_column(source, table, 2, SESSION)
    second = inspect_column(source, table, 3, SESSION)
    assert first.header == "ns1:v" and first.repeated[0].text == "001"
    assert second.header == "ns2:v" and second.examples[0].text == "other"
    assert second.examples[1].presence == "Empty element"
    assert first.examples[0].source_path != second.examples[0].source_path
    assert_cleanup()


def test_off_page_late_field_and_large_population_are_complete_without_preview_rows(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "late.xml"
    source.write_text(
        "<r>"
        + "".join(
            "<item>"
            + "".join(f"<f{col}>{row}:{col}</f{col}>" for col in range(1, 13))
            + ("<late>000099</late>" if row == 2000 else "")
            + "</item>"
            for row in range(1, 2001)
        )
        + "</r>"
    )
    table = scope(source)
    original = xml_column._parse

    def parsed(path, target):
        result = original(path, target)
        assert not target.rows and not target.locations
        return result

    monkeypatch.setattr(xml_column, "_parse", parsed)
    result = inspect_column(source, table, 13, SESSION)
    assert result.total_rows == 2000 and result.header == "late"
    assert dict(result.counts)["Absent"] == 1999
    assert result.examples[-1].row == 2000 and result.examples[-1].text == "000099"
    unique = inspect_column(source, table, 12, SESSION)
    assert unique.distinct_values == 2000 and unique.repeated_values == 0
    assert len(unique.examples) == 3
    assert_cleanup()


@pytest.mark.parametrize(
    "text", ["0", "000123", "+1", "-0.003", ".5", "123456789012345678901234567890.000100"]
)
def test_plain_decimal_checks_preserve_exact_text(tmp_path, monkeypatch, text):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "number.xml"
    table = write_values(source, [text, text])
    before = source.read_bytes()
    report = check_column(
        source, table, 2, SESSION, ColumnRules("Number", number_format="Plain decimal text")
    )
    try:
        assert report.finding_count == 0
        assert report.profile.repeated[0].text == text
    finally:
        report.close()
    assert source.read_bytes() == before
    assert_cleanup()


@pytest.mark.parametrize(
    "text",
    ["1,000", "1e3", "$2.00", "12%", "NaN", "Infinity", "1.", "--2", " 1 ", "N/A", "1_000", "١٢"],
)
def test_number_grammar_does_not_guess_conventions(tmp_path, monkeypatch, text):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "number.xml"
    table = write_values(source, [text, text])
    report = check_column(
        source, table, 2, SESSION, ColumnRules("Number", number_format="Plain decimal text")
    )
    try:
        assert report.finding_count == 2 and "plain decimal text" in report.page()[0].reason
        assert report.page()[0].cell.text == text and report.page()[0].cell.source_path.endswith(
            "/v[1]"
        )
    finally:
        report.close()
    assert_cleanup()


def test_every_finding_and_missing_state_survives_paging_and_close(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "bad.xml"
    table = write_values(source, ["N/A"] * 41 + [None, ("empty",), ("nil",), " \t "] + ["N/A"] * 18)
    report = check_column(
        source, table, 2, SESSION, ColumnRules("Number", number_format="Plain decimal text")
    )
    cells = []
    try:
        assert report.finding_count == 63
        for offset in (0, 20, 40, 60):
            cells.extend(report.page(offset))
        assert [item.cell.row for item in cells] == list(range(1, 64))
        assert [item.cell.kind for item in cells[41:45]] == [
            "Absent",
            "Empty element",
            "Explicit nil",
            "Text",
        ]
        assert [item.cell.presence for item in cells[41:45]] == [
            "Absent",
            "Empty element",
            "Explicit nil",
            "Present",
        ]
        assert "Whitespace-only" in cells[44].reason
        assert "item[63]" in cells[-1].cell.source_path
        with pytest.raises(InspectionError):
            report.page(-1)
    finally:
        report.close()
    with pytest.raises(InspectionError, match="closed"):
        report.page()
    optional = check_column(
        source, table, 2, SESSION, ColumnRules("Number", False, number_format="Plain decimal text")
    )
    try:
        assert optional.allowed_blanks == 4 and optional.finding_count == 59
    finally:
        optional.close()
    assert_cleanup()


def test_identifier_text_and_formula_looking_xml_are_not_coerced(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "identifier.xml"
    values = ["000123", "999999999999999999999999", "N/A", "=1+1", " 0002 "]
    table = write_values(source, values)
    for expectation in ("Identifier", "Text"):
        report = check_column(source, table, 2, SESSION, ColumnRules(expectation))
        try:
            assert report.finding_count == 1 and report.page()[0].cell.row == 5
            assert report.profile.distinct_values == 5
            assert dict(report.profile.counts)["Text"] == 5
        finally:
            report.close()
    assert_cleanup()


def test_dates_require_an_explicit_format_and_keep_reference_context(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "dates.xml"
    values = [
        "2024-02-29",
        "2023-02-29",
        "01/02/2026",
        "2051-01-01",
        "1999-12-31",
        "2026-09-16",
        "45000",
        "2026-09-16T00:00",
        "N/A",
    ]
    table = write_values(source, values)
    with pytest.raises(InspectionError, match="explicit text date"):
        check_column(source, table, 2, SESSION, ColumnRules("Date"))
    with pytest.raises(InspectionError, match="Plain decimal"):
        check_column(source, table, 2, SESSION, ColumnRules("Number"))
    before = source.read_bytes()
    report = check_column(
        source,
        table,
        2,
        SESSION,
        ColumnRules(
            "Date",
            date_format="YYYY-MM-DD",
            min_year=2000,
            max_year=2050,
            flag_before_reference=True,
        ),
    )
    try:
        assert report.finding_count == 8
        findings = {x.cell.row: x for x in report.page()}
        assert 6 not in findings
        assert "reference date" in findings[1].reason
        assert "calendar date" in findings[2].reason and "YYYY-MM-DD" in findings[3].reason
        assert "latest year" in findings[4].reason and "earliest year" in findings[5].reason
        assert report.profile.session is SESSION
    finally:
        report.close()
    assert source.read_bytes() == before
    assert_cleanup()


def test_nested_group_isolation_and_parent_source_occurrences(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "groups.xml"
    source.write_text(
        "<r><loan><fees><fee><v>A</v></fee><fee><v>B</v></fee></fees></loan><loan><fees><fee><v>A</v></fee></fees></loan><other><v>excluded</v></other></r>"
    )
    table = scope(source, "/r/loan/fees/fee")
    profile = inspect_column(source, table, 1, SESSION)
    assert profile.total_rows == 3 and profile.repeated[0].count == 2
    assert profile.examples[2].source_path == "/r[1]/loan[2]/fees[1]/fee[1]/v[1]"
    assert_cleanup()


def test_source_changes_invalid_scopes_and_unsafe_input_never_publish_results(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "source.xml"
    table = write_values(source, ["1", "2"] * 30)
    with pytest.raises(InspectionError, match="field"):
        inspect_column(source, table, 0, SESSION)
    with pytest.raises(InspectionError, match="scope"):
        inspect_column(source, replace(table, record_count=5), 2, SESSION)
    original = xml_column._parse
    calls = 0

    def change(path, target):
        nonlocal calls
        result = original(path, target)
        calls += 1
        if calls == 1:
            path.write_bytes(path.read_bytes().replace(b"<v>1</v>", b"<v>9</v>"))
        return result

    with monkeypatch.context() as scoped:
        scoped.setattr(xml_column, "_parse", change)
        with pytest.raises(InspectionError, match="changed"):
            check_column(source, table, 2, SESSION, ColumnRules("Text"))
    with pytest.raises(InspectionError, match="changed"):
        inspect_column(source, table, 2, SESSION)
    source.write_text('<!DOCTYPE r [<!ENTITY x "oops">]><r>&x;</r>')
    with pytest.raises(InspectionError, match="DTD"):
        inspect_column(source, table, 2, SESSION)
    assert_cleanup()


def test_cancellation_reader_failure_and_storage_limit_cleanup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "cancel.xml"
    table = write_values(source, ["value"] * 100)
    cancelled = Event()
    original = column_profile.ColumnAccumulator.add

    def cancel(acc, cell, key, **kwargs):
        original(acc, cell, key, **kwargs)
        if cell.row == 25:
            cancelled.set()

    with monkeypatch.context() as scoped:
        scoped.setattr(column_profile.ColumnAccumulator, "add", cancel)
        with pytest.raises(InspectionError, match="cancelled"):
            check_column(source, table, 2, SESSION, ColumnRules("Text"), cancelled=cancelled)
    assert_cleanup()
    with monkeypatch.context() as scoped:
        scoped.setattr(column_profile, "XML_RESULT_MAX_BYTES", 4096)
        with pytest.raises(InspectionError, match="storage failed"):
            check_column(source, table, 2, SESSION, ColumnRules("Text"))
    assert_cleanup()
    original_parse = xml_column._parse
    calls = 0

    def broken(path, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise InspectionError("late extraction failure")
        return original_parse(path, target)

    monkeypatch.setattr(xml_column, "_parse", broken)
    with pytest.raises(InspectionError, match="late extraction"):
        check_column(source, table, 2, SESSION, ColumnRules("Text"))
    assert_cleanup()
