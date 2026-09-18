"""Source-bound, snapshot-pinned definitions for saved Excel data-set columns."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from loan_tape.date_parser import TEXT_FORMATS
from loan_tape.pack_format import DATA_TYPES, object_keys, parse_json
from loan_tape.packs import Catalog, CatalogField
from loan_tape.ranges import parse_range
from loan_tape.selection import SavedTable, SourceSelection

MAX_SETTINGS_BYTES = 2 * 1024 * 1024
MAX_SCOPES = 500
MAX_DEFINITIONS = 2_048
MAX_TEXT = 2_000
DATE_FORMATS = frozenset(TEXT_FORMATS)


def _text(value: object, name: str, *, maximum: int = MAX_TEXT) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be non-empty text of at most {maximum:,} characters.")
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise ValueError(f"{name} contains an invalid Unicode character.") from error
    return value


def _optional_text(value: object, name: str, *, maximum: int = MAX_TEXT) -> str | None:
    return None if value is None else _text(value, name, maximum=maximum)


def _optional_bool(value: object, name: str) -> bool | None:
    if value is not None and type(value) is not bool:
        raise ValueError(f"{name} must be true, false, or null.")
    return value


def _strings(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be a list of text values.")
    result = tuple(_text(item, name, maximum=200) for item in value)
    if len(result) != len(set(result)):
        raise ValueError(f"{name} contains duplicate values.")
    return result


def _decimal_text(value: str | None, name: str) -> None:
    if value is None:
        return
    if value != value.strip():
        raise ValueError(f"{name} cannot contain surrounding whitespace.")
    if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)", value):
        raise ValueError(f"{name} must be a plain finite decimal value.")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{name} must be a plain finite decimal value.") from error
    if not parsed.is_finite():
        raise ValueError(f"{name} must be a plain finite decimal value.")


@dataclass(frozen=True)
class AllowedValueSnapshot:
    value: str
    label: str
    definition: str

    def __post_init__(self) -> None:
        _text(self.value, "Allowed value", maximum=1_000)
        _text(self.label, "Allowed-value label")
        _text(self.definition, "Allowed-value definition")


@dataclass(frozen=True)
class FieldSnapshot:
    """The exact active dictionary meaning used when a mapping was saved."""

    id: str
    pack_id: str
    pack_version: str
    pack_fingerprint: str
    label: str
    definition: str
    entity: str
    data_type: str
    context: tuple[str, ...]
    canonical_unit: str | None
    dictionary_required: bool | None
    dictionary_blank_allowed: bool | None
    code_list: str | None
    allowed_values: tuple[AllowedValueSnapshot, ...] = ()

    def __post_init__(self) -> None:
        _text(self.id, "Field ID", maximum=201)
        _text(self.pack_id, "Pack ID", maximum=100)
        _text(self.pack_version, "Pack version", maximum=100)
        if not re.fullmatch(r"[0-9a-f]{64}", self.pack_fingerprint):
            raise ValueError("Pack fingerprint must be 64 lowercase hexadecimal characters.")
        _text(self.label, "Field label")
        _text(self.definition, "Field definition", maximum=10_000)
        _text(self.entity, "Field entity", maximum=100)
        if self.data_type not in DATA_TYPES:
            raise ValueError("Field snapshot has an unsupported data type.")
        if not isinstance(self.context, tuple):
            raise ValueError("Field context must be an immutable sequence.")
        _strings(self.context, "Field context")
        _optional_text(self.canonical_unit, "Canonical unit", maximum=200)
        _optional_bool(self.dictionary_required, "Dictionary required rule")
        _optional_bool(self.dictionary_blank_allowed, "Dictionary blank rule")
        _optional_text(self.code_list, "Code-list ID", maximum=100)
        if not isinstance(self.allowed_values, tuple) or any(
            not isinstance(item, AllowedValueSnapshot) for item in self.allowed_values
        ):
            raise ValueError("Allowed values must be immutable snapshots.")
        values = [item.value for item in self.allowed_values]
        if len(values) != len(set(values)):
            raise ValueError("Allowed-value snapshots contain duplicate values.")
        if (self.code_list is None) != (not self.allowed_values):
            raise ValueError("Category code-list identity and values must be saved together.")


@dataclass(frozen=True)
class ColumnRules:
    """Mapping-specific rule choices; null values retain the dictionary setting."""

    required: bool | None = None
    blank_allowed: bool | None = None
    unique: bool | None = None
    minimum: str | None = None
    maximum: str | None = None
    missing_tokens: tuple[str, ...] = ()
    notes: str | None = None

    def __post_init__(self) -> None:
        _optional_bool(self.required, "Required rule")
        _optional_bool(self.blank_allowed, "Blank rule")
        _optional_bool(self.unique, "Unique rule")
        _optional_text(self.minimum, "Minimum rule", maximum=200)
        _optional_text(self.maximum, "Maximum rule", maximum=200)
        _decimal_text(self.minimum, "Minimum rule")
        _decimal_text(self.maximum, "Maximum rule")
        if self.minimum is not None and self.maximum is not None:
            if Decimal(self.minimum) > Decimal(self.maximum):
                raise ValueError("Minimum rule cannot exceed maximum rule.")
        if not isinstance(self.missing_tokens, tuple):
            raise ValueError("Missing tokens must be an immutable sequence.")
        _strings(self.missing_tokens, "Missing tokens")
        if any(item != item.strip() for item in self.missing_tokens):
            raise ValueError("Missing tokens cannot contain surrounding whitespace.")
        _optional_text(self.notes, "Rule notes", maximum=4_000)
        if self.required is True and self.blank_allowed is True:
            raise ValueError("A required column cannot also allow blank values.")


@dataclass(frozen=True)
class ColumnDefinition:
    column: int
    source_header: str
    field: FieldSnapshot
    currency: str | None = None
    source_unit: str | None = None
    date_formats: tuple[str, ...] = ()
    two_digit_year_start: int | None = None
    rules: ColumnRules = ColumnRules()

    def __post_init__(self) -> None:
        if type(self.column) is not int or self.column < 1 or self.column > 16_384:
            raise ValueError("Column number must be an Excel source column.")
        if not isinstance(self.source_header, str) or len(self.source_header) > 2_000:
            raise ValueError("Source header must be text of at most 2,000 characters.")
        try:
            self.source_header.encode("utf-8")
        except UnicodeError as error:
            raise ValueError("Source header contains an invalid Unicode character.") from error
        if not isinstance(self.field, FieldSnapshot):
            raise ValueError("Column definition requires a dictionary field snapshot.")
        if self.currency is not None and not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise ValueError("Currency must be a three-letter uppercase code such as USD.")
        _optional_text(self.source_unit, "Source unit", maximum=200)
        if not isinstance(self.date_formats, tuple):
            raise ValueError("Date formats must be an immutable sequence.")
        _strings(self.date_formats, "Date formats")
        if set(self.date_formats) - DATE_FORMATS:
            raise ValueError("Column definition contains an unsupported date format.")
        if self.two_digit_year_start is not None and (
            type(self.two_digit_year_start) is not int
            or not 1 <= self.two_digit_year_start <= 9_900
        ):
            raise ValueError("Two-digit year window must start between 1 and 9900.")
        uses_short_year = any(item in {"M/D/YY", "D/M/YY"} for item in self.date_formats)
        if uses_short_year and self.two_digit_year_start is None:
            raise ValueError("Two-digit text dates require an explicit year-window start.")
        if not uses_short_year and self.two_digit_year_start is not None:
            raise ValueError("A two-digit year window applies only to a YY date format.")
        if self.field.data_type == "date":
            if not self.date_formats:
                raise ValueError("Date columns require at least one accepted text format.")
            if self.currency is not None or self.source_unit is not None:
                raise ValueError("Date columns cannot have currency or source units.")
        elif self.date_formats:
            raise ValueError("Date formats apply only to date columns.")
        if self.currency is not None and self.field.data_type not in {"integer", "decimal"}:
            raise ValueError("Currency applies only to numeric columns.")
        if self.source_unit is not None and self.field.data_type not in {"integer", "decimal"}:
            raise ValueError("Source units apply only to numeric columns.")
        if (self.rules.minimum is not None or self.rules.maximum is not None) and (
            self.field.data_type not in {"integer", "decimal"}
        ):
            raise ValueError("Minimum and maximum rules apply only to numeric columns.")
        effective_required = (
            self.rules.required
            if self.rules.required is not None
            else self.field.dictionary_required
        )
        effective_blanks = (
            self.rules.blank_allowed
            if self.rules.blank_allowed is not None
            else self.field.dictionary_blank_allowed
        )
        if effective_required is True and effective_blanks is True:
            raise ValueError("The effective rules cannot require a value and allow blanks.")
        needs_currency = self.field.data_type in {"integer", "decimal"} and (
            "currency" in self.field.context
            or (self.field.canonical_unit or "").casefold() == "currency units"
        )
        if needs_currency and self.currency is None:
            raise ValueError("This monetary column requires an explicit three-letter currency.")
        if (
            self.field.data_type in {"integer", "decimal"}
            and self.field.canonical_unit is not None
            and self.source_unit is None
        ):
            raise ValueError("This numeric field requires explicit source units.")


@dataclass(frozen=True)
class DefinitionScope:
    table_id: str
    table_name: str
    selection: SourceSelection
    definitions: tuple[ColumnDefinition, ...] = ()

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{32}", self.table_id):
            raise ValueError("Invalid data set identity in column definitions.")
        _text(self.table_name, "Data set name", maximum=80)
        if not isinstance(self.selection, SourceSelection):
            raise ValueError("Column definitions require a source selection.")
        if not isinstance(self.definitions, tuple):
            raise ValueError("Column definitions must be an immutable sequence.")
        columns = [item.column for item in self.definitions]
        if len(columns) != len(set(columns)):
            raise ValueError("A source column can have only one saved definition per data set.")
        if any(
            column < self.selection.area.min_column or column > self.selection.area.max_column
            for column in columns
        ):
            raise ValueError("A saved column definition falls outside its data set.")

    def matches(self, table: SavedTable) -> bool:
        return self.table_id == table.id and self.selection == table.selection


@dataclass(frozen=True)
class ColumnDefinitionStore:
    workbook_sha256: str
    scopes: tuple[DefinitionScope, ...] = ()

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", self.workbook_sha256):
            raise ValueError("Invalid workbook identity for column definitions.")
        if not isinstance(self.scopes, tuple):
            raise ValueError("Column-definition scopes must be immutable.")
        if len(self.scopes) > MAX_SCOPES:
            raise ValueError("Too many historical column-definition scopes.")
        keys = [
            (
                item.table_id,
                item.selection.sheet,
                item.selection.area.address,
                item.selection.header_row,
            )
            for item in self.scopes
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("Column-definition scopes contain duplicates.")
        if any(item.selection.workbook_sha256 != self.workbook_sha256 for item in self.scopes):
            raise ValueError("Column-definition scope does not match the workbook identity.")
        if sum(len(item.definitions) for item in self.scopes) > MAX_DEFINITIONS:
            raise ValueError("Too many saved column definitions.")

    def for_table(self, table: SavedTable) -> DefinitionScope | None:
        return next((item for item in self.scopes if item.matches(table)), None)


def definition_path(sha256: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValueError("Invalid source identity.")
    return Path.cwd() / ".artifacts" / "column-definitions" / f"{sha256}.json"


def snapshot_field(catalog: Catalog, selected: CatalogField) -> FieldSnapshot:
    """Freeze the selected active field and any exact allowed-value meanings."""
    pack = next((item for item in catalog.packs if item.id == selected.pack_id), None)
    if pack is None or pack.version != selected.pack_version:
        raise ValueError("The selected dictionary field is not in the active catalog snapshot.")
    field = selected.field
    allowed: tuple[AllowedValueSnapshot, ...] = ()
    if field.code_list is not None:
        code_list = next((item for item in pack.code_lists if item.id == field.code_list), None)
        if code_list is None:
            raise ValueError("The selected dictionary field has no available code list.")
        allowed = tuple(
            AllowedValueSnapshot(item.value, item.label, item.definition)
            for item in code_list.codes
        )
    return FieldSnapshot(
        selected.id,
        selected.pack_id,
        selected.pack_version,
        pack.fingerprint,
        field.label,
        field.definition,
        field.entity,
        field.data_type,
        field.context,
        field.unit,
        field.required,
        field.blank_allowed,
        field.code_list,
        allowed,
    )


def _field_from_dict(value: object) -> FieldSnapshot:
    row = object_keys(
        value,
        {
            "id",
            "pack_id",
            "pack_version",
            "pack_fingerprint",
            "label",
            "definition",
            "entity",
            "data_type",
            "context",
            "canonical_unit",
            "dictionary_required",
            "dictionary_blank_allowed",
            "code_list",
            "allowed_values",
        },
        set(),
        "column definition field",
    )
    if not isinstance(row["allowed_values"], list) or not isinstance(row["context"], list):
        raise ValueError("Field context and allowed values must be lists.")
    return FieldSnapshot(
        row["id"],
        row["pack_id"],
        row["pack_version"],
        row["pack_fingerprint"],
        row["label"],
        row["definition"],
        row["entity"],
        row["data_type"],
        tuple(row["context"]),
        row["canonical_unit"],
        row["dictionary_required"],
        row["dictionary_blank_allowed"],
        row["code_list"],
        tuple(AllowedValueSnapshot(**item) for item in row["allowed_values"]),
    )


def _rules_from_dict(value: object) -> ColumnRules:
    row = object_keys(
        value,
        {"required", "blank_allowed", "unique", "minimum", "maximum", "missing_tokens", "notes"},
        set(),
        "column definition rules",
    )
    if not isinstance(row["missing_tokens"], list):
        raise ValueError("Missing tokens must be a list.")
    return ColumnRules(
        row["required"],
        row["blank_allowed"],
        row["unique"],
        row["minimum"],
        row["maximum"],
        tuple(row["missing_tokens"]),
        row["notes"],
    )


def _definition_from_dict(value: object) -> ColumnDefinition:
    row = object_keys(
        value,
        {
            "column",
            "source_header",
            "field",
            "currency",
            "source_unit",
            "date_formats",
            "two_digit_year_start",
            "rules",
        },
        set(),
        "column definition",
    )
    if not isinstance(row["date_formats"], list):
        raise ValueError("Date formats must be a list.")
    return ColumnDefinition(
        row["column"],
        row["source_header"],
        _field_from_dict(row["field"]),
        row["currency"],
        row["source_unit"],
        tuple(row["date_formats"]),
        row["two_digit_year_start"],
        _rules_from_dict(row["rules"]),
    )


def _scope_from_dict(value: object, sha256: str) -> DefinitionScope:
    row = object_keys(
        value,
        {"table_id", "table_name", "sheet", "range", "header_row", "definitions"},
        set(),
        "column definition scope",
    )
    if not isinstance(row["definitions"], list):
        raise ValueError("Column definitions must be a list.")
    return DefinitionScope(
        row["table_id"],
        row["table_name"],
        SourceSelection(sha256, row["sheet"], parse_range(row["range"]), row["header_row"]),
        tuple(_definition_from_dict(item) for item in row["definitions"]),
    )


def load_column_definitions(sha256: str) -> ColumnDefinitionStore:
    target = definition_path(sha256)
    if not target.exists():
        return ColumnDefinitionStore(sha256)
    try:
        with target.open("rb") as stream:
            raw = stream.read(MAX_SETTINGS_BYTES + 1)
        if len(raw) > MAX_SETTINGS_BYTES:
            raise ValueError("Saved column definitions exceed the storage limit.")
        data = parse_json(raw.decode("utf-8"), str(target))
        row = object_keys(
            data,
            {"schema_version", "workbook_sha256", "scopes"},
            set(),
            "column definition settings",
        )
        if type(row["schema_version"]) is not int or row["schema_version"] != 1:
            raise ValueError("Unsupported column-definition settings version.")
        if row["workbook_sha256"] != sha256 or not isinstance(row["scopes"], list):
            raise ValueError("Column-definition settings do not match this source.")
        return ColumnDefinitionStore(
            sha256, tuple(_scope_from_dict(item, sha256) for item in row["scopes"])
        )
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise ValueError(
            "Saved column definitions could not be read. Repair or remove their local settings file."
        ) from error


def _payload(settings: ColumnDefinitionStore) -> dict[str, object]:
    return {
        "schema_version": 1,
        "workbook_sha256": settings.workbook_sha256,
        "scopes": [
            {
                "table_id": scope.table_id,
                "table_name": scope.table_name,
                "sheet": scope.selection.sheet,
                "range": scope.selection.area.address,
                "header_row": scope.selection.header_row,
                "definitions": [asdict(item) for item in scope.definitions],
            }
            for scope in settings.scopes
        ],
    }


def save_column_definitions(settings: ColumnDefinitionStore) -> None:
    target = definition_path(settings.workbook_sha256)
    payload = json.dumps(_payload(settings), ensure_ascii=False, indent=2)
    if len(payload.encode("utf-8")) > MAX_SETTINGS_BYTES:
        raise ValueError("Saved column definitions exceed the storage limit.")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f".{uuid4().hex}.tmp")
    try:
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def definitions_for_table(table: SavedTable) -> tuple[ColumnDefinition, ...]:
    scope = load_column_definitions(table.selection.workbook_sha256).for_table(table)
    return scope.definitions if scope is not None else ()


def definition_for_column(table: SavedTable, column: int) -> ColumnDefinition | None:
    return next((item for item in definitions_for_table(table) if item.column == column), None)


def save_column_definition(table: SavedTable, definition: ColumnDefinition) -> None:
    if not table.selection.area.min_column <= definition.column <= table.selection.area.max_column:
        raise ValueError("The selected source column is outside this saved data set.")
    settings = load_column_definitions(table.selection.workbook_sha256)
    current = settings.for_table(table)
    existing = current.definitions if current is not None else ()
    duplicate = next(
        (
            item
            for item in existing
            if item.column != definition.column and item.field.id == definition.field.id
        ),
        None,
    )
    if duplicate is not None:
        raise ValueError(
            f"{definition.field.label} is already mapped to source column {duplicate.column}."
        )
    definitions = tuple(
        sorted(
            (*[item for item in existing if item.column != definition.column], definition),
            key=lambda item: item.column,
        )
    )
    replacement = DefinitionScope(table.id, table.name, table.selection, definitions)
    scopes = tuple(item for item in settings.scopes if not item.matches(table)) + (replacement,)
    save_column_definitions(ColumnDefinitionStore(settings.workbook_sha256, scopes))


def remove_column_definition(table: SavedTable, column: int) -> bool:
    settings = load_column_definitions(table.selection.workbook_sha256)
    current = settings.for_table(table)
    if current is None or not any(item.column == column for item in current.definitions):
        return False
    remaining = tuple(item for item in current.definitions if item.column != column)
    scopes = tuple(item for item in settings.scopes if not item.matches(table))
    if remaining:
        scopes += (DefinitionScope(table.id, table.name, table.selection, remaining),)
    save_column_definitions(ColumnDefinitionStore(settings.workbook_sha256, scopes))
    return True
