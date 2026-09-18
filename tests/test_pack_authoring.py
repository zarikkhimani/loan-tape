"""Draft publication preserves active definitions, previous files, and source attribution."""

import json
import shutil
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

import pytest

from loan_tape.pack_authoring import LOCAL_URI, documents_for, save_draft, update_field
from loan_tape.pack_format import PACK_FILES, PackError, load_pack
from loan_tape.packs import PackStore


@pytest.fixture
def store(tmp_path):
    shutil.copytree(Path(__file__).resolve().parents[1] / "packs", tmp_path / "packs")
    return PackStore(tmp_path / "packs", tmp_path / "state")


def changed(pack):
    docs = documents_for(pack)
    values = deepcopy(docs["fields.json"][0])
    values.pop("references")
    values["definition"] = "A locally reviewed definition for the custom workflow."
    return update_field(docs, 0, values, pack)


def test_new_pack_and_local_field_creation_are_inactive(store):
    docs = documents_for()
    docs["pack.json"].update(id="custom.clo", name="Custom CLO", description="Local field meanings")
    field = dict(
        id="loan_id",
        label="Loan ID",
        definition="Identifier preserved as text.",
        entity="loan",
        data_type="identifier",
    )
    docs = update_field(docs, None, field, None)
    saved = save_draft(store, docs)
    assert saved.path == store.packs_dir / "custom.clo"
    assert saved.backup is None
    assert load_pack(saved.path) == saved.pack
    assert store.pins() == ()
    assert not (store.state_dir / "profiles").exists()
    assert saved.pack.sources[0].uri == LOCAL_URI
    assert saved.pack.fields[0].references[0].source == saved.pack.sources[0].id


def test_custom_copy_keeps_original_files_codes_and_provenance(store):
    source = store.available_pack("esma.reporting")
    docs = documents_for(source, custom_copy=True)
    docs["pack.json"]["id"] = "custom.reporting"
    saved = save_draft(store, docs)
    assert saved.pack.fields == source.fields
    assert saved.pack.code_lists == source.code_lists
    assert source.fingerprint in saved.pack.sources[-1].uri
    assert store.available_pack(source.id) == source
    assert store.pins() == ()


def test_edit_preserves_old_files_and_pinned_definitions(store):
    original = store.available_pack("example.loans")
    path = store.packs_dir / "example-loans"
    before = {name: (path / name).read_bytes() for name in PACK_FILES}
    pin = store.activate(original.id)
    docs = changed(original)
    docs["pack.json"]["version"] = "1.1.0"
    saved = save_draft(store, docs, path=path, expected_fingerprint=original.fingerprint)
    assert saved.backup.parent == store.packs_dir / ".history"
    assert all((saved.backup / name).read_bytes() == data for name, data in before.items())
    assert store.pins() == (pin,)
    assert store.snapshot(pin) == original
    assert (
        saved.pack.fields[0].references[0].locator.startswith("Background for earlier definition")
    )
    local = next(source for source in saved.pack.sources if source.uri == LOCAL_URI)
    assert local.version == "1.1.0"
    assert saved.pack.fields[0].references[-1].source == local.id
    assert original.fingerprint in saved.pack.fields[0].references[-1].locator
    assert len(store.available()) == len(list(store.packs_dir.glob("*/pack.json")))
    with pytest.raises(PackError, match="changed since they were displayed"):
        store.activate(original.id, expected_fingerprint=original.fingerprint)
    assert store.activate(original.id, expected_fingerprint=saved.pack.fingerprint) != pin


def test_stale_editor_cannot_overwrite_external_changes(store):
    original = store.available_pack("example.loans")
    path = store.packs_dir / "example-loans"
    manifest = path / "pack.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["name"] = "Edited elsewhere"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    external = load_pack(path)
    with pytest.raises(PackError, match="changed since editing began"):
        save_draft(store, changed(original), path=path, expected_fingerprint=original.fingerprint)
    assert load_pack(path) == external
    assert not (store.packs_dir / ".history").exists()
    docs = changed(original)
    docs["pack.json"]["id"] = "custom.saved-draft"
    assert save_draft(store, docs).pack.id == "custom.saved-draft"


