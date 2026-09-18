"""Generic XSD validation stays explicit, local, complete, and read-only."""

import hashlib
from pathlib import Path
from threading import Event

import pytest

from loan_tape import xml_schema
from loan_tape.inspection import InspectionError
from loan_tape.xml_schema import FINDINGS_PAGE_SIZE, validate_xml_schema


def write_schema(directory: Path) -> tuple[Path, Path]:
    parts = directory / "parts"
    parts.mkdir()
    included = parts / "amount.xsd"
    included.write_text(
        """<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
        <xs:simpleType name="amountType"><xs:restriction base="xs:decimal">
        <xs:minInclusive value="0"/></xs:restriction></xs:simpleType>
        </xs:schema>""",
        encoding="utf-8",
    )
    main = directory / "loans.xsd"
    main.write_text(
        """<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
        <xs:include schemaLocation="parts/amount.xsd"/>
        <xs:element name="loans"><xs:complexType><xs:sequence>
        <xs:element name="loan" maxOccurs="unbounded"><xs:complexType><xs:sequence>
        <xs:element name="amount" type="amountType"/>
        </xs:sequence><xs:attribute name="id" type="xs:string" use="required"/>
        </xs:complexType></xs:element>
        </xs:sequence></xs:complexType></xs:element>
        </xs:schema>""",
        encoding="utf-8",
    )
    return main, included


def source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_complete_validation_pages_all_findings_and_preserves_sources(tmp_path):
    schema, included = write_schema(tmp_path)
    xml = tmp_path / "loans.xml"
    xml.write_text(
        "<loans>"
        + "".join(f'<loan id="{row:06}"><amount>-{row}</amount></loan>' for row in range(1, 76))
        + "</loans>",
        encoding="utf-8",
    )
    before = {path: path.read_bytes() for path in (xml, schema, included)}
    report = validate_xml_schema(xml, schema, source_hash(xml))
    try:
        assert report.schema_version == "XSD 1.0"
        assert report.finding_count == 75
        assert len(report.resources) == 2
        assert report.schema.path == schema.resolve()
        assert report.schema.sha256 == source_hash(schema)
        assert len(report.page()) == FINDINGS_PAGE_SIZE
        assert len(report.page(FINDINGS_PAGE_SIZE)) == 25
        assert report.page()[0].source_path == "/loans/loan[1]/amount"
        assert "greater or equal" in report.page()[0].reason
        assert all(path.read_bytes() == content for path, content in before.items())
    finally:
        temporary = Path(report._temporary.name)
        report.close()
    assert not temporary.exists()
    with pytest.raises(InspectionError, match="closed"):
        report.page()


def test_valid_document_and_schema_hint_is_ignored(tmp_path):
    schema, _ = write_schema(tmp_path)
    xml = tmp_path / "loans.xml"
    xml.write_text(
        """<loans xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xsi:noNamespaceSchemaLocation="https://example.invalid/never.xsd">
        <loan id="000001"><amount>0.0000</amount></loan></loans>""",
        encoding="utf-8",
    )
    report = validate_xml_schema(xml, schema, source_hash(xml))
    try:
        assert report.finding_count == 0
        assert report.page() == ()
    finally:
        report.close()


def test_xsd_11_is_selected_explicitly_from_schema_version(tmp_path):
    schema = tmp_path / "versioned.xsd"
    schema.write_text(
        """<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" version="1.1">
        <xs:element name="root" type="xs:string"/></xs:schema>""",
        encoding="utf-8",
    )
    xml = tmp_path / "source.xml"
    xml.write_text("<root>ok</root>", encoding="utf-8")
    report = validate_xml_schema(xml, schema, source_hash(xml))
    try:
        assert report.schema_version == "XSD 1.1"
        assert report.finding_count == 0
    finally:
        report.close()


def test_outside_folder_schema_dependency_is_blocked(tmp_path):
    outside = tmp_path / "outside.xsd"
    outside.write_text(
        """<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
        <xs:simpleType name="outsideType"><xs:restriction base="xs:string"/></xs:simpleType>
        </xs:schema>""",
        encoding="utf-8",
    )
    folder = tmp_path / "schema"
    folder.mkdir()
    schema = folder / "main.xsd"
    schema.write_text(
        """<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
        <xs:include schemaLocation="../outside.xsd"/>
        <xs:element name="root" type="outsideType"/></xs:schema>""",
        encoding="utf-8",
    )
    xml = tmp_path / "source.xml"
    xml.write_text("<root>ok</root>", encoding="utf-8")
    with pytest.raises(InspectionError, match="outside-folder imports are blocked"):
        validate_xml_schema(xml, schema, source_hash(xml))


