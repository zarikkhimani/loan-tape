"""Source and code authoring preserves links, literal values, and activated snapshots."""

import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from loan_tape.pack_authoring import LOCAL_CODES_URI, documents_for, save_draft, update_field
from loan_tape.pack_content import (
    managed_ids,
    remove_code_list,
    remove_source,
    update_citations,
    update_code_list,
    update_source,
)
from loan_tape.pack_format import PACK_FILES, PackError, load_pack
from loan_tape.packs import PackStore


def source(**changes):
    return dict(
        id="reviewed.source",
        title="Reviewed source",
        version="2026",
        uri="urn:test:source",
        **changes,
    )


def codes():
    return dict(
        id="reviewed.codes",
        codes=[
            dict(value="001", label="First code", definition="A literal identifier."),
            dict(value="1", label="Another code", definition="Distinct from 001."),
            dict(value=" ND1\n", label="Multiline\nlabel", definition="Do not trim\nor split."),
        ],
        references=[],
    )


@pytest.fixture
def store(tmp_path):
    shutil.copytree(Path(__file__).resolve().parents[1] / "packs", tmp_path / "packs")
    return PackStore(tmp_path / "packs", tmp_path / "state")


def test_sources_can_precede_fields_without_saving_fake_content(store):
    empty = documents_for()
    docs = update_source(empty, None, source(sha256="a" * 64))
    assert not empty["sources.json"]
    assert docs["fields.json"] == [] and docs["code_lists.json"] == []
    assert docs["sources.json"] == [source(sha256="a" * 64)]
    revised = {**docs["sources.json"][0], "title": "Corrected title", "sha256": None}
    docs = update_source(docs, 0, revised)
    assert docs["sources.json"] == [revised]
    assert remove_source(docs, 0) == empty
    docs["pack.json"].update(id="empty.pack", name="Empty", description="Incomplete")
    with pytest.raises(PackError, match="at least one field or code list"):
        save_draft(store, docs)
    assert not (store.packs_dir / "empty.pack").exists()


@pytest.mark.parametrize("problem", ["duplicate", "rename", "empty", "hash", "reserved"])
def test_invalid_source_edits_leave_original_draft_intact(problem):
    docs = update_source(documents_for(), None, source())
    before = deepcopy(docs)
    values, index = source(), 0
    if problem == "duplicate":
        index = None
    elif problem == "rename":
        values["id"] = "changed.source"
    elif problem == "empty":
        values["title"] = " "
    elif problem == "hash":
        values["sha256"] = "not a hash"
    else:
        values["uri"] = LOCAL_CODES_URI
    with pytest.raises(PackError):
        update_source(docs, index, values)
    assert docs == before


def test_linked_source_requires_citation_changes_before_removal(store):
    base = store.available_pack("example.loans")
    docs = update_source(documents_for(base), None, source())
    reference = dict(source="reviewed.source", locator="Sheet Fields, B2:D2")
    docs = update_citations(docs, "fields.json", 0, [reference])
    docs = update_citations(docs, "code_lists.json", 0, [reference])
    with pytest.raises(PackError, match="field loan_id.*allowed-value list"):
        remove_source(docs, len(docs["sources.json"]) - 1)
    for kind in ("fields.json", "code_lists.json"):
        docs = update_citations(
            docs, kind, 0, [dict(source=base.sources[0].id, locator="Replacement citation")]
        )
    docs = remove_source(docs, len(docs["sources.json"]) - 1)
    assert all(s["id"] != "reviewed.source" for s in docs["sources.json"])


@pytest.mark.parametrize("references", [[], [{"source": "unknown.source", "locator": "Page 1"}]])
def test_invalid_citations_do_not_mutate_fields(store, references):
    docs = documents_for(store.available_pack("example.loans"))
    before = deepcopy(docs)
    with pytest.raises(PackError):
        update_citations(docs, "fields.json", 0, references)
    assert docs == before


def test_automatic_authorship_and_copy_records_are_retained(store):
    base = store.available_pack("example.loans")
    docs = documents_for(base, custom_copy=True)
    values = {**docs["fields.json"][0], "definition": "New local definition"}
    values.pop("references")
    docs = update_field(docs, 0, values, base)
    for index, record in enumerate(docs["sources.json"]):
        if record["id"] in managed_ids(docs):
            with pytest.raises(PackError, match="Automatic"):
                update_source(docs, index, {**record, "title": "Rewritten attribution"})
            with pytest.raises(PackError, match="Automatic"):
                remove_source(docs, index)
    with pytest.raises(PackError, match="Automatic"):
        update_citations(docs, "fields.json", 0, docs["fields.json"][0]["references"][:-1])


