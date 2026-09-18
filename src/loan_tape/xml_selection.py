"""Named whole-group XML selections, separate from workbook cell ranges."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from loan_tape.xml_preview import MAX_DEPTH, MAX_NAME_CHARS, MAX_NODES, MAX_PATHS

MAX_SETTINGS_BYTES = 1_048_576
MAX_DATA_SETS = 200


def xml_selection_path(sha256: str) -> Path:
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValueError("Invalid XML source identity.")
    return Path.cwd() / ".artifacts" / "xml-selections" / (sha256 + ".json")


@dataclass(frozen=True)
class XmlDataSet:
    id: str
    name: str
    group_path: tuple[str, ...]
    row: int = 1
    column: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not re.fullmatch(r"[0-9a-f]{32}", self.id):
            raise ValueError("Invalid XML data set identity.")
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 80:
            raise ValueError("Give the data set a name of 1 to 80 characters.")
        if not isinstance(self.group_path, tuple) or not 1 <= len(self.group_path) <= MAX_DEPTH:
            raise ValueError("Invalid XML record-group path.")
        if any(
            not isinstance(p, str) or not 1 <= len(p) <= MAX_NAME_CHARS for p in self.group_path
        ):
            raise ValueError("Invalid XML record-group name.")
        if (
            type(self.row) is not int
            or type(self.column) is not int
            or not (1 <= self.row <= MAX_NODES and 1 <= self.column <= MAX_PATHS)
        ):
            raise ValueError("Invalid saved XML page position.")


@dataclass(frozen=True)
class XmlSelections:
    source_sha256: str
    data_sets: tuple[XmlDataSet, ...] = ()
    active_id: str | None = None

    def __post_init__(self) -> None:
        xml_selection_path(self.source_sha256)
        if len(self.data_sets) > MAX_DATA_SETS:
            raise ValueError(f"Save at most {MAX_DATA_SETS} XML data sets per source.")
        ids = [item.id for item in self.data_sets]
        names = [item.name.strip().casefold() for item in self.data_sets]
        if len(set(ids)) != len(ids) or len(set(names)) != len(names):
            raise ValueError("Each XML data set needs its own identity and name.")
        if self.active_id is not None and self.active_id not in ids:
            raise ValueError("The active XML data set is missing.")

    @property
    def active(self) -> XmlDataSet | None:
        return next((item for item in self.data_sets if item.id == self.active_id), None)


def save_xml_selections(settings: XmlSelections) -> None:
    """Publish metadata atomically, never touching the source or Excel settings."""
    target = xml_selection_path(settings.source_sha256)
    payload = json.dumps({"schema_version": 1, **asdict(settings)}, ensure_ascii=False, indent=2)
    if len(payload.encode("utf-8")) > MAX_SETTINGS_BYTES:
        raise ValueError("XML data set settings exceed the storage limit.")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix("." + uuid4().hex + ".tmp")
    try:
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def load_xml_selections(sha256: str) -> XmlSelections:
    target = xml_selection_path(sha256)
    if not target.exists():
        return XmlSelections(sha256)
    try:
        with target.open("rb") as stream:
            raw = stream.read(MAX_SETTINGS_BYTES + 1)
        if len(raw) > MAX_SETTINGS_BYTES:
            raise ValueError("Settings exceed the storage limit.")
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {
            "schema_version",
            "source_sha256",
            "data_sets",
            "active_id",
        }:
            raise ValueError("Invalid XML settings structure.")
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ValueError("Unsupported XML settings version.")
        if data["source_sha256"] != sha256 or not isinstance(data["data_sets"], list):
            raise ValueError("XML settings do not match this source.")
        items = []
        for item in data["data_sets"]:
            if not isinstance(item, dict) or set(item) != {
                "id",
                "name",
                "group_path",
                "row",
                "column",
            }:
                raise ValueError("Invalid XML data set structure.")
            if not isinstance(item["group_path"], list):
                raise ValueError("Invalid XML record-group path.")
            items.append(
                XmlDataSet(
                    item["id"], item["name"], tuple(item["group_path"]), item["row"], item["column"]
                )
            )
        return XmlSelections(sha256, tuple(items), data["active_id"])
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        raise ValueError(f"Saved XML data sets could not be read: {error}") from error


@dataclass(frozen=True)
class SavedXmlTable:
    """Immutable analysis scope; page positions are deliberately excluded."""

    id: str
    name: str
    source_sha256: str
    group_path: tuple[str, ...]
    group_label: str
    record_count: int
    field_count: int

    def __post_init__(self) -> None:
        xml_selection_path(self.source_sha256)
        XmlDataSet(self.id, self.name, self.group_path)
        if (
            not self.group_label
            or type(self.record_count) is not int
            or type(self.field_count) is not int
            or not (1 <= self.record_count <= MAX_NODES and 1 <= self.field_count <= MAX_PATHS)
        ):
            raise ValueError("Invalid XML analysis scope.")
