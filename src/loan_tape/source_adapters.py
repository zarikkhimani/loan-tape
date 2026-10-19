"""Saved CSV/XML scopes and mappings feeding the existing reviewed text contracts."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from threading import Event
from typing import Any
from uuid import uuid4

from loan_tape._date_json import canonical
from loan_tape.column_definitions import ColumnDefinition, _definition_from_dict, snapshot_field
from loan_tape.pack_format import object_keys, parse_json, read_text
from loan_tape.packs import PackStore
from loan_tape.source_records import (
    CSV_DELIMITERS,
    CSV_ENCODINGS,
    MAX_FIELDS,
    SourceRecords,
    check_xml_table,
    read_csv_records,
    read_xml_records,
)
from loan_tape.text_cleanup import TextCleanupSettings, preview_text_cleanup
from loan_tape.text_rule_types import ExactRulesSettings
from loan_tape.text_rules import preview_exact_rules
from loan_tape.transformations import (
    FOUNDATION_VERSION,
    MAX_CELLS,
    TransformationApproval,
    TransformationPreview,
    TransformationRevision,
    TransformationSnapshot,
    _bounded_json,
    apply_transformation,
    replay_revision,
)
from loan_tape.workbook_index import _digest, check_cancelled
from loan_tape.xml_selection import SavedXmlTable

MAX_SETTINGS_BYTES = 8 * 1024 * 1024
MAX_SCOPES = 200


def _metadata(text: str) -> dict[str, Any]:
    value = object_keys(
        parse_json(text, "source scope"),
        {
            "format",
            "source_sha256",
            "options",
            "record_count",
            "field_count",
            "headers",
            "first_data_record",
            "header_evidence",
        },
        set(),
        "source scope",
    )
    if (
        not isinstance(value["format"], str)
        or value["format"] not in {"csv", "xml"}
        or not isinstance(value["source_sha256"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", value["source_sha256"])
    ):
        raise ValueError("Invalid source format or identity.")
    rows, columns, first = (
        value[key] for key in ("record_count", "field_count", "first_data_record")
    )
    if (
        any(type(item) is not int for item in (rows, columns, first))
        or not 1 <= columns <= MAX_FIELDS
        or not 1 <= rows * columns <= MAX_CELLS
        or not 1 <= first <= rows
        or first not in {1, 2}
    ):
        raise ValueError("Invalid complete source population.")
    if (
        not isinstance(value["headers"], list)
        or len(value["headers"]) != columns
        or any(not isinstance(item, str) for item in value["headers"])
    ):
        raise ValueError("Invalid complete field labels.")
    if value["format"] == "csv":
        options = object_keys(
            value["options"],
            {"encoding", "delimiter", "header", "quotechar", "doublequote", "strict"},
            set(),
            "CSV settings",
        )
        if (
            options["encoding"] not in CSV_ENCODINGS
            or options["delimiter"] not in CSV_DELIMITERS
            or type(options["header"]) is not bool
            or options["quotechar"] != '"'
            or options["doublequote"] is not True
            or options["strict"] is not True
            or first != (2 if options["header"] else 1)
        ):
            raise ValueError("Invalid explicit CSV conventions.")
        header_evidence = value["header_evidence"]
        if (
            options["header"]
            and (not isinstance(header_evidence, list) or len(header_evidence) != columns)
        ) or (not options["header"] and header_evidence is not None):
            raise ValueError("Invalid CSV header evidence.")
    else:
        options = object_keys(
            value["options"], {"group_path", "group_label", "namespaces"}, set(), "XML settings"
        )
        if (
            not isinstance(options["group_path"], list)
            or not isinstance(options["namespaces"], dict)
            or first != 1
            or value["header_evidence"] is not None
        ):
            raise ValueError("Invalid XML group identity.")
    return value


@dataclass(frozen=True)
class AdapterScope:
    id: str
    name: str
    metadata_json: str
    definitions: tuple[ColumnDefinition, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not re.fullmatch(r"[0-9a-f]{32}", self.id):
            raise ValueError("Invalid saved source data set identity.")
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 80:
            raise ValueError("Give the data set a name of 1 to 80 characters.")
        if (
            not isinstance(self.metadata_json, str)
            or len(self.metadata_json.encode("utf-8")) > MAX_SETTINGS_BYTES
        ):
            raise ValueError("Source scope metadata must be bounded JSON text.")
        data = _metadata(self.metadata_json)
        object.__setattr__(self, "metadata_json", canonical(data))
        if not isinstance(self.definitions, tuple) or any(
            not isinstance(item, ColumnDefinition) for item in self.definitions
        ):
            raise ValueError("Mappings require immutable column definitions.")
        columns = [item.column for item in self.definitions]
        if len(columns) != len(set(columns)) or any(
            column > data["field_count"] for column in columns
        ):
            raise ValueError("Mapped fields must occur once inside the complete source scope.")
        if any(item.source_header != data["headers"][item.column - 1] for item in self.definitions):
            raise ValueError("Mappings must preserve the literal source field label.")
        if data["format"] == "xml":
            xml_table(self)

    @property
    def metadata(self) -> dict[str, Any]:
        return _metadata(self.metadata_json)

    @property
    def source_sha256(self) -> str:
        return str(self.metadata["source_sha256"])


def xml_table(scope: AdapterScope) -> SavedXmlTable:
    data = scope.metadata
    options = data["options"]
    return SavedXmlTable(
        scope.id,
        scope.name,
        scope.source_sha256,
        tuple(options["group_path"]),
        options["group_label"],
        data["record_count"],
        data["field_count"],
    )


def scope_path(identity: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", identity):
        raise ValueError("Invalid source identity.")
    return Path.cwd() / ".artifacts/source-adapters" / (identity + ".json")


def load_scopes(identity: str) -> tuple[AdapterScope, ...]:
    try:
        return _load_scopes(identity)
    except (TypeError, KeyError, RecursionError) as error:
        raise ValueError(f"Saved source scopes are invalid: {error}") from error


def _load_scopes(identity: str) -> tuple[AdapterScope, ...]:
    path = scope_path(identity)
    if not path.exists():
        return ()
    data = object_keys(
        parse_json(read_text(path, limit=MAX_SETTINGS_BYTES), "source scopes"),
        {"format_version", "source_sha256", "scopes"},
        set(),
        "source scopes",
    )
    if (
        type(data["format_version"]) is not int
        or data["format_version"] != 1
        or data["source_sha256"] != identity
        or not isinstance(data["scopes"], list)
        or len(data["scopes"]) > MAX_SCOPES
    ):
        raise ValueError("Invalid saved source scopes.")
    scopes = []
    for item in data["scopes"]:
        item = object_keys(
            item, {"id", "name", "metadata_json", "definitions"}, set(), "source scope"
        )
        if not isinstance(item["definitions"], list):
            raise ValueError("Invalid saved source mappings.")
        scope = AdapterScope(
            item["id"],
            item["name"],
            item["metadata_json"],
            tuple(_definition_from_dict(entry) for entry in item["definitions"]),
        )
        if scope.source_sha256 != identity:
            raise ValueError("Saved scope belongs to another source.")
        scopes.append(scope)
    if len({scope.id for scope in scopes}) != len(scopes):
        raise ValueError("Duplicate saved source scope.")
    return tuple(scopes)


def save_scope(
    scope: AdapterScope,
    expected: AdapterScope | None = None,
    *,
    guard: Callable[[], None] = lambda: None,
) -> None:
    """Serialize application writers and reject stale edits before replacing metadata."""
    path = scope_path(scope.source_sha256)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(".lock")
    temporary = path.with_suffix("." + uuid4().hex + ".tmp")
    owns_staging = False
    with lock.open("x") as lock_handle:
        try:
            scopes = load_scopes(scope.source_sha256)
            current = next((item for item in scopes if item.id == scope.id), None)
            if current != expected:
                raise ValueError("Saved mappings changed; reload before editing.")
            updated = tuple(item for item in scopes if item.id != scope.id) + (scope,)
            if len(updated) > MAX_SCOPES:
                raise ValueError("Save at most 200 source scopes per file.")
            payload = canonical(
                {
                    "format_version": 1,
                    "source_sha256": scope.source_sha256,
                    "scopes": [asdict(item) for item in updated],
                }
            ).encode("utf-8")
            if len(payload) > MAX_SETTINGS_BYTES:
                raise ValueError("Saved source mappings exceed the 8 MiB limit.")
            with temporary.open("xb") as stream:
                owns_staging = True
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            guard()
            temporary.replace(path)
        finally:
            try:
                if owns_staging:
                    temporary.unlink(missing_ok=True)
            finally:
                lock_handle.close()
                lock.unlink()


def create_csv_scope(
    source: Path,
    name: str,
    encoding: str,
    delimiter: str,
    header: bool,
    *,
    cancelled: Event | None = None,
) -> AdapterScope:
    records = read_csv_records(source, encoding, delimiter, header, cancelled=cancelled)
    scope = AdapterScope(uuid4().hex, name, records.metadata_json)
    save_scope(scope, guard=lambda: _source_guard(source, scope, cancelled))
    return scope


def create_xml_scope(
    source: Path, table: SavedXmlTable, *, cancelled: Event | None = None
) -> AdapterScope:
    records = read_xml_records(source, table, cancelled=cancelled)
    scope = AdapterScope(table.id, table.name, records.metadata_json)
    current = next((item for item in load_scopes(scope.source_sha256) if item.id == scope.id), None)
    if current is not None:
        if replace(current, definitions=()) != scope:
            raise ValueError("XML scope changed; save a new XML data set for new mappings.")
        return current
    save_scope(scope, guard=lambda: _source_guard(source, scope, cancelled))
    return scope


def _source_guard(source: Path, scope: AdapterScope, cancelled: Event | None) -> None:
    check_cancelled(cancelled)
    if _digest(source, cancelled) != scope.source_sha256:
        raise ValueError("Source bytes changed; reopen the preserved source.")
    if scope.metadata["format"] == "xml":
        check_xml_table(xml_table(scope))


def guard_scope(
    source: Path, scope: AdapterScope, store: PackStore, cancelled: Event | None = None
) -> None:
    _source_guard(source, scope, cancelled)
    if scope not in load_scopes(scope.source_sha256):
        raise ValueError("Saved scope or mappings changed; reopen the data set.")
    catalog = store.catalog()
    for item in scope.definitions:
        selected = catalog.get_field(item.field.id)
        if snapshot_field(catalog, selected) != item.field:
            raise ValueError("Active dictionary changed; review the mapping again.")
        if set(selected.field.missing_codes) - set(item.rules.missing_tokens):
            raise ValueError("Dictionary missing codes require explicit mapped missing tokens.")


def save_mapping(
    source: Path,
    scope: AdapterScope,
    definition: ColumnDefinition | None,
    column: int,
    store: PackStore,
    *,
    cancelled: Event | None = None,
) -> AdapterScope:
    if type(column) is not int or not 1 <= column <= scope.metadata["field_count"]:
        raise ValueError("Choose a field inside the saved scope.")
    if definition is not None and definition.column != column:
        raise ValueError("Mapping belongs to another field.")
    updated = replace(
        scope,
        definitions=tuple(
            sorted(
                tuple(item for item in scope.definitions if item.column != column)
                + ((definition,) if definition is not None else ()),
                key=lambda item: item.column,
            )
        ),
    )

    def guard() -> None:
        _source_guard(source, scope, cancelled)
        catalog = store.catalog()
        for item in (definition,) if definition is not None else ():
            selected = catalog.get_field(item.field.id)
            if snapshot_field(catalog, selected) != item.field or set(
                selected.field.missing_codes
            ) - set(item.rules.missing_tokens):
                raise ValueError("Review current dictionary meanings and explicit missing tokens.")

    save_scope(updated, scope, guard=guard)
    return updated


def read_scope_records(
    source: Path, scope: AdapterScope, *, cancelled: Event | None = None
) -> SourceRecords:
    data = scope.metadata
    options = data["options"]
    records = (
        read_csv_records(
            source,
            options["encoding"],
            options["delimiter"],
            options["header"],
            cancelled=cancelled,
        )
        if data["format"] == "csv"
        else read_xml_records(source, xml_table(scope), cancelled=cancelled)
    )
    if records.metadata_json != scope.metadata_json:
        raise ValueError("Source layout or reading conventions changed; save a new scope.")
    return records


def read_snapshot(
    source: Path, scope: AdapterScope, store: PackStore, *, cancelled: Event | None = None
) -> TransformationSnapshot:
    guard_scope(source, scope, store, cancelled)
    if not scope.definitions:
        raise ValueError("Map at least one field explicitly before previewing cleanup.")
    records = read_scope_records(source, scope, cancelled=cancelled)
    data = scope.metadata
    first = data["first_data_record"]
    cells = []
    for row, values in enumerate(records.rows, 1):
        if row < first:
            continue
        check_cancelled(cancelled)
        for definition in scope.definitions:
            item = values[definition.column - 1]
            raw = item["evidence"]["raw"]
            state = (
                "missing_token"
                if item["state"] == "text"
                and isinstance(raw, str)
                and raw in definition.rules.missing_tokens
                else item["state"]
            )
            cells.append(
                {
                    "row": row,
                    "column": definition.column,
                    "state": state,
                    "evidence": item["evidence"],
                }
            )
    fields = []
    for definition in scope.definitions:
        index = definition.column - 1
        fields.append(
            {
                "definition": asdict(definition),
                "header": {
                    "label": data["headers"][index],
                    "occurrence": data["headers"][: index + 1].count(data["headers"][index]),
                    "evidence": data["header_evidence"][index] if data["header_evidence"] else None,
                },
            }
        )
    guard_scope(source, scope, store, cancelled)
    return TransformationSnapshot(
        _bounded_json(
            {
                "format_version": 1,
                "foundation_version": FOUNDATION_VERSION,
                "dataset": {"id": scope.id, "name": scope.name, **data},
                "fields": fields,
                "cells": cells,
                "population": {
                    "first_row": first,
                    "row_count": len(records.rows) - first + 1,
                    "mapped_cell_count": len(cells),
                    "selected_column_count": data["field_count"],
                    "unmapped_column_count": data["field_count"] - len(fields),
                },
            }
        )
    )


@dataclass(frozen=True)
class AdapterReview:
    snapshot: TransformationSnapshot
    preview: TransformationPreview
    scope: AdapterScope


def review_source(
    source: Path,
    scope: AdapterScope,
    column: int,
    settings: TextCleanupSettings | ExactRulesSettings,
    store: PackStore,
    *,
    parent: TransformationRevision | None = None,
    cancelled: Event | None = None,
) -> AdapterReview:
    snapshot = read_snapshot(source, scope, store, cancelled=cancelled)
    preview = (
        preview_exact_rules(snapshot, column, settings, parent=parent, cancelled=cancelled)
        if isinstance(settings, ExactRulesSettings)
        else preview_text_cleanup(snapshot, column, settings, parent=parent, cancelled=cancelled)
    )
    return AdapterReview(snapshot, preview, scope)


def publish_audit(
    target: Path, revision: TransformationRevision, guard: Callable[[], None]
) -> Path:
    if target.suffix.lower() != ".json" or target.exists() or target.is_symlink():
        raise ValueError("Choose a new JSON audit file; existing files cannot be overwritten.")
    content = _bounded_json(
        {"format_version": 1, "revision_id": revision.id, "revision": revision.to_dict()}
    ).encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    identity = revision.to_dict()["snapshot"]["dataset"]["source_sha256"]
    temporary = target.with_name(identity + "-" + uuid4().hex + ".tmp")
    owns_staging = False
    linked = False
    try:
        with temporary.open("xb") as stream:
            owns_staging = True
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        guard()
        os.link(temporary, target)
        linked = True
        if target.read_bytes() != content:
            raise ValueError("Published audit differs from the reviewed evidence.")
        guard()
        return target
    except BaseException:
        if linked and target.exists() and target.samefile(temporary):
            target.unlink()
        raise
    finally:
        if owns_staging:
            temporary.unlink(missing_ok=True)


def apply_review(
    source: Path,
    review: AdapterReview,
    column: int,
    settings: TextCleanupSettings | ExactRulesSettings,
    approval: TransformationApproval,
    store: PackStore,
    *,
    parent: TransformationRevision | None = None,
    cancelled: Event | None = None,
) -> tuple[TransformationRevision, Path]:
    current = review_source(
        source, review.scope, column, settings, store, parent=parent, cancelled=cancelled
    )
    if current != review:
        raise ValueError("Source, mappings or proposals changed; preview and review again.")
    revision = apply_transformation(
        current.snapshot, current.preview, approval, parent=parent, cancelled=cancelled
    )
    revision = replay_revision(current.snapshot, revision.document_json, cancelled=cancelled)
    target = (
        Path.cwd()
        / ".artifacts/transformations"
        / (review.scope.source_sha256 + "-" + uuid4().hex + ".json")
    )
    publish_audit(target, revision, lambda: guard_scope(source, review.scope, store, cancelled))
    return revision, target


def export_audit(
    source: Path,
    scope: AdapterScope,
    store: PackStore,
    revision: TransformationRevision,
    target: Path,
    *,
    cancelled: Event | None = None,
) -> Path:
    snapshot = read_snapshot(source, scope, store, cancelled=cancelled)
    revision = replay_revision(snapshot, revision.document_json, cancelled=cancelled)
    return publish_audit(target, revision, lambda: guard_scope(source, scope, store, cancelled))