def test_code_changes_preserve_exact_text_backups_and_active_version(store):
    base = store.available_pack("example.loans")
    path = store.packs_dir / "example-loans"
    pin = store.activate(base.id)
    original_bytes = {name: (path / name).read_bytes() for name in PACK_FILES}
    docs = update_source(documents_for(base), None, source())
    values = codes()
    values["id"] = base.code_lists[0].id
    values["references"] = deepcopy(docs["code_lists.json"][0]["references"])
    values["references"].append(dict(source="reviewed.source", locator="Page 2"))
    docs = update_code_list(docs, 0, values, base)
    docs["pack.json"]["version"] = "1.1.0"
    saved = save_draft(store, docs, path=path, expected_fingerprint=base.fingerprint)
    assert load_pack(saved.path) == saved.pack
    assert [code.value for code in saved.pack.code_lists[0].codes] == ["001", "1", " ND1\n"]
    assert saved.pack.code_lists[0].codes[-1].label == "Multiline\nlabel"
    refs = saved.pack.code_lists[0].references
    assert refs[0].locator.startswith("Background for earlier definition:")
    assert refs[-2].locator == "Page 2"
    assert base.fingerprint in refs[-1].locator
    assert next(s for s in saved.pack.sources if s.uri == LOCAL_CODES_URI).version == "1.1.0"
    assert store.snapshot(pin) == base and store.pins() == (pin,)
    assert all((saved.backup / name).read_bytes() == data for name, data in original_bytes.items())


def test_new_codes_then_category_and_missing_metadata(store):
    docs = update_code_list(documents_for(), None, codes(), None)
    local = next(source for source in docs["sources.json"] if source["uri"] == LOCAL_CODES_URI)
    assert docs["code_lists.json"][0]["references"][0]["source"] == local["id"]
    docs = update_field(
        docs,
        None,
        dict(
            id="status",
            label="Status",
            definition="Reported status",
            entity="loan",
            data_type="category",
            code_list="reviewed.codes",
            missing_code_list="reviewed.codes",
            missing_codes=["001"],
        ),
        None,
    )
    with pytest.raises(PackError, match="still used by fields status"):
        remove_code_list(docs, 0)
    changed = deepcopy(docs["code_lists.json"][0])
    changed["codes"].pop(0)
    with pytest.raises(PackError, match="missing_codes"):
        update_code_list(docs, 0, changed, None)
    # Explicitly release the missing-code selection first, then the code can be removed.
    values = {**docs["fields.json"][0], "missing_codes": []}
    values.pop("references")
    docs = update_field(docs, 0, values, None)
    docs = update_code_list(docs, 0, changed, None)
    assert docs["code_lists.json"][0]["codes"][0]["value"] == "1"
    other = update_code_list(docs, None, {**codes(), "id": "unused.codes"}, None)
    assert remove_code_list(other, 1)["code_lists.json"] == docs["code_lists.json"]


@pytest.mark.parametrize(
    "problem", ["duplicate_id", "rename", "duplicate_value", "empty", "definition", "authorship"]
)
def test_invalid_list_edits_leave_original_draft_intact(problem):
    docs = update_code_list(documents_for(), None, codes(), None)
    before = deepcopy(docs)
    values, index = deepcopy(docs["code_lists.json"][0]), 0
    if problem == "duplicate_id":
        index = None
    elif problem == "rename":
        values["id"] = "renamed.list"
    elif problem == "duplicate_value":
        values["codes"][1]["value"] = "001"
    elif problem == "empty":
        values["codes"] = []
    elif problem == "definition":
        values["codes"][0]["definition"] = ""
    else:
        values["references"] = []
    with pytest.raises(PackError):
        update_code_list(docs, index, values, None)
    assert docs == before


def test_citation_only_edit_does_not_reauthor_codes(store):
    base = store.available_pack("example.loans")
    docs = documents_for(base)
    values = deepcopy(docs["code_lists.json"][0])
    values["references"][0]["locator"] = "Corrected page 3"
    updated = update_code_list(docs, 0, values, base)
    assert updated["sources.json"] == docs["sources.json"]
    assert updated["code_lists.json"][0]["codes"] == docs["code_lists.json"][0]["codes"]
    assert updated["code_lists.json"][0]["references"][0]["locator"] == "Corrected page 3"


def test_reediting_a_new_list_does_not_claim_it_existed_in_base_pack(store):
    base = store.available_pack("example.loans")
    docs = update_code_list(documents_for(base), None, codes(), base)
    index = len(docs["code_lists.json"]) - 1
    values = deepcopy(docs["code_lists.json"][index])
    values["codes"][0]["definition"] = "Revised before this list was ever saved."
    docs = update_code_list(docs, index, values, base)
    locator = docs["code_lists.json"][index]["references"][-1]["locator"]
    assert locator == "Locally authored allowed-value list reviewed.codes"
    assert base.fingerprint not in locator