@pytest.mark.parametrize(
    ("schema_text", "message"),
    [
        ("<not-schema/>", "not an XML Schema"),
        (
            '<!DOCTYPE xs:schema [<!ENTITY x "bad">]><xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">&x;</xs:schema>',
            "parsed safely",
        ),
        ("<xs:schema", "parsed safely"),
    ],
)
def test_invalid_or_unsafe_schema_fails_clearly(tmp_path, schema_text, message):
    schema = tmp_path / "bad.xsd"
    schema.write_text(schema_text, encoding="utf-8")
    xml = tmp_path / "source.xml"
    xml.write_text("<root/>", encoding="utf-8")
    with pytest.raises(InspectionError, match=message):
        validate_xml_schema(xml, schema, source_hash(xml))


def test_source_change_during_validation_discards_result(tmp_path, monkeypatch):
    schema, _ = write_schema(tmp_path)
    xml = tmp_path / "loans.xml"
    xml.write_text('<loans><loan id="1"><amount>1</amount></loan></loans>', encoding="utf-8")
    original = xml_schema._hash_file
    source_calls = 0

    def change(path, cancelled):
        nonlocal source_calls
        if path == xml:
            source_calls += 1
            if source_calls == 2:
                xml.write_text("<loans/>", encoding="utf-8")
        return original(path, cancelled)

    monkeypatch.setattr(xml_schema, "_hash_file", change)
    with pytest.raises(InspectionError, match="changed during"):
        validate_xml_schema(xml, schema, source_hash(xml))


def test_schema_dependency_change_during_validation_discards_result(tmp_path, monkeypatch):
    schema, included = write_schema(tmp_path)
    xml = tmp_path / "loans.xml"
    xml.write_text('<loans><loan id="1"><amount>1</amount></loan></loans>', encoding="utf-8")
    original = xml_schema._hash_file
    dependency_calls = 0

    def change(path, cancelled):
        nonlocal dependency_calls
        if path == included.resolve():
            dependency_calls += 1
            if dependency_calls == 2:
                included.write_text(included.read_text(encoding="utf-8") + " ", encoding="utf-8")
        return original(path, cancelled)

    monkeypatch.setattr(xml_schema, "_hash_file", change)
    with pytest.raises(InspectionError, match="dependencies changed"):
        validate_xml_schema(xml, schema, source_hash(xml))


def test_cancellation_and_schema_size_limit_are_explicit(tmp_path, monkeypatch):
    schema, _ = write_schema(tmp_path)
    xml = tmp_path / "loans.xml"
    xml.write_text("<loans/>", encoding="utf-8")
    cancelled = Event()
    cancelled.set()
    with pytest.raises(InspectionError, match="cancelled"):
        validate_xml_schema(xml, schema, source_hash(xml), cancelled=cancelled)
    monkeypatch.setattr(xml_schema, "MAX_SCHEMA_FILE_BYTES", 10)
    with pytest.raises(InspectionError, match="selected XSD exceeds"):
        validate_xml_schema(xml, schema, source_hash(xml))


def test_dependency_budget_is_enforced_before_schema_compilation(tmp_path, monkeypatch):
    dependency = tmp_path / "dependency.xsd"
    dependency.write_text(
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        + "<!--"
        + ("x" * 2_000)
        + "-->"
        + '<xs:simpleType name="text"><xs:restriction base="xs:string"/></xs:simpleType>'
        + "</xs:schema>",
        encoding="utf-8",
    )
    schema = tmp_path / "main.xsd"
    schema.write_text(
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        '<xs:include schemaLocation="dependency.xsd"/>'
        '<xs:element name="root" type="text"/></xs:schema>',
        encoding="utf-8",
    )
    xml = tmp_path / "source.xml"
    xml.write_text("<root>ok</root>", encoding="utf-8")
    compiled = False

    def fail_if_compiled(*args, **kwargs):
        nonlocal compiled
        compiled = True
        raise AssertionError("schema compiler must not run")

    monkeypatch.setattr(xml_schema, "MAX_SCHEMA_FILE_BYTES", 1_000)
    monkeypatch.setattr(xml_schema.xmlschema, "XMLSchema10", fail_if_compiled)
    with pytest.raises(InspectionError, match="Schema dependency.*exceeds"):
        validate_xml_schema(xml, schema, source_hash(xml))
    assert not compiled


def test_schema_dependency_count_is_bounded_before_compilation(tmp_path, monkeypatch):
    for name, following in (("two.xsd", "three.xsd"), ("three.xsd", None)):
        include = f'<xs:include schemaLocation="{following}"/>' if following else ""
        (tmp_path / name).write_text(
            f'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">{include}</xs:schema>',
            encoding="utf-8",
        )
    schema = tmp_path / "main.xsd"
    schema.write_text(
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        '<xs:include schemaLocation="two.xsd"/><xs:element name="root" type="xs:string"/>'
        "</xs:schema>",
        encoding="utf-8",
    )
    xml = tmp_path / "source.xml"
    xml.write_text("<root>ok</root>", encoding="utf-8")
    monkeypatch.setattr(xml_schema, "MAX_SCHEMA_FILES", 2)
    with pytest.raises(InspectionError, match="file limit"):
        validate_xml_schema(xml, schema, source_hash(xml))
