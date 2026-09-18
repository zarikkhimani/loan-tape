"""Bounded, source-preserving XML records for the existing preview grid."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from xml.etree.ElementTree import ParseError

from defusedxml.common import DefusedXmlException  # type: ignore[import-untyped]
from defusedxml.ElementTree import DefusedXMLParser  # type: ignore[import-untyped]

from loan_tape.inspection import (
    MAX_COLUMNS,
    MAX_ROWS,
    FilePreview,
    InspectionError,
    PreviewCell,
    check_read_cancelled,
)
from loan_tape.intake import MAX_FILE_BYTES

MAX_DEPTH = 64
MAX_NODES = 1_000_000
MAX_PATHS = 2048
MAX_ATTRIBUTES = 128
MAX_VALUE_CHARS = 1_000_000
MAX_PREVIEW_CHARS = 4_000_000
MAX_NAME_CHARS = 2048
CHUNK_BYTES = 64 * 1024
NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"
XmlPath = tuple[str, ...]


@dataclass
class _Group:
    count: int = 0
    repeated: bool = False


@dataclass
class _Node:
    path: XmlPath
    location: str
    attributes: dict[str, str]
    children: dict[str, int] = field(default_factory=dict)
    text: list[str] = field(default_factory=list)
    text_size: int = 0
    nonspace: bool = False
    preserve_space: bool = False


class _Target:
    """Parser callbacks keep a stack, never an in-memory document tree."""

    def __init__(
        self,
        cancelled: Event | None,
        selected: XmlPath | None = None,
        start_row: int = 1,
        start_column: int = 1,
        *,
        collect_preview: bool = True,
        stream_field: str | None = None,
        on_record: Callable[[int, PreviewCell], None] | None = None,
        on_full_record: Callable[[int, str, dict[str, PreviewCell]], None] | None = None,
    ) -> None:
        self.collect_preview = collect_preview
        self.stream_field = stream_field
        self.on_record = on_record
        self.on_full_record = on_full_record
        self.stream_value: PreviewCell | None = None
        self.start_row = start_row
        self.start_column = start_column
        self.cancelled = cancelled
        self.selected = selected
        self.stack: list[_Node] = []
        self.groups: dict[XmlPath, _Group] = {}
        self.namespaces: dict[str, str] = {}
        self.nodes = 0
        self.records = 0
        self.fields: dict[str, int] = {}
        self.rows: list[dict[str, PreviewCell]] = []
        self.locations: list[str] = []
        self.active: dict[str, PreviewCell] | None = None
        self.record_depth = 0
        self.preview_chars = 0
        self.record_chars = 0
        self.problem: str | None = None

    @property
    def visible_record(self) -> bool:
        return self.collect_preview and self.start_row <= self.records < self.start_row + MAX_ROWS

    def name(self, tag: str) -> str:
        if len(tag) > MAX_NAME_CHARS:
            raise InspectionError("XML name or namespace exceeds the preview limit.")
        if not tag.startswith("{"):
            return tag
        uri, local = tag[1:].split("}", 1)
        if uri not in self.namespaces:
            if len(self.namespaces) >= MAX_PATHS:
                raise InspectionError("XML has too many namespaces to preview.")
            self.namespaces[uri] = f"ns{len(self.namespaces) + 1}"
        return f"{self.namespaces[uri]}:{local}"

    def label(self, path: XmlPath) -> str:
        return "/" + "/".join(self.name(part) for part in path)

    def start(self, tag: str, attributes: dict[str, str]) -> None:
        check_read_cancelled(self.cancelled)
        self.nodes += 1
        if self.nodes > MAX_NODES or len(self.stack) >= MAX_DEPTH:
            raise InspectionError("XML exceeds the node or nesting limit; no preview was produced.")
        if len(attributes) > MAX_ATTRIBUTES:
            raise InspectionError("XML element has too many attributes to preview.")
        name = self.name(tag)
        for key, value in attributes.items():
            self.name(key)
            if len(value) > MAX_VALUE_CHARS:
                raise InspectionError("XML attribute exceeds the value-size limit.")
        parent = self.stack[-1] if self.stack else None
        occurrence = 1
        if parent:
            occurrence = parent.children.get(tag, 0) + 1
            parent.children[tag] = occurrence
        path = (*parent.path, tag) if parent else (tag,)
        if path not in self.groups:
            if len(self.groups) >= MAX_PATHS:
                raise InspectionError("XML has too many distinct paths to preview.")
            self.groups[path] = _Group()
        group = self.groups[path]
        group.count += 1
        group.repeated |= occurrence > 1
        location = f"{parent.location if parent else ''}/{name}[{occurrence}]"
        space = attributes.get("{http://www.w3.org/XML/1998/namespace}space")
        preserve = space == "preserve" or (
            space is None and parent is not None and parent.preserve_space
        )
        node = _Node(path, location, attributes, preserve_space=preserve)
        self.stack.append(node)
        if path == self.selected:
            self.records += 1
            self.record_depth = len(self.stack)
            self.active = {}
            self.stream_value = None
            self.record_chars = 0
            if self.visible_record:
                self.rows.append(self.active)
                self.locations.append(location)
        elif self.active is not None and occurrence > 1:
            self.problem = self.problem or (
                f"Repeated child records at {location}. Choose that narrower record group; "
                "nested repetitions are not flattened in this preview."
            )
        if self.active is not None:
            for key, value in attributes.items():
                self.add(node, "@" + self.name(key), value, "Present")

    def data(self, value: str) -> None:
        check_read_cancelled(self.cancelled)
        if not self.stack:
            return
        node = self.stack[-1]
        node.text_size += len(value)
        if node.text_size > MAX_VALUE_CHARS:
            raise InspectionError("XML text exceeds the value-size limit; no preview was produced.")
        node.nonspace |= bool(value.strip())
        if self.active is not None and (self.visible_record or self.on_full_record is not None):
            if self.on_full_record is not None:
                self.record_chars += len(value)
                if self.record_chars > MAX_PREVIEW_CHARS:
                    raise InspectionError("One XML record exceeds the ordering memory limit.")
            self.preview_chars += len(value)
            if self.visible_record and self.preview_chars > MAX_PREVIEW_CHARS:
                raise InspectionError("XML preview text exceeds the memory limit.")
            node.text.append(value)
        elif self.active is not None and self.stream_field == self.field_key(node, ""):
            node.text.append(value)

    def field_key(self, node: _Node, suffix: str) -> str:
        relative = node.path[self.record_depth :]
        parts = [self.name(part) for part in relative]
        if suffix:
            parts.append(suffix)
        return "/".join(parts) or "#text"

    def add(self, node: _Node, suffix: str, text: str, state: str) -> None:
        assert self.active is not None
        key = self.field_key(node, suffix)
        if key not in self.fields:
            if len(self.fields) >= MAX_PATHS:
                raise InspectionError("XML record group has too many fields to preview.")
            self.fields[key] = len(self.fields)
        if key == self.stream_field:
            self.stream_value = PreviewCell(
                text, source_path=node.location + ("/" + suffix if suffix else ""), presence=state
            )
        visible_field = self.visible_record and (
            self.start_column - 1 <= self.fields[key] < self.start_column - 1 + MAX_COLUMNS
        )
        if self.on_full_record is not None or visible_field:
            if suffix and self.on_full_record is not None:
                self.record_chars += len(text)
                if self.record_chars > MAX_PREVIEW_CHARS:
                    raise InspectionError("One XML record exceeds the ordering memory limit.")
            if suffix and visible_field:
                self.preview_chars += len(text)
                if self.preview_chars > MAX_PREVIEW_CHARS:
                    raise InspectionError("XML preview text exceeds the memory limit.")
            self.active[key] = PreviewCell(
                text, source_path=node.location + ("/" + suffix if suffix else ""), presence=state
            )

    def end(self, tag: str) -> None:
        check_read_cancelled(self.cancelled)
        node = self.stack.pop()
        if self.active is not None:
            nil = node.attributes.get(NIL) in {"true", "1"}
            if node.children and (node.nonspace or (node.preserve_space and node.text_size)):
                self.problem = self.problem or (
                    f"Mixed text and child elements at {node.location}. "
                    "This structure cannot be represented as preview columns."
                )
            if nil and (node.children or node.text_size):
                self.problem = self.problem or f"A nil element contains content at {node.location}."
            if not node.children:
                state = (
                    "Explicit nil" if nil else "Empty element" if not node.text_size else "Present"
                )
                self.add(node, "", "".join(node.text), state)
            if node.path == self.selected:
                if self.on_record is not None:
                    self.on_record(
                        self.records,
                        self.stream_value
                        or PreviewCell(
                            "",
                            source_path=f"{node.location} (absent field: {self.stream_field})",
                            presence="Absent",
                        ),
                    )
                if self.on_full_record is not None:
                    self.on_full_record(self.records, node.location, self.active)
                self.active = None

    def close(self) -> None:
        return None


def _parse(path: Path, target: _Target) -> str:
    parser = DefusedXMLParser(
        target=target, forbid_dtd=True, forbid_entities=True, forbid_external=True
    )
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if before.st_size > MAX_FILE_BYTES:
                raise InspectionError("XML exceeds the 100 MB file limit.")
            while True:
                check_read_cancelled(target.cancelled)
                chunk = stream.read(CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise InspectionError("XML exceeds the 100 MB file limit.")
                digest.update(chunk)
                parser.feed(chunk)
            parser.close()
            after = path.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino, before.st_dev) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ino,
                after.st_dev,
            ):
                raise InspectionError("The XML source changed while reading. Add it again.")
    except DefusedXmlException as error:
        raise InspectionError(
            "XML DTDs and entity declarations are not supported or loaded."
        ) from error
    except (ParseError, UnicodeError, LookupError, ValueError) as error:
        if isinstance(error, InspectionError):
            raise
        raise InspectionError(f"Could not parse XML: {error}") from error
    check_read_cancelled(target.cancelled)
    return digest.hexdigest()


def read_xml_preview(
    path: Path,
    group: str | None = None,
    cancelled: Event | None = None,
    *,
    start_row: int = 1,
    start_column: int = 1,
    group_path: XmlPath | None = None,
    source_sha256: str | None = None,
) -> FilePreview:
    if (
        type(start_row) is not int
        or type(start_column) is not int
        or not (1 <= start_row <= MAX_NODES and 1 <= start_column <= MAX_PATHS)
    ):
        raise InspectionError("Choose positive record and field numbers within the XML limits.")
    discovery = _Target(cancelled)
    identity = _parse(path, discovery)
    if source_sha256 is not None and identity != source_sha256:
        raise InspectionError("The XML source changed. Close this preview and add the file again.")
    candidates = [key for key, value in discovery.groups.items() if value.repeated]
    if not candidates:
        candidates = [next(iter(discovery.groups))]
    options = {discovery.label(key): key for key in candidates}
    if group_path is not None:
        if group_path not in candidates:
            raise InspectionError("The saved XML record group is unavailable in this source.")
        group = discovery.label(group_path)
    selected = group if group is not None else next(iter(options)) if len(options) == 1 else None
    note = (
        "XML values are decoded text; identifiers and whitespace are retained. "
        "No schema validation or financial interpretation. "
        "Each page shows up to 20 records and 10 fields; other groups are separate."
    )
    if discovery.namespaces:
        note += " Namespaces: " + "; ".join(
            f"{alias} = {uri}" for uri, alias in discovery.namespaces.items()
        )
    if selected is None:
        return FilePreview(
            (),
            0,
            False,
            False,
            reading_note=note,
            record_groups=tuple(options),
            source_sha256=identity,
            record_group_paths=tuple(candidates),
        )
    if selected not in options:
        raise InspectionError("The selected XML record group is unavailable. Reopen Inspect file.")
    target = _Target(cancelled, options[selected], start_row, start_column)
    if _parse(path, target) != identity:
        raise InspectionError("The XML source changed between discovery and preview. Add it again.")
    if not target.problem and (start_row > target.records or start_column > len(target.fields)):
        raise InspectionError("Choose a record and field inside the selected XML group.")
    columns = tuple(target.fields)[start_column - 1 : start_column - 1 + MAX_COLUMNS]
    rows = tuple(
        tuple(
            values.get(
                key,
                PreviewCell("", source_path=f"{location} (absent field: {key})", presence="Absent"),
            )
            for key in columns
        )
        for values, location in zip(target.rows, target.locations, strict=True)
    )
    return FilePreview(
        rows=() if target.problem else rows,
        column_count=0 if target.problem else len(columns),
        more_rows=target.records >= start_row + MAX_ROWS,
        more_columns=len(target.fields) >= start_column + MAX_COLUMNS,
        start_row=start_row,
        start_column=start_column,
        field_count=len(target.fields),
        source_sha256=identity,
        record_group_paths=tuple(candidates),
        column_labels=columns,
        reading_note=note,
        record_groups=tuple(options),
        selected_record_group=selected,
        record_count=target.records,
        record_group_error=target.problem,
    )
