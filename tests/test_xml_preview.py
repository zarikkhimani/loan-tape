"""XML previews preserve source data and never multiply nested records."""

import hashlib
from pathlib import Path
from threading import Event

import pytest

from loan_tape import xml_preview
from loan_tape.inspection import InspectionError, read_preview
from loan_tape.intake import IntakeStore


def preview(tmp_path, text, **kwargs):
    source = tmp_path / "source.xml"
    source.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
    return read_preview(source, **kwargs)


def test_intake_reopen_and_text_values_preserve_source(tmp_path):
    source = tmp_path / "source.XML"
    payload = b'<loans><loan id="000123"><balance>100.2300</balance><note>  A &amp; B  </note></loan><loan id="99999999999999999999"><balance>0</balance><note/></loan></loans>'
    source.write_bytes(payload)
    store = IntakeStore(tmp_path / "inputs")
    record = store.save_path(source)
    saved = Path(str(store.describe(record)["saved_path"]))
    result = read_preview(saved)
    assert result.selected_record_group == "/loans/loan"
    assert result.column_labels == ("@id", "balance", "note")
    assert [[c.text for c in row] for row in result.rows] == [
        ["000123", "100.2300", "  A & B  "],
        ["99999999999999999999", "0", ""],
    ]
    assert result.rows[1][2].presence == "Empty element"
    assert result.rows[0][0].source_path == "/loans[1]/loan[1]/@id"
    assert result.record_count == 2
    assert source.read_bytes() == saved.read_bytes() == payload
    assert record["sha256"] == hashlib.sha256(payload).hexdigest()
    assert IntakeStore(tmp_path / "inputs").list_files() == [record]


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "iso-8859-1"])
def test_declared_encoding_and_single_document(tmp_path, encoding):
    xml = f'<?xml version="1.0" encoding="{encoding}"?><loan><borrower><name>Jos\u00e9</name></borrower><balance>001.00</balance></loan>'
    result = preview(tmp_path, xml.encode(encoding))
    assert result.selected_record_group == "/loan"
    assert result.column_labels == ("borrower/name", "balance")
    assert result.rows[0][0].text == "Jos\u00e9"
    assert result.rows[0][1].text == "001.00"


def test_namespace_identity_attributes_and_absent_empty_nil(tmp_path):
    xml = '<r xmlns:a="urn:one" xmlns:b="urn:one" xmlns:c="urn:two" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><a:item><a:id>01</a:id><c:id>other</c:id><empty/><nil xsi:nil="true"/><spaces> </spaces></a:item><b:item><a:id>02</a:id><zero>0</zero></b:item></r>'
    result = preview(tmp_path, xml)
    assert len(result.record_groups) == 1
    assert result.record_count == 2
    fields = dict(zip(result.column_labels, result.rows[0], strict=True))
    assert fields["ns1:id"].text == "01"
    assert fields["ns2:id"].text == "other"
    assert fields["empty"].presence == "Empty element"
    assert fields["nil"].presence == "Explicit nil"
    assert fields["spaces"].text == " "
    second = dict(zip(result.column_labels, result.rows[1], strict=True))
    assert second["empty"].presence == "Absent"
    assert second["zero"].text == "0"
    assert "ns1 = urn:one" in result.reading_note


def test_multiple_groups_require_selection_without_guessing(tmp_path):
    xml = '<root><loans><loan id="1"/><loan id="2"/></loans><fees><fee>5</fee><fee>6</fee></fees></root>'
    result = preview(tmp_path, xml)
    assert result.rows == ()
    assert result.selected_record_group is None
    assert result.record_groups == ("/root/loans/loan", "/root/fees/fee")
    selected = read_preview(tmp_path / "source.xml", xml_group="/root/fees/fee")
    assert [row[0].text for row in selected.rows] == ["5", "6"]
    with pytest.raises(InspectionError, match="unavailable"):
        read_preview(tmp_path / "source.xml", xml_group="/missing")


def test_nested_repetitions_even_beyond_preview_are_not_flattened(tmp_path):
    xml = (
        "<loans>"
        + "<loan><balance>100</balance></loan>" * 20
        + "<loan><balance>200</balance><borrowers><borrower>A</borrower><borrower>B</borrower></borrowers></loan></loans>"
    )
    result = preview(tmp_path, xml, xml_group="/loans/loan")
    assert result.rows == ()
    assert result.record_count == 21
    assert "Repeated child records" in result.record_group_error
    selected = read_preview(tmp_path / "source.xml", xml_group="/loans/loan/borrowers/borrower")
    assert [row[0].text for row in selected.rows] == ["A", "B"]
    assert "loan[21]" in selected.rows[1][0].source_path