@pytest.mark.parametrize("problem", ["invalid", "duplicate", "escape", "rename", "extra"])
def test_invalid_edits_do_not_replace_files(store, problem):
    original = store.available_pack("example.loans")
    path = store.packs_dir / "example-loans"
    docs = changed(original)
    target = path
    if problem == "invalid":
        docs["fields.json"][0]["data_type"] = "unknown"
    elif problem == "duplicate":
        target = None
    elif problem == "escape":
        target = path.parent / ".." / "outside"
    elif problem == "rename":
        docs["pack.json"]["id"] = "changed.identity"
    else:
        (path / "instructions.txt").write_text("Preserve this extra file", encoding="utf-8")
    with pytest.raises(PackError):
        save_draft(store, docs, path=target, expected_fingerprint=original.fingerprint)
    assert store.available_pack(original.id) == original
    assert not list(store.packs_dir.glob(".draft-*"))


@pytest.mark.parametrize("failure", ["write", "publish", "restore"])
def test_failed_publication_keeps_recoverable_originals(store, monkeypatch, failure):
    original = store.available_pack("example.loans")
    path = store.packs_dir / "example-loans"
    pin = store.activate(original.id)
    write, rename = Path.write_bytes, Path.rename

    def broken_write(self, data):
        if (
            failure == "write"
            and self.parent.name.startswith(".draft-")
            and self.name == "fields.json"
        ):
            raise OSError("simulated file write failure")
        return write(self, data)

    def broken_rename(self, target):
        if failure != "write" and self.name.startswith(".draft-"):
            raise OSError("simulated publication failure")
        if failure == "restore" and self.parent.name == ".history":
            raise OSError("simulated restore failure")
        return rename(self, target)

    monkeypatch.setattr(Path, "write_bytes", broken_write)
    monkeypatch.setattr(Path, "rename", broken_rename)
    with pytest.raises(PackError, match="failure|preserved"):
        save_draft(store, changed(original), path=path, expected_fingerprint=original.fingerprint)
    assert store.snapshot(pin) == original
    assert not (store.state_dir / ".activation.lock").exists()
    if failure == "restore":
        (backup,) = (store.packs_dir / ".history").iterdir()
        assert load_pack(backup) == original
        assert len(list(store.packs_dir.glob(".draft-*"))) == 1
    else:
        assert load_pack(path) == original
        assert not list(store.packs_dir.glob(".draft-*"))


def test_editor_and_activation_share_update_lock(store):
    original = store.available_pack("example.loans")
    with store._lock():
        with pytest.raises(PackError, match="in progress"):
            save_draft(
                store,
                changed(original),
                path=store.packs_dir / "example-loans",
                expected_fingerprint=original.fingerprint,
            )
        with pytest.raises(PackError, match="in progress"):
            store.activate(original.id)
    assert store.available_pack(original.id) == original
    assert not store.pins()


def test_invalid_field_does_not_mutate_the_draft(store):
    base = store.available_pack("example.loans")
    docs = documents_for(base)
    before = deepcopy(docs)
    with pytest.raises(PackError):
        update_field(docs, None, dict(id="invalid"), base)
    assert docs == before


def test_activation_rejects_a_source_change_before_lock_acquisition(store, monkeypatch):
    original = store.available_pack("example.loans")
    lock = store._lock

    @contextmanager
    def changed_before_lock():
        with lock():
            manifest = store.packs_dir / "example-loans" / "pack.json"
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["name"] = "Another saved version"
            manifest.write_text(json.dumps(data), encoding="utf-8")
            yield

    monkeypatch.setattr(store, "_lock", changed_before_lock)
    with pytest.raises(PackError, match="changed during activation"):
        store.activate(original.id)
    assert not store.pins()
