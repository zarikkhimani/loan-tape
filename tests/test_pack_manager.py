"""The management view never substitutes editable definitions for saved versions."""

import json
import shutil
from pathlib import Path

import pytest

from loan_tape.pack_format import PackError
from loan_tape.pack_manager import field_text, inspect_packs
from loan_tape.packs import PackStore


@pytest.fixture
def store(tmp_path: Path) -> PackStore:
    shutil.copytree(Path(__file__).resolve().parents[1] / "packs", tmp_path / "packs")
    return PackStore(tmp_path / "packs", tmp_path / "state")


def test_inventory_is_read_only_and_displays_distinct_versions(store: PackStore) -> None:
    inventory = inspect_packs(store, "default")
    assert all(row.status == "Inactive" for row in inventory.rows)
    assert not store.state_dir.exists()
    pin = store.activate("example.loans")
    path = store.packs_dir / "example-loans" / "fields.json"
    fields = json.loads(path.read_text(encoding="utf-8"))
    fields[0]["label"] = "Edited label"
    path.write_text(json.dumps(fields), encoding="utf-8")
    row = next(row for row in inspect_packs(store, "default").rows if row.pack_id == pin.id)
    assert row.status == "Active — edits available"
    assert row.can_activate
    assert row.active.fields[0].label == "Loan identifier"
    assert row.editable.fields[0].label == "Edited label"
    with pytest.raises(PackError, match="changed since they were displayed"):
        store.activate(pin.id, expected_fingerprint=pin.fingerprint)
    assert store.pins() == (pin,)
    assert store.activate(pin.id, expected_fingerprint=row.editable.fingerprint) != pin


@pytest.mark.parametrize("broken", ["source", "snapshot", "folder-root", "duplicate"])
def test_inventory_retains_active_selection_for_repair(store: PackStore, broken: str) -> None:
    pin = store.activate("example.loans")
    if broken == "source":
        (store.packs_dir / "example-loans" / "fields.json").write_text("{", encoding="utf-8")
    elif broken == "snapshot":
        (store.state_dir / "snapshots" / f"{pin.fingerprint}.json").unlink()
    elif broken == "folder-root":
        shutil.rmtree(store.packs_dir)
        store.packs_dir.write_text("not a directory", encoding="utf-8")
    else:
        shutil.copytree(store.packs_dir / "example-loans", store.packs_dir / "duplicate")
    inventory = inspect_packs(store, "default")
    rows = [row for row in inventory.rows if row.pin == pin]
    assert rows
    assert all(not row.can_activate for row in rows)
    if broken == "snapshot":
        assert rows[0].active is None and rows[0].active_error
        assert rows[0].editable is not None
    else:
        assert all(row.active is not None for row in rows)
    if broken == "folder-root":
        assert inventory.source_error
    store.deactivate(pin.id)
    assert store.catalog().packs == ()


def test_corrupt_profile_is_not_presented_as_empty(store: PackStore) -> None:
    store.activate("example.loans")
    (store.state_dir / "profiles" / "default.json").write_text("{}", encoding="utf-8")
    with pytest.raises(PackError):
        inspect_packs(store, "default")


def test_field_details_include_only_applicable_missing_codes(store: PackStore) -> None:
    pack = store.available_pack("esma.reporting")
    field = next(field for field in pack.fields if field.id == "pool_addition_date")
    text = field_text(pack, field)
    assert "Expected type: date" in text
    assert "Required: Not specified / conditional" in text
    assert "ND5 —" in text
    assert "ND4 —" not in text
    assert field.references[0].locator in text
    assert pack.sources[0].title in text