@pytest.mark.parametrize(
    "xml",
    [
        "<r><item>before<b>bold</b>after</item><item>ok</item></r>",
        "<r><item><b>bold</b>after</item><item>ok</item></r>",
        '<r xml:space="preserve"><item> <b>bold</b> </item><item>ok</item></r>',
        '<r xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><item xsi:nil="true">value</item><item/></r>',
    ],
)
def test_unrepresentable_content_is_visible_with_tiny_parser_chunks(tmp_path, monkeypatch, xml):
    monkeypatch.setattr(xml_preview, "CHUNK_BYTES", 1)
    result = preview(tmp_path, xml)
    assert result.rows == ()
    assert result.record_group_error


def test_full_document_checked_and_late_fields_counted(tmp_path):
    xml = (
        "<r>"
        + "<item><id>01</id></item>" * 20
        + "<item>"
        + "".join(f"<f{i}>x</f{i}>" for i in range(12))
        + "</item></r>"
    )
    result = preview(tmp_path, xml)
    assert len(result.rows) == 20 and result.column_count == 10
    assert result.more_rows and result.more_columns
    assert result.rows[0][1].presence == "Absent"
    with pytest.raises(InspectionError, match="parse XML"):
        preview(tmp_path, xml[:-4] + "<broken>")


@pytest.mark.parametrize(
    "xml",
    [
        '<!DOCTYPE r [<!ENTITY secret SYSTEM "file:///never-read.txt">]><r>&secret;</r>',
        '<!DOCTYPE r SYSTEM "https://example.invalid/not-loaded.dtd"><r/>',
        '<!DOCTYPE r [<!ENTITY a "expansion">]><r>&a;</r>',
        "",
        "<r><wrong></r>",
    ],
)
def test_unsafe_or_malformed_xml_fails_clearly(tmp_path, xml):
    with pytest.raises(InspectionError, match="DTD|parse XML"):
        preview(tmp_path, xml)


@pytest.mark.parametrize(
    ("limit", "amount", "xml"),
    [
        ("MAX_DEPTH", 2, "<r><a><b/></a></r>"),
        ("MAX_NODES", 2, "<r><a/><a/></r>"),
        ("MAX_PATHS", 2, "<r><a/><b/></r>"),
        ("MAX_ATTRIBUTES", 1, '<r a="1" b="2"/>'),
        ("MAX_VALUE_CHARS", 3, "<r>1234</r>"),
        ("MAX_VALUE_CHARS", 3, '<r a="1234"/>'),
        ("MAX_PREVIEW_CHARS", 3, "<r><a>12</a><b>34</b></r>"),
        ("MAX_NAME_CHARS", 3, "<longname/>"),
        ("MAX_FILE_BYTES", 3, "<r/>"),
    ],
)
def test_limits_fail_explicitly(tmp_path, monkeypatch, limit, amount, xml):
    monkeypatch.setattr(xml_preview, limit, amount)
    with pytest.raises(InspectionError):
        preview(tmp_path, xml)


def test_cancellation_before_and_during_parsing(tmp_path, monkeypatch):
    cancelled = Event()
    cancelled.set()
    with pytest.raises(InspectionError, match="cancelled"):
        preview(tmp_path, "<r/>", cancelled=cancelled)
    cancelled.clear()
    original = xml_preview._Target.data

    def cancel(target, text):
        cancelled.set()
        original(target, text)

    monkeypatch.setattr(xml_preview._Target, "data", cancel)
    with pytest.raises(InspectionError, match="cancelled"):
        preview(tmp_path, "<r><a>value</a></r>", cancelled=cancelled)


def test_source_change_between_discovery_and_preview_fails(tmp_path, monkeypatch):
    original = xml_preview._parse
    calls = 0

    def change(path, target):
        nonlocal calls
        result = original(path, target)
        calls += 1
        if calls == 1:
            path.write_text("<r><v>changed</v></r>", encoding="utf-8")
        return result

    monkeypatch.setattr(xml_preview, "_parse", change)
    with pytest.raises(InspectionError, match="changed between"):
        preview(tmp_path, "<r><v>original</v></r>")


def test_schema_hints_and_processing_instructions_are_not_executed(tmp_path):
    xml = '<?xml-stylesheet href="https://example.invalid/style.xsl"?><r xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="https://example.invalid/schema.xsd"><value><![CDATA[=1+1]]></value></r>'
    result = preview(tmp_path, xml)
    assert result.rows[0][-1].text == "=1+1"
    assert result.rows[0][-1].formula is None
