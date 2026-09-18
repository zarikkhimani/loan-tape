"""Independent dictionary catalog and explicit, snapshot-pinned activation profiles."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from threading import Event
from uuid import uuid4

from loan_tape.pack_format import (
    VERSION_PATTERN,
    Field,
    Pack,
    PackError,
    check_pack_cancelled,
    identifier,
    load_pack,
    load_pack_files,
    object_keys,
    parse_json,
    read_text,
)

MAX_PACK_DIRECTORIES = 100
MAX_ACTIVE_PACKS = 100
MAX_PROFILE_FILES = 100


@dataclass(frozen=True)
class PackEntry:
    path: Path
    pack: Pack | None
    error: str | None = None


@dataclass(frozen=True)
class PackPin:
    id: str
    version: str
    fingerprint: str


@dataclass(frozen=True)
class CatalogField:
    id: str
    pack_id: str
    pack_version: str
    field: Field


@dataclass(frozen=True)
class Catalog:
    profile: str
    packs: tuple[Pack, ...]

    @property
    def fields(self) -> tuple[CatalogField, ...]:
        return tuple(
            CatalogField(f"{pack.id}:{field.id}", pack.id, pack.version, field)
            for pack in self.packs
            for field in pack.fields
        )

    def search(self, query: str) -> tuple[CatalogField, ...]:
        """Return every match; aliases never automatically select or merge a meaning."""
        term = query.casefold()
        return tuple(
            item
            for item in self.fields
            if term
            in " ".join(
                (
                    item.id,
                    item.field.label,
                    item.field.definition,
                    *item.field.aliases,
                )
            ).casefold()
        )

    def get_field(self, field_id: str) -> CatalogField:
        for item in self.fields:
            if item.id == field_id:
                return item
        raise PackError(f"Field {field_id!r} is not in active profile {self.profile!r}.")


def discover_packs(root: Path, cancelled: Event | None = None) -> tuple[PackEntry, ...]:
    """Report invalid directories individually, including duplicate pack IDs."""
    if not root.exists():
        return ()
    if not root.is_dir():
        raise PackError(f"{root}: expected a packs directory.")
    entries = []
    try:
        directories = tuple(
            path
            for path in sorted(root.iterdir())
            if not path.name.startswith(".") and path.is_dir()
        )
        if len(directories) > MAX_PACK_DIRECTORIES:
            raise PackError(
                f"{root}: exceeds the limit of {MAX_PACK_DIRECTORIES} pack directories."
            )
        for path in directories:
            check_pack_cancelled(cancelled)
            try:
                entries.append(PackEntry(path, load_pack(path, cancelled)))
            except PackError as error:
                entries.append(PackEntry(path, None, str(error)))
    except OSError as error:
        raise PackError(f"{root}: {error}") from error
    counts = Counter(entry.pack.id for entry in entries if entry.pack is not None)
    return tuple(
        replace(entry, error=f"Duplicate pack ID {entry.pack.id!r}; keep one directory per ID.")
        if entry.pack is not None and counts[entry.pack.id] > 1
        else entry
        for entry in entries
    )


class PackStore:
    """Activation changes catalog membership only, never existing inspection behavior."""

    def __init__(self, packs_dir: Path, state_dir: Path) -> None:
        self.packs_dir, self.state_dir = packs_dir, state_dir

    def available(self, cancelled: Event | None = None) -> tuple[PackEntry, ...]:
        return discover_packs(self.packs_dir, cancelled)

    def available_pack(self, pack_id: str) -> Pack:
        identifier(pack_id, "pack ID")
        entries = self.available()
        matches = [
            entry for entry in entries if entry.pack is not None and entry.pack.id == pack_id
        ]
        if len(matches) == 1 and matches[0].error is None:
            assert matches[0].pack is not None
            return matches[0].pack
        errors = "; ".join(entry.error for entry in entries if entry.error)
        raise PackError(f"Pack {pack_id!r} is unavailable or ambiguous. {errors}".strip())

    def _profile_path(self, profile: str) -> Path:
        return self.state_dir / "profiles" / f"{identifier(profile, 'profile')}.json"

    def pins(self, profile: str = "default", cancelled: Event | None = None) -> tuple[PackPin, ...]:
        path = self._profile_path(profile)
        if not path.exists():
            return ()
        data = object_keys(
            parse_json(read_text(path), str(path)),
            {"format_version", "profile", "active"},
            set(),
            str(path),
        )
        if type(data["format_version"]) is not int or data["format_version"] != 1:
            raise PackError(f"{path}: unsupported activation format_version.")
        if data["profile"] != profile or not isinstance(data["active"], list):
            raise PackError(f"{path}: invalid profile or active pack list.")
        if len(data["active"]) > MAX_ACTIVE_PACKS:
            raise PackError(f"{path}: exceeds the limit of {MAX_ACTIVE_PACKS} active packs.")
        result, seen = [], set[str]()
        for row in data["active"]:
            check_pack_cancelled(cancelled)
            item = object_keys(row, {"id", "version", "fingerprint"}, set(), str(path))
            pack_id = identifier(item["id"], str(path))
            version, fingerprint = item["version"], item["fingerprint"]
            if pack_id in seen:
                raise PackError(f"{path}: duplicate active pack {pack_id!r}.")
            if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
                raise PackError(f"{path}: invalid pinned version.")
            if not isinstance(fingerprint, str) or not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
                raise PackError(f"{path}: invalid pinned fingerprint.")
            seen.add(pack_id)
            result.append(PackPin(pack_id, version, fingerprint))
        return tuple(sorted(result, key=lambda pin: pin.id))

    def snapshot(self, pin: PackPin, cancelled: Event | None = None) -> Pack:
        if not re.fullmatch(r"[a-f0-9]{64}", pin.fingerprint):
            raise PackError("Invalid snapshot fingerprint.")
        path = self.state_dir / "snapshots" / f"{pin.fingerprint}.json"
        data = object_keys(
            parse_json(read_text(path, limit=64 * 1024 * 1024), str(path)),
            {"format_version", "files"},
            set(),
            str(path),
        )
        if type(data["format_version"]) is not int or data["format_version"] != 1:
            raise PackError(f"{path}: unsupported snapshot format_version.")
        if not isinstance(data["files"], dict):
            raise PackError(f"{path}: invalid snapshot files.")
        pack = load_pack_files(data["files"], str(path), cancelled)
        if PackPin(pack.id, pack.version, pack.fingerprint) != pin:
            raise PackError(
                f"{path}: snapshot identity or fingerprint does not match its activation."
            )
        return pack

    def catalog(self, profile: str = "default") -> Catalog:
        return Catalog(profile, tuple(self.snapshot(pin) for pin in self.pins(profile)))

    def profiles(self, cancelled: Event | None = None) -> tuple[str, ...]:
        folder = self.state_dir / "profiles"
        paths = tuple(folder.glob("*.json"))
        if len(paths) > MAX_PROFILE_FILES:
            raise PackError(f"{folder}: exceeds the limit of {MAX_PROFILE_FILES} profiles.")
        names = {"default"}
        for path in paths:
            check_pack_cancelled(cancelled)
            names.add(identifier(path.stem, "profile"))
        return tuple(sorted(names))

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        path = self.state_dir / ".activation.lock"
        try:
            stream = path.open("x", encoding="utf-8")
        except FileExistsError as error:
            raise PackError(
                f"{path}: another activation update is in progress. If a process crashed, "
                "remove this lock only after confirming no pack update is running."
            ) from error
        try:
            with stream:
                stream.write("Loan Tape pack activation update\n")
                stream.flush()
                yield
        finally:
            path.unlink()

    @staticmethod
    def _write(path: Path, data: object) -> None:
        payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(payload, encoding="utf-8")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def activate(
        self, pack_id: str, profile: str = "default", *, expected_fingerprint: str | None = None
    ) -> PackPin:
        path = self._profile_path(profile)
        pack = self.available_pack(pack_id)
        if expected_fingerprint is not None and pack.fingerprint != expected_fingerprint:
            raise PackError(
                "Pack files changed since they were displayed. Refresh and review before activating."
            )
        pin = PackPin(pack.id, pack.version, pack.fingerprint)
        try:
            with self._lock():
                # Editors share this lock. Recheck after acquiring it so a folder
                # publication cannot result in activating mixed file versions.
                if self.available_pack(pack_id).fingerprint != pack.fingerprint:
                    raise PackError("Pack files changed during activation. Refresh and try again.")
                pins = self.pins(profile)
                for existing in pins:
                    if existing.id != pack_id:
                        self.snapshot(existing)
                snapshot = self.state_dir / "snapshots" / f"{pin.fingerprint}.json"
                if snapshot.exists():
                    self.snapshot(pin)
                else:
                    self._write(snapshot, {"format_version": 1, "files": dict(pack.files)})
                    self.snapshot(pin)
                updated = sorted((*(p for p in pins if p.id != pack_id), pin), key=lambda p: p.id)
                self._write(
                    path,
                    {
                        "format_version": 1,
                        "profile": profile,
                        "active": [asdict(p) for p in updated],
                    },
                )
            return pin
        except OSError as error:
            raise PackError(f"Could not activate {pack_id!r}: {error}") from error

    def deactivate(self, pack_id: str, profile: str = "default") -> bool:
        identifier(pack_id, "pack ID")
        path = self._profile_path(profile)
        try:
            with self._lock():
                pins = self.pins(profile)
                updated = [pin for pin in pins if pin.id != pack_id]
                if len(updated) == len(pins):
                    return False
                # Can deactivate even if the source or snapshot was deleted or corrupted.
                self._write(
                    path,
                    {
                        "format_version": 1,
                        "profile": profile,
                        "active": [asdict(pin) for pin in updated],
                    },
                )
                return True
        except OSError as error:
            raise PackError(f"Could not deactivate {pack_id!r}: {error}") from error
