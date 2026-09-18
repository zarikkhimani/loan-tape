"""Versioned, data-only dictionary packs; no document, code, or rule execution."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any

PACK_FILES = ("pack.json", "sources.json", "code_lists.json", "fields.json")
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_SOURCES = 100
MAX_CODE_LISTS = 250
MAX_CODES_PER_LIST = 2_000
MAX_TOTAL_CODES = 10_000
MAX_FIELDS = 2_000
MAX_REFERENCES = 50
MAX_TEXT_LIST_ITEMS = 250
ID_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*")
VERSION_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
ENTITIES = {"borrower", "loan", "holding", "tranche", "portfolio", "report"}
DATA_TYPES = {"identifier", "text", "integer", "decimal", "date", "boolean", "category"}


class PackError(ValueError):
    """A pack or its activation state needs an explicit repair."""


def check_pack_cancelled(cancelled: Event | None) -> None:
    if cancelled is not None and cancelled.is_set():
        raise PackError("Pack loading cancelled; no complete inventory was produced.")


def identifier(value: object, location: str) -> str:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value) or len(value) > 100:
        raise PackError(f"{location}: use a lowercase ID with letters, digits, '.', '_' or '-'.")
    return value


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PackError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise PackError(f"non-finite JSON value {value!r} is unsupported")


def parse_json(text: str, location: str) -> Any:
    try:
        return json.loads(
            text.removeprefix("\ufeff"), object_pairs_hook=_pairs, parse_constant=_constant
        )
    except (ValueError, RecursionError) as error:
        raise PackError(f"{location}: {error}") from error


def read_text(path: Path, *, limit: int = MAX_FILE_BYTES) -> str:
    try:
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise PackError(f"{path}: exceeds {limit:,} bytes.")
        return data.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise PackError(f"{path}: {error}") from error


def object_keys(
    value: Any, required: set[str], optional: set[str], location: str
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PackError(f"{location}: expected an object.")
    missing, unknown = required - value.keys(), value.keys() - required - optional
    if missing or unknown:
        raise PackError(
            f"{location}: missing keys {sorted(missing)}; unsupported keys {sorted(unknown)}."
        )
    return value


def _text(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PackError(f"{location}: expected non-empty text.")
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise PackError(f"{location}: text contains an invalid Unicode character.") from error
    return value


def _strings(value: Any, location: str, limit: int = MAX_TEXT_LIST_ITEMS) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise PackError(f"{location}: expected a list.")
    if len(value) > limit:
        raise PackError(f"{location}: exceeds the limit of {limit:,} values.")
    result = tuple(_text(item, location) for item in value)
    if len(set(result)) != len(result):
        raise PackError(f"{location}: duplicate values.")
    return result


def _rows(value: Any, location: str, limit: int, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise PackError(f"{location}: expected a list.")
    if len(value) > limit:
        raise PackError(f"{location}: exceeds the limit of {limit:,} {label}.")
    return value


def _optional_text(value: Any, location: str) -> str | None:
    return None if value is None else _text(value, location)


def _optional_bool(value: Any, location: str) -> bool | None:
    if value is not None and type(value) is not bool:
        raise PackError(f"{location}: expected true, false, or null (unspecified).")
    return value


@dataclass(frozen=True)
class Reference:
    source: str
    locator: str


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    version: str
    uri: str
    sha256: str | None


@dataclass(frozen=True)
class Code:
    value: str
    label: str
    definition: str


@dataclass(frozen=True)
class CodeList:
    id: str
    codes: tuple[Code, ...]
    references: tuple[Reference, ...]


@dataclass(frozen=True)
class Field:
    id: str
    label: str
    definition: str
    entity: str
    data_type: str
    references: tuple[Reference, ...]
    aliases: tuple[str, ...]
    context: tuple[str, ...]
    unit: str | None
    required: bool | None
    blank_allowed: bool | None
    code_list: str | None
    missing_code_list: str | None
    missing_codes: tuple[str, ...]
    notes: str | None


@dataclass(frozen=True)
class Pack:
    id: str
    version: str
    name: str
    description: str
    asset_classes: tuple[str, ...]
    sources: tuple[Source, ...]
    code_lists: tuple[CodeList, ...]
    fields: tuple[Field, ...]
    fingerprint: str
    files: tuple[tuple[str, str], ...]


def _references(
    value: Any, sources: set[str], location: str, cancelled: Event | None = None
) -> tuple[Reference, ...]:
    result = []
    for index, item in enumerate(_rows(value, location, MAX_REFERENCES, "references")):
        check_pack_cancelled(cancelled)
        where = f"{location}[{index}]"
        row = object_keys(item, {"source", "locator"}, set(), where)
        source = _text(row["source"], where)
        if source not in sources:
            raise PackError(f"{where}: unknown source {source!r}.")
        result.append(Reference(source, _text(row["locator"], where)))
    if not result:
        raise PackError(f"{location}: provide at least one source reference.")
    return tuple(result)


def _unique(value: Any, seen: set[str], location: str) -> str:
    key = identifier(value, location)
    if key in seen:
        raise PackError(f"{location}: duplicate ID {key!r}.")
    seen.add(key)
    return key


def load_pack_files(
    files: dict[str, str], location: str = "pack", cancelled: Event | None = None
) -> Pack:
    """Validate the complete format and references; keep exact UTF-8 source texts."""
    if set(files) != set(PACK_FILES):
        raise PackError(f"{location}: expected exactly {', '.join(PACK_FILES)}.")
    documents = {}
    digest = hashlib.sha256()
    for name in PACK_FILES:
        check_pack_cancelled(cancelled)
        content = files[name]
        if not isinstance(content, str):
            raise PackError(f"{location}/{name}: expected UTF-8 text.")
        try:
            payload = content.encode("utf-8")
        except UnicodeError as error:
            raise PackError(f"{location}/{name}: invalid Unicode in file content.") from error
        if len(payload) > MAX_FILE_BYTES:
            raise PackError(f"{location}/{name}: file exceeds size limit.")
        digest.update(name.encode("ascii") + b"\0" + len(payload).to_bytes(8, "big") + payload)
        documents[name] = parse_json(content, f"{location}/{name}")
    where = f"{location}/pack.json"
    manifest = object_keys(
        documents["pack.json"],
        {"format_version", "id", "version", "name", "description", "asset_classes"},
        set(),
        where,
    )
    if type(manifest["format_version"]) is not int or manifest["format_version"] != 1:
        raise PackError(f"{where}: unsupported format_version; expected 1.")
    pack_id = identifier(manifest["id"], f"{where}.id")
    version = _text(manifest["version"], f"{where}.version")
    if not VERSION_PATTERN.fullmatch(version):
        raise PackError(f"{where}.version: expected major.minor.patch, for example 1.0.0.")
    asset_classes = _strings(manifest["asset_classes"], f"{where}.asset_classes", 50)
    if not asset_classes:
        raise PackError(f"{where}: specify at least one asset class.")
    sources, source_ids = [], set[str]()
    for index, item in enumerate(
        _rows(documents["sources.json"], "sources.json", MAX_SOURCES, "sources")
    ):
        check_pack_cancelled(cancelled)
        where = f"{location}/sources.json[{index}]"
        row = object_keys(item, {"id", "title", "version", "uri"}, {"sha256"}, where)
        key = _unique(row["id"], source_ids, where)
        sha = _optional_text(row.get("sha256"), where)
        if sha is not None and not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise PackError(f"{where}.sha256: expected 64 lowercase hexadecimal characters.")
        sources.append(
            Source(
                key,
                _text(row["title"], where),
                _text(row["version"], where),
                _text(row["uri"], where),
                sha,
            )
        )
    code_lists, code_ids = [], set[str]()
    total_codes = 0
    for index, item in enumerate(
        _rows(documents["code_lists.json"], "code_lists.json", MAX_CODE_LISTS, "code lists")
    ):
        check_pack_cancelled(cancelled)
        where = f"{location}/code_lists.json[{index}]"
        row = object_keys(item, {"id", "codes", "references"}, set(), where)
        key = _unique(row["id"], code_ids, where)
        codes, values = [], set[str]()
        code_rows = _rows(row["codes"], where, MAX_CODES_PER_LIST, "codes")
        total_codes += len(code_rows)
        if total_codes > MAX_TOTAL_CODES:
            raise PackError(f"{location}: exceeds the limit of {MAX_TOTAL_CODES:,} total codes.")
        for code in code_rows:
            check_pack_cancelled(cancelled)
            entry = object_keys(code, {"value", "label", "definition"}, set(), where)
            value = _text(entry["value"], where)
            if value in values:
                raise PackError(f"{where}: duplicate code {value!r}.")
            values.add(value)
            codes.append(
                Code(value, _text(entry["label"], where), _text(entry["definition"], where))
            )
        if not codes:
            raise PackError(f"{where}: a code list cannot be empty.")
        code_lists.append(
            CodeList(
                key,
                tuple(codes),
                _references(row["references"], source_ids, where, cancelled),
            )
        )
    code_values = {item.id: frozenset(code.value for code in item.codes) for item in code_lists}
    fields, field_ids = [], set[str]()
    for index, item in enumerate(
        _rows(documents["fields.json"], "fields.json", MAX_FIELDS, "fields")
    ):
        check_pack_cancelled(cancelled)
        where = f"{location}/fields.json[{index}]"
        row = object_keys(
            item,
            {"id", "label", "definition", "entity", "data_type", "references"},
            {
                "aliases",
                "context",
                "unit",
                "required",
                "blank_allowed",
                "code_list",
                "missing_code_list",
                "missing_codes",
                "notes",
            },
            where,
        )
        key = _unique(row["id"], field_ids, where)
        entity, data_type = _text(row["entity"], where), _text(row["data_type"], where)
        if entity not in ENTITIES or data_type not in DATA_TYPES:
            raise PackError(f"{where}: unsupported entity {entity!r} or data_type {data_type!r}.")
        code_list = _optional_text(row.get("code_list"), where)
        missing_list = _optional_text(row.get("missing_code_list"), where)
        for reference in (code_list, missing_list):
            if reference is not None and reference not in code_ids:
                raise PackError(f"{where}: unknown code list {reference!r}.")
        if data_type == "category" and code_list is None:
            raise PackError(f"{where}: category fields require a code_list.")
        if data_type != "category" and code_list is not None:
            raise PackError(f"{where}: code_list applies to category fields only.")
        missing_codes = _strings(row.get("missing_codes", []), where)
        allowed = frozenset() if missing_list is None else code_values[missing_list]
        if set(missing_codes) - allowed:
            raise PackError(f"{where}: missing_codes must reference values in missing_code_list.")
        fields.append(
            Field(
                key,
                _text(row["label"], where),
                _text(row["definition"], where),
                entity,
                data_type,
                _references(row["references"], source_ids, where, cancelled),
                _strings(row.get("aliases", []), where),
                _strings(row.get("context", []), where),
                _optional_text(row.get("unit"), where),
                _optional_bool(row.get("required"), where),
                _optional_bool(row.get("blank_allowed"), where),
                code_list,
                missing_list,
                missing_codes,
                _optional_text(row.get("notes"), where),
            )
        )
    if not fields and not code_lists:
        raise PackError(f"{location}: provide at least one field or code list.")
    return Pack(
        pack_id,
        version,
        _text(manifest["name"], "pack.name"),
        _text(manifest["description"], "pack.description"),
        asset_classes,
        tuple(sources),
        tuple(code_lists),
        tuple(fields),
        digest.hexdigest(),
        tuple((name, files[name]) for name in PACK_FILES),
    )


def load_pack(directory: Path, cancelled: Event | None = None) -> Pack:
    """Read a folder without importing scripts, fetching sources, or following file escapes."""
    try:
        root = directory.resolve(strict=True)
        if not root.is_dir():
            raise PackError(f"{directory}: expected a pack directory.")
        unknown = {p.name for p in root.glob("*.json")} - set(PACK_FILES)
        if unknown:
            raise PackError(f"{directory}: unsupported JSON files {sorted(unknown)}.")
        files = {}
        for name in PACK_FILES:
            check_pack_cancelled(cancelled)
            path = root / name
            if path.resolve().parent != root:
                raise PackError(f"{path}: pack file resolves outside its directory.")
            files[name] = read_text(path)
        return load_pack_files(files, str(directory), cancelled)
    except OSError as error:
        raise PackError(f"{directory}: {error}") from error
