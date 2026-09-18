"""Dictionary packs remain explicit, editable, reproducible, and outside current analysis."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from loan_tape import pack_format, packs
from loan_tape.pack_cli import main
from loan_tape.pack_format import PACK_FILES, PackError, load_pack
from loan_tape.packs import PackStore

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def store(tmp_path: Path) -> PackStore:
    shutil.copytree(ROOT / "packs", tmp_path / "packs")
    return PackStore(tmp_path / "packs", tmp_path / "state")


def rewrite(path: Path, transform) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    transform(data)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_starter_packs_are_valid_and_default_catalog_is_empty(store: PackStore) -> None:
    entries = store.available()
    assert {"example.loans", "esma.reporting"} <= {e.pack.id for e in entries if e.pack}
    assert all(e.error is None for e in entries)
    assert store.catalog().packs == ()
    assert store.catalog().search("balance") == ()
    assert not store.state_dir.exists()


def test_activate_reopen_deactivate_preserves_pack_files(store: PackStore) -> None:
    originals = {path: path.read_bytes() for path in store.packs_dir.rglob("*.json")}
    pin = store.activate("example.loans")
    reopened = PackStore(store.packs_dir, store.state_dir)
    field = reopened.catalog().get_field("example.loans:loan_id")
    assert field.field.data_type == "identifier"
    assert field.field.blank_allowed is False
    assert reopened.catalog().search("BALANCE")[0].field.context == (
        "currency",
        "reporting_date",
        "whole_loan_scope",
    )
    assert reopened.pins() == (pin,)
    assert reopened.deactivate("example.loans")
    assert reopened.catalog().fields == ()
    assert not reopened.deactivate("example.loans")
    assert (store.state_dir / "snapshots" / f"{pin.fingerprint}.json").exists()
    assert all(path.read_bytes() == content for path, content in originals.items())


def test_profiles_are_independent_and_activation_is_idempotent(store: PackStore) -> None:
    pin = store.activate("example.loans", "research")
    assert store.activate("example.loans", "research") == pin
    assert len(store.pins("research")) == 1
    assert store.pins() == ()
    store.activate("esma.reporting")
    store.deactivate("example.loans", "research")
    assert store.pins("research") == ()
    assert [p.id for p in store.pins()] == ["esma.reporting"]


def test_edits_require_reactivation_and_old_snapshots_remain_available(store: PackStore) -> None:
    old_pin = store.activate("example.loans")
    path = store.packs_dir / "example-loans" / "fields.json"
    rewrite(path, lambda rows: rows[0].update(label="Edited loan ID"))
    assert store.catalog().get_field("example.loans:loan_id").field.label == "Loan identifier"
    new_pin = store.activate("example.loans")
    assert new_pin.version == old_pin.version
    assert new_pin.fingerprint != old_pin.fingerprint
    assert store.catalog().get_field("example.loans:loan_id").field.label == "Edited loan ID"
    assert store.snapshot(old_pin).fields[0].label == "Loan identifier"


def test_removed_source_keeps_snapshot_and_can_be_deactivated(store: PackStore) -> None:
    store.activate("example.loans")
    shutil.rmtree(store.packs_dir / "example-loans")
    assert store.catalog().search("loan_id")
    assert store.deactivate("example.loans")


def test_broken_source_does_not_replace_active_snapshot(store: PackStore) -> None:
    store.activate("example.loans")
    state = store.state_dir / "profiles" / "default.json"
    original = state.read_bytes()
    (store.packs_dir / "example-loans" / "fields.json").write_text("{", encoding="utf-8")
    with pytest.raises(PackError, match="unavailable"):
        store.activate("example.loans")
    assert state.read_bytes() == original
    assert store.catalog().fields
    assert store.deactivate("example.loans")


def test_invalid_inactive_pack_is_visible_but_does_not_block_valid_pack(store: PackStore) -> None:
    (store.packs_dir / "esma-reporting" / "fields.json").write_text("{", encoding="utf-8")
    entries = store.available()
    assert len([entry for entry in entries if entry.error]) == 1
    assert "fields.json" in entries[0].error
    store.activate("example.loans")
    assert store.catalog().fields


def test_pack_cardinality_directory_and_cancellation_limits_are_explicit(
    store: PackStore, monkeypatch
) -> None:
    monkeypatch.setattr(pack_format, "MAX_FIELDS", 1)
    with pytest.raises(PackError, match="limit of 1 fields"):
        load_pack(store.packs_dir / "example-loans")

    monkeypatch.setattr(pack_format, "MAX_FIELDS", 2_000)
    monkeypatch.setattr(packs, "MAX_PACK_DIRECTORIES", 1)
    with pytest.raises(PackError, match="pack directories"):
        store.available()

    from threading import Event

    cancelled = Event()
    cancelled.set()
    monkeypatch.setattr(packs, "MAX_PACK_DIRECTORIES", 100)
    with pytest.raises(PackError, match="cancelled"):
        store.available(cancelled)


def test_duplicate_pack_id_has_no_directory_order_winner(store: PackStore) -> None:
    shutil.copytree(store.packs_dir / "example-loans", store.packs_dir / "another-copy")
    assert len([e for e in store.available() if e.error and "Duplicate pack ID" in e.error]) == 2
    with pytest.raises(PackError, match="ambiguous"):
        store.activate("example.loans")
    assert not store.state_dir.exists()


def test_identical_field_names_in_separate_packs_remain_distinct(store: PackStore) -> None:
    target = store.packs_dir / "custom"
    shutil.copytree(store.packs_dir / "example-loans", target)
    rewrite(target / "pack.json", lambda d: d.update(id="custom.loans"))
    rewrite(target / "fields.json", lambda rows: rows[1].update(entity="holding"))
    store.activate("example.loans")
    store.activate("custom.loans")
    matches = store.catalog().search("Balance")
    assert {match.id for match in matches} == {
        "example.loans:principal_balance",
        "custom.loans:principal_balance",
    }
    assert {match.field.entity for match in matches} == {"loan", "holding"}
    with pytest.raises(PackError, match="not in active profile"):
        store.catalog().get_field("principal_balance")


@pytest.mark.parametrize(
    "filename,transform,expected",
    [
        ("pack.json", lambda d: d.update(format_version=True), "format_version"),
        ("pack.json", lambda d: d.update(format_version=2), "format_version"),
        ("pack.json", lambda d: d.update(version="latest"), "major.minor.patch"),
        ("pack.json", lambda d: d.update(id="../outside"), "lowercase ID"),
        ("pack.json", lambda d: d.update(execute="example.py"), "unsupported keys"),
        ("pack.json", lambda d: d.update(asset_classes=[]), "asset class"),
        ("fields.json", lambda d: d.append(d[0]), "duplicate ID"),
        ("fields.json", lambda d: d[0].update(entity="unknown"), "unsupported entity"),
        ("fields.json", lambda d: d[0].update(data_type="function"), "data_type"),
        ("fields.json", lambda d: d[0].update(required="yes"), "true, false, or null"),
        ("fields.json", lambda d: d[0].update(references=[]), "source reference"),
        (
            "fields.json",
            lambda d: d[0].update(references=[{"source": "missing", "locator": "1"}]),
            "unknown source",
        ),
        ("fields.json", lambda d: d[3].update(code_list="missing"), "unknown code list"),
        ("fields.json", lambda d: d[3].pop("code_list"), "require a code_list"),
        ("fields.json", lambda d: d[0].update(code_list="loan_status"), "category fields only"),
        ("fields.json", lambda d: d[0].update(missing_codes=["ND5"]), "missing_codes"),
        ("sources.json", lambda d: d.append(d[0]), "duplicate ID"),
        ("code_lists.json", lambda d: d[0]["codes"].append(d[0]["codes"][0]), "duplicate code"),
    ],
)
def test_invalid_pack_contracts_report_file_and_reason(
    store: PackStore,
    filename: str,
    transform,
    expected: str,
) -> None:
    directory = store.packs_dir / "example-loans"
    rewrite(directory / filename, transform)
    with pytest.raises(PackError, match=expected) as error:
        load_pack(directory)
    assert filename in str(error.value)


def test_duplicate_json_keys_and_nonfinite_values_are_rejected(store: PackStore) -> None:
    directory = store.packs_dir / "example-loans"
    path = directory / "pack.json"
    original = path.read_text()
    path.write_text(
        original.replace('"format_version": 1', '"format_version": 1, "format_version": 1')
    )
    with pytest.raises(PackError, match="duplicate JSON key"):
        load_pack(directory)
    path.write_text(original.replace('"format_version": 1', '"format_version": NaN'))
    with pytest.raises(PackError, match="non-finite"):
        load_pack(directory)


def test_unsupported_rules_file_fails_instead_of_pretending_to_run_checks(store: PackStore) -> None:
    directory = store.packs_dir / "example-loans"
    (directory / "checks.json").write_text("[]")
    with pytest.raises(PackError, match="unsupported JSON files"):
        load_pack(directory)


def test_pack_code_is_never_executed(store: PackStore) -> None:
    (store.packs_dir / "example-loans" / "anything.py").write_text("raise RuntimeError('executed')")
    store.activate("example.loans")
    assert store.catalog().fields


def test_immutable_loaded_definitions_and_esma_scope(store: PackStore) -> None:
    pack = store.available_pack("esma.reporting")
    with pytest.raises(FrozenInstanceError):
        pack.fields[0].label = "modified"
    assert next(f for f in pack.fields if f.id == "tranche_principal_balance").entity == "tranche"
    assert next(f for f in pack.fields if f.id == "aggregate_tranche_balance").unit == "EUR"
    assert pack.fields[0].missing_codes == ("ND5",)
    assert len(pack.sources[0].sha256) == 64


@pytest.mark.parametrize("profile", ["../outside", "../", "/tmp", "UPPER", "a/b", "a\\b"])
def test_unsafe_profile_names_do_not_create_state(store: PackStore, profile: str) -> None:
    with pytest.raises(PackError):
        store.activate("example.loans", profile)
    assert not store.state_dir.exists()


def test_tampered_snapshot_fails_clearly_and_can_be_deactivated(store: PackStore) -> None:
    pin = store.activate("example.loans")
    path = store.state_dir / "snapshots" / f"{pin.fingerprint}.json"

    def tamper(data):
        fields = json.loads(data["files"]["fields.json"])
        fields[0]["definition"] = "tampered"
        data["files"]["fields.json"] = json.dumps(fields)

    rewrite(path, tamper)
    with pytest.raises(PackError, match="fingerprint"):
        store.catalog()
    with pytest.raises(PackError, match="fingerprint"):
        store.activate("esma.reporting")
    assert store.deactivate("example.loans")
    assert store.catalog().fields == ()


def test_corrupt_activation_file_is_not_reset(store: PackStore) -> None:
    store.activate("example.loans")
    path = store.state_dir / "profiles" / "default.json"
    path.write_text("{broken")
    with pytest.raises(PackError):
        store.activate("esma.reporting")
    assert path.read_text() == "{broken"


def test_conflicting_activation_process_fails_without_lost_update(store: PackStore) -> None:
    store.activate("example.loans")
    lock = store.state_dir / ".activation.lock"
    lock.write_text("another process")
    with pytest.raises(PackError, match="in progress"):
        store.activate("esma.reporting")
    assert lock.read_text() == "another process"
    assert [pin.id for pin in store.pins()] == ["example.loans"]


def test_failed_state_publish_retains_previous_activation(store: PackStore, monkeypatch) -> None:
    store.activate("example.loans")
    path = store.state_dir / "profiles" / "default.json"
    original = path.read_bytes()
    replace = Path.replace

    def failed_publish(self, target):
        if target == path:
            raise OSError("simulated publish failure")
        return replace(self, target)

    monkeypatch.setattr(Path, "replace", failed_publish)
    with pytest.raises(PackError, match="publish failure"):
        store.activate("esma.reporting")
    assert path.read_bytes() == original
    assert not list(store.state_dir.rglob("*.tmp"))
    assert not (store.state_dir / ".activation.lock").exists()


def test_cli_reports_edits_errors_and_missing_sources(store: PackStore, capsys) -> None:
    args = ["--packs-dir", str(store.packs_dir), "--state-dir", str(store.state_dir)]
    assert main([*args, "activate", "example.loans"]) == 0
    rewrite(
        store.packs_dir / "example-loans" / "fields.json",
        lambda rows: rows[0].update(label="Edited"),
    )
    assert main([*args, "list"]) == 0
    assert "edited on disk" in capsys.readouterr().out
    (store.packs_dir / "example-loans" / "fields.json").unlink()
    assert main([*args, "list"]) == 1
    output = capsys.readouterr().out
    assert "INVALID" in output and "active snapshot; source missing or invalid" in output
    assert main([*args, "deactivate", "example.loans"]) == 0


def test_cli_end_to_end_and_existing_help_do_not_load_invalid_packs(
    store: PackStore, tmp_path: Path
) -> None:
    def run(*arguments):
        return subprocess.run(
            [sys.executable, "-m", "loan_tape", *arguments],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

    assert run("packs", "list").returncode == 0
    assert not (tmp_path / ".artifacts").exists()
    assert run("packs", "activate", "example.loans").returncode == 0
    catalog = run("packs", "catalog")
    assert json.loads(catalog.stdout)["packs"][0]["fields"][0]["data_type"] == "identifier"
    assert run("packs", "search", "Balance").returncode == 0
    assert run("packs", "deactivate", "example.loans").returncode == 0
    (store.packs_dir / "example-loans" / "pack.json").write_text("{broken")
    assert run("--help").returncode == 0
    assert run().returncode == 0
    assert run("packs", "validate", str(store.packs_dir / "example-loans")).returncode == 1


def test_utf8_bom_and_formatting_edits_have_distinct_fingerprints(store: PackStore) -> None:
    directory = store.packs_dir / "example-loans"
    first = load_pack(directory)
    path = directory / "fields.json"
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    second = load_pack(directory)
    assert first.fields == second.fields
    assert first.fingerprint != second.fingerprint
    assert set(dict(second.files)) == set(PACK_FILES)


def test_invalid_unicode_fails_as_a_pack_error_without_activation(store: PackStore) -> None:
    directory = store.packs_dir / "example-loans"
    rewrite(directory / "fields.json", lambda rows: rows[0].update(definition=chr(0xD800)))
    with pytest.raises(PackError, match="invalid Unicode"):
        load_pack(directory)
    with pytest.raises(PackError, match="invalid Unicode"):
        store.activate("example.loans")
    assert not store.state_dir.exists()
