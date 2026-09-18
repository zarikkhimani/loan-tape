"""Preserve source bytes and their identity without interpreting file contents."""

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, TypedDict, cast
from uuid import uuid4

SUPPORTED_EXTENSIONS = frozenset({".csv", ".xml", ".xlsx", ".xls", ".xlsm", ".xlsb"})
MAX_FILE_BYTES = 100 * 1024 * 1024


class ByteReader(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...


class IntakeError(ValueError):
    """An input cannot be safely saved."""


class SavedFile(TypedDict):
    schema_version: int
    id: str
    original_name: str
    original_path: str | None
    stored_name: str
    size_bytes: int
    sha256: str
    saved_at: str


def validate_upload(name: str, size: int) -> str:
    """Validate a filename, never a client-supplied filesystem path."""
    if (
        not name
        or len(name) > 200
        or any(character in name for character in r'/\\<>:"|?*')
        or any(ord(character) < 32 or ord(character) == 127 for character in name)
        or name.endswith((".", " "))
    ):
        raise IntakeError(
            "Use a filename of 200 characters or fewer without special path characters."
        )
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", name.split(".")[0]):
        raise IntakeError("This filename is reserved by Windows. Rename the file and try again.")
    extension = Path(name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise IntakeError(
            "Choose a CSV, XML, or Excel file (.csv, .xml, .xlsx, .xls, .xlsm, or .xlsb)."
        )
    if size <= 0:
        raise IntakeError("This file is empty. Choose a file with content.")
    if size > MAX_FILE_BYTES:
        raise IntakeError("This file is too large. The limit is 100 MB per file.")
    return extension


def reject_nonlocal_path(path: Path) -> None:
    """Reject explicit network/device paths before accessing the filesystem."""
    text = str(path).replace("\\", "/")
    if text.startswith(("//", "/??/", "/Device/")) or text.lower().startswith("file:"):
        raise IntakeError(
            "Choose a file on this computer. Network and device paths are not supported."
        )


class IntakeStore:
    """One unique folder per upload; only complete uploads become visible."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()

    def save(self, name: str, stream: ByteReader, size: int) -> SavedFile:
        """Preserve a stream whose original filesystem path is unknown."""
        return self._save(name, stream, size)

    def save_path(self, source: Path) -> SavedFile:
        """Copy a local file and record its location; reject changes during the copy."""
        reject_nonlocal_path(source)
        # Check the name before accessing a device or alternate data stream on Windows.
        validate_upload(source.name, 1)
        source = source.absolute()
        resolved = source.resolve(strict=True)
        reject_nonlocal_path(resolved)
        if not stat.S_ISREG(resolved.stat().st_mode):
            raise IntakeError("Choose a file, not a folder or a special device.")
        with resolved.open("rb") as stream:
            before = os.fstat(stream.fileno())
            validate_upload(source.name, before.st_size)

            def verify_source() -> None:
                after = os.fstat(stream.fileno())
                current = source.stat()

                # Windows ctime is creation time; fstat and stat may report it differently.
                def signature(info: os.stat_result) -> tuple[int, int, int, int, int]:
                    return (
                        info.st_dev,
                        info.st_ino,
                        info.st_size,
                        info.st_mtime_ns,
                        0 if os.name == "nt" else info.st_ctime_ns,
                    )

                if signature(before) != signature(after) or signature(before) != signature(current):
                    raise IntakeError("The source changed while copying. Close it and try again.")

            return self._save(
                source.name,
                stream,
                before.st_size,
                original_path=str(source),
                verify_source=verify_source,
            )

    def _save(
        self,
        name: str,
        stream: ByteReader,
        size: int,
        *,
        original_path: str | None = None,
        verify_source: Callable[[], None] | None = None,
    ) -> SavedFile:
        validate_upload(name, size)
        self.directory.mkdir(parents=True, exist_ok=True)
        identity = uuid4().hex
        # Staging and destination share a filesystem, so publication is an atomic rename.
        with tempfile.TemporaryDirectory(prefix=".upload-", dir=self.directory) as temporary:
            stage = Path(temporary)
            digest = hashlib.sha256()
            remaining = size
            with (stage / name).open("xb") as output:
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise IntakeError("The copy was interrupted. Please try again.")
                    output.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
            if verify_source is not None:
                verify_source()
            record: SavedFile = {
                "schema_version": 2 if original_path is not None else 1,
                "id": identity,
                "original_name": name,
                "original_path": original_path,
                "stored_name": name,
                "size_bytes": size,
                "sha256": digest.hexdigest(),
                "saved_at": datetime.now(UTC).isoformat(),
            }
            (stage / "manifest.json").write_text(
                json.dumps(record, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
            )
            stage.rename(self.directory / identity)
        return record

    def list_files(self) -> list[SavedFile]:
        records: list[SavedFile] = []
        for manifest in self.directory.glob("*/manifest.json"):
            if not re.fullmatch(r"[0-9a-f]{32}", manifest.parent.name):
                continue
            try:
                record = cast(SavedFile, json.loads(manifest.read_text(encoding="utf-8")))
                if record["schema_version"] not in {1, 2} or record["id"] != manifest.parent.name:
                    raise ValueError("Invalid manifest identity")
                if (
                    not isinstance(record["original_name"], str)
                    or not isinstance(record["stored_name"], str)
                    or not isinstance(record["size_bytes"], int)
                    or not isinstance(record["saved_at"], str)
                    or not isinstance(record["sha256"], str)
                    or record["original_name"] != record["stored_name"]
                    or (
                        record["original_path"] is not None
                        and not isinstance(record["original_path"], str)
                    )
                    or (record["schema_version"] == 2 and not record["original_path"])
                    or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"])
                ):
                    raise ValueError("Invalid manifest fields")
                datetime.fromisoformat(record["saved_at"])
                validate_upload(record["stored_name"], record["size_bytes"])
                source = manifest.parent / record["stored_name"]
                if not source.is_file() or source.stat().st_size != record["size_bytes"]:
                    raise ValueError("Saved source is missing or has changed size")
                records.append(record)
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise IntakeError(
                    "A saved file or its record could not be read. Check the intake folder."
                ) from error
        return sorted(records, key=lambda record: record["saved_at"], reverse=True)

    def describe(self, record: SavedFile) -> dict[str, object]:
        return {
            **record,
            "saved_path": str(self.directory / record["id"] / record["stored_name"]),
        }

    def clear(self) -> int:
        """Remove complete application-owned intake records, not the source files."""
        if not self.directory.exists():
            return 0
        records = self.list_files()
        for record in records:
            target = self.directory / record["id"]
            if target.is_symlink() or target.is_junction() or not target.is_dir():
                raise IntakeError("A saved-file folder is not safe to remove.")
            shutil.rmtree(target)
        try:
            self.directory.rmdir()
        except OSError:
            # A caller-supplied storage directory may contain unrelated files. Never remove them.
            pass
        return len(records)
