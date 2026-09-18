"""Complete XML navigation and content-bound saved setups."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from loan_tape.inspection import InspectionError, read_preview
from loan_tape.xml_selection import (
    XmlDataSet,
    XmlSelections,
    load_xml_selections,
    save_xml_selections,
    xml_selection_path,
)


def matrix(path):
    payload = '<r xmlns="https://example.invalid/loans"><items>'
    for row in range(1, 48):
        payload += f'<item id="{row:06}">'
        payload += "".join(f"<f{col}>{row}:{col}</f{col}>" for col in range(1, 24))
        if row == 47:
            payload += "<late>000099</late>"
        payload += "</item>"
    payload += "</items></r>"
    path.write_text(payload, encoding="utf-8")
    return payload.encode()


def test_every_record_and_field_reachable_with_stable_labels_and_source_paths(tmp_path):
    source = tmp_path / "matrix.xml"
    payload = matrix(source)
    first = read_preview(source)
    assert first.record_count == 47 and first.field_count == 25
    assert first.source_sha256 == hashlib.sha256(payload).hexdigest()
    canonical = (
        "{https://example.invalid/loans}r",
        "{https://example.invalid/loans}items",
        "{https://example.invalid/loans}item",
    )
    assert first.record_group_paths == (canonical,)
    cells = {}
    for row in (1, 21, 41):
        for column in (1, 11, 21):
            page = read_preview(
                source,
                xml_group_path=canonical,
                xml_start_row=row,
                xml_start_column=column,
                xml_source_sha256=first.source_sha256,
            )
            assert page.start_row == row and page.start_column == column
            assert page.more_rows == (row < 41)
            assert page.more_columns == (column < 21)
            assert page.record_count == 47 and page.field_count == 25
            for number, values in enumerate(page.rows, row):
                for index, cell in enumerate(values, column):
                    assert (number, index) not in cells
                    cells[number, index] = cell
                    assert f"item[{number}]" in cell.source_path
    assert len(cells) == 47 * 25
    assert cells[41, 1].text == "000041"
    assert cells[47, 24].text == "47:23"
    assert cells[47, 25].text == "000099"
    assert cells[1, 25].presence == "Absent"
    assert source.read_bytes() == payload


@pytest.mark.parametrize(
    ("row", "column"),
    [(0, 1), (1, 0), (-1, 1), (True, 1), (1, False), (1, 26), (48, 1), (1, 2049), (1000001, 1)],
)
def test_bad_page_coordinates_fail_without_an_empty_success(tmp_path, row, column):
    source = tmp_path / "data.xml"
    matrix(source)
    with pytest.raises(InspectionError, match="record|field"):
        read_preview(source, xml_start_row=row, xml_start_column=column)


def test_distant_page_and_endpoints_preserve_exact_coordinates(tmp_path):
    source = tmp_path / "data.xml"
    matrix(source)
    page = read_preview(source, xml_start_row=47, xml_start_column=25)
    assert len(page.rows) == 1 and page.column_count == 1
    assert page.column_labels == ("ns1:late",)
    assert page.rows[0][0].text == "000099"
    assert page.rows[0][0].source_path.endswith("/ns1:item[47]/ns1:late[1]")
    assert not page.more_rows and not page.more_columns


def test_changed_source_cannot_reuse_an_old_page_identity(tmp_path):
    source = tmp_path / "data.xml"
    matrix(source)
    first = read_preview(source)
    source.write_text(source.read_text().replace("000001", "000009"), encoding="utf-8")
    with pytest.raises(InspectionError, match="source changed"):
        read_preview(source, xml_start_row=41, xml_source_sha256=first.source_sha256)
    with pytest.raises(InspectionError, match="unavailable"):
        read_preview(source, xml_group_path=("missing",))


def test_complete_structure_checked_outside_requested_page(tmp_path):
    source = tmp_path / "data.xml"
    source.write_text("<r><item><v>1</v><v>2</v></item>" + "<item><v>3</v></item>" * 45 + "</r>")
    page = read_preview(source, xml_group="/r/item", xml_start_row=41)
    assert not page.rows and "Repeated child" in page.record_group_error
    source.write_text("<r>" + "<item>ok</item>" * 45 + "<broken></r>")
    with pytest.raises(InspectionError, match="parse XML"):
        read_preview(source, xml_start_row=21)


def test_saving_reopening_multiple_groups_and_positions_preserves_xml_and_excel_metadata(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "data.xml"
    payload = matrix(source)
    result = read_preview(source)
    sha = result.source_sha256
    a = XmlDataSet("a" * 32, "Loans", result.record_group_paths[0], 41, 21)
    b = XmlDataSet("b" * 32, "Another view", result.record_group_paths[0], 1, 11)
    excel = tmp_path / ".artifacts" / "selections" / (sha + ".json")
    excel.parent.mkdir(parents=True)
    excel.write_text("Existing workbook settings")
    settings = XmlSelections(sha, (a, b), b.id)
    save_xml_selections(settings)
    assert load_xml_selections(sha) == settings
    assert load_xml_selections(sha).active == b
    save_xml_selections(XmlSelections(sha, (replace(a, name="Renamed"), b), a.id))
    assert load_xml_selections(sha).active.row == 41
    save_xml_selections(XmlSelections(sha, (b,), b.id))
    assert load_xml_selections(sha).data_sets == (b,)
    assert load_xml_selections("0" * 64).data_sets == ()
    assert source.read_bytes() == payload
    assert excel.read_text() == "Existing workbook settings"
    saved_json = json.loads(xml_selection_path(sha).read_text())
    assert saved_json["data_sets"][0]["group_path"] == list(b.group_path)


def test_failed_atomic_publication_retains_previous_settings(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    a = XmlDataSet("a" * 32, "Loans", ("r", "loan"))
    settings = XmlSelections("1" * 64, (a,), a.id)
    save_xml_selections(settings)
    old = xml_selection_path(settings.source_sha256).read_bytes()
    with monkeypatch.context() as scoped:

        def fail(*args):
            raise PermissionError("cannot replace")

        scoped.setattr(Path, "replace", fail)
        with pytest.raises(PermissionError):
            save_xml_selections(XmlSelections("1" * 64))
    assert xml_selection_path(settings.source_sha256).read_bytes() == old
    assert not list(xml_selection_path(settings.source_sha256).parent.glob("*.tmp"))


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": True},
        {"schema_version": 2},
        {"source_sha256": "2" * 64},
        {"active_id": "c" * 32},
        {"data_sets": {}},
        {"extra": 1},
        {
            "data_sets": [
                {"id": "a" * 32, "name": "Loans", "group_path": "r/item", "row": 1, "column": 1}
            ]
        },
        {
            "data_sets": [
                {
                    "id": "a" * 32,
                    "name": "Loans",
                    "group_path": ["r", "item"],
                    "row": True,
                    "column": 1,
                }
            ]
        },
    ],
)
def test_invalid_saved_settings_are_visible_and_not_rewritten(tmp_path, monkeypatch, change):
    monkeypatch.chdir(tmp_path)
    a = XmlDataSet("a" * 32, "Loans", ("r", "item"))
    save_xml_selections(XmlSelections("1" * 64, (a,), a.id))
    path = xml_selection_path("1" * 64)
    data = json.loads(path.read_text())
    data.update(change)
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="could not be read"):
        load_xml_selections("1" * 64)
    assert path.read_bytes() == before


def test_duplicate_names_and_invalid_identities_are_rejected():
    a = XmlDataSet("a" * 32, "Loans", ("r", "item"))
    with pytest.raises(ValueError, match="own identity and name"):
        XmlSelections("1" * 64, (a, replace(a, id="b" * 32, name=" loans ")))
    with pytest.raises(ValueError):
        xml_selection_path("../outside")
    with pytest.raises(ValueError):
        XmlDataSet("a" * 32, "", ("r",))
