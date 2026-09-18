"""Source preservation and failure behavior, using only synthetic payloads."""

import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from loan_tape.intake import MAX_FILE_BYTES, IntakeError, IntakeStore


@pytest.mark.parametrize("suffix", [".csv", ".xlsx", ".xls", ".xlsm", ".xlsb", ".CSV"])
def test_bytes_names_and_identity_survive_restart(tmp_path: Path, suffix: str) -> None:
    payload = b"\xef\xbb\xbfloan_id,amount,amount\r\n000123,0,NA\r\n\x00\xff"
    original = tmp_path / ("synthetic" + suffix)
    original.write_bytes(payload)
    store = IntakeStore(tmp_path / "inputs")
    with original.open("rb") as stream:
        record = store.save(original.name, stream, len(payload))
    assert original.read_bytes() == payload
    saved_path = Path(str(store.describe(record)["saved_path"]))
    assert saved_path.read_bytes() == payload
    assert saved_path.name == original.name
    assert record["sha256"] == hashlib.sha256(payload).hexdigest()
    assert record["original_path"] is None
    assert IntakeStore(store.directory).list_files() == [record]
    manifest = json.loads((saved_path.parent / "manifest.json").read_text())
    assert manifest == record


def test_same_name_never_overwrites_previous_copy(tmp_path: Path) -> None:
    store = IntakeStore(tmp_path)
    # Rapid saves can share one Windows clock tick. Set distinct times explicitly
    # so this also tests newest-first listing without depending on disk speed.
    with patch("loan_tape.intake.datetime", wraps=datetime) as clock:
        clock.now.side_effect = [datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)]
        first = store.save("tape.csv", io.BytesIO(b"first"), 5)
        second = store.save("tape.csv", io.BytesIO(b"second"), 6)
    assert first["id"] != second["id"]
    assert Path(str(store.describe(first)["saved_path"])).read_bytes() == b"first"
    assert Path(str(store.describe(second)["saved_path"])).read_bytes() == b"second"
    assert store.list_files() == [second, first]


def test_clear_removes_only_intake_records_and_preserves_originals(tmp_path: Path) -> None:
    source = tmp_path / "original.xlsx"
    source.write_bytes(b"original")
    storage = tmp_path / "inputs"
    storage.mkdir()
    unrelated = storage / "keep.txt"
    unrelated.write_text("unrelated", encoding="utf-8")
    store = IntakeStore(storage)
    first = store.save_path(source)
    second = store.save("second.csv", io.BytesIO(b"second"), 6)

    assert store.clear() == 2
    assert not (storage / first["id"]).exists()
    assert not (storage / second["id"]).exists()
    assert unrelated.read_text(encoding="utf-8") == "unrelated"
    assert source.read_bytes() == b"original"


@pytest.mark.parametrize(
    ("name", "size"),
    [
        ("notes.pdf", 10),
        ("tape.csv.exe", 10),
        ("../tape.csv", 10),
        (r"C:\private\tape.csv", 10),
        ("tape.csv:stream", 10),
        ("NUL.csv", 10),
        ("bad\x00.csv", 10),
        ("a" * 201 + ".csv", 10),
        ("empty.csv", 0),
        ("negative.csv", -1),
        ("large.xlsx", MAX_FILE_BYTES + 1),
    ],
)
def test_rejection_has_no_filesystem_side_effects(tmp_path: Path, name: str, size: int) -> None:
    store = IntakeStore(tmp_path / "inputs")
    with pytest.raises(IntakeError):
        store.save(name, io.BytesIO(b"test"), size)
    assert not store.directory.exists()


def test_interrupted_copy_leaves_no_partial_record(tmp_path: Path) -> None:
    store = IntakeStore(tmp_path)
    with pytest.raises(IntakeError, match="interrupted"):
        store.save("tape.csv", io.BytesIO(b"short"), 10)
    assert list(tmp_path.iterdir()) == []


def test_disk_failure_leaves_no_partial_record(tmp_path: Path) -> None:
    class BrokenStream(io.BytesIO):
        def read(self, size: int = -1) -> bytes:
            raise OSError("Synthetic disk/read failure")

    store = IntakeStore(tmp_path)
    with pytest.raises(OSError):
        store.save("tape.csv", BrokenStream(), 10)
    assert list(tmp_path.iterdir()) == []


def test_corrupt_manifest_fails_clearly(tmp_path: Path) -> None:
    store = IntakeStore(tmp_path)
    record = store.save("tape.csv", io.BytesIO(b"abc"), 3)
    (tmp_path / record["id"] / "manifest.json").write_text("{broken")
    with pytest.raises(IntakeError, match="could not be read"):
        store.list_files()


def test_missing_saved_copy_fails_clearly(tmp_path: Path) -> None:
    store = IntakeStore(tmp_path)
    record = store.save("tape.csv", io.BytesIO(b"abc"), 3)
    Path(str(store.describe(record)["saved_path"])).unlink()
    with pytest.raises(IntakeError, match="could not be read"):
        store.list_files()


@pytest.mark.parametrize("suffix", [".csv", ".xlsx", ".xls", ".xlsm", ".xlsb"])
def test_desktop_copy_records_original_path_and_preserves_bytes(
    tmp_path: Path, suffix: str
) -> None:
    source = tmp_path / ("Synthetic {Q1} résumé" + suffix)
    payload = b"\xef\xbb\xbfloan_id,balance\r\n000123,0\r\n\x00\xff"
    source.write_bytes(payload)
    store = IntakeStore(tmp_path / "inputs")
    record = store.save_path(source)
    assert record["schema_version"] == 2
    assert record["original_path"] == str(source.absolute())
    assert Path(str(store.describe(record)["saved_path"])).read_bytes() == payload
    assert source.read_bytes() == payload
    source.unlink()
    assert IntakeStore(store.directory).list_files() == [record]


@pytest.mark.parametrize(
    "path", [r"\\server\share\tape.csv", r"\\?\C:\tape.csv", "file://host/tape.csv"]
)
def test_explicit_network_and_device_sources_are_rejected(tmp_path: Path, path: str) -> None:
    store = IntakeStore(tmp_path / "inputs")
    with pytest.raises(IntakeError, match="Network and device"):
        store.save_path(Path(path))
    assert not store.directory.exists()


def test_source_changed_during_copy_is_not_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "changing.csv"
    source.write_bytes(b"original")
    store = IntakeStore(tmp_path / "inputs")
    original_save = store._save

    def changed_save(*args, **kwargs):
        source.write_bytes(b"changed size")
        return original_save(*args, **kwargs)

    monkeypatch.setattr(store, "_save", changed_save)
    with pytest.raises(IntakeError, match="source changed"):
        store.save_path(source)
    assert list(store.directory.iterdir()) == []


def test_directory_is_not_accepted_as_a_workbook(tmp_path: Path) -> None:
    source = tmp_path / "folder.xlsx"
    source.mkdir()
    store = IntakeStore(tmp_path / "inputs")
    with pytest.raises(IntakeError, match="not a folder"):
        store.save_path(source)
    assert not store.directory.exists()
