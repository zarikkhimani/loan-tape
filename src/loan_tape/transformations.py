"""Immutable, engine-neutral text proposals and explicitly approved derived revisions.

This module never opens a workbook, calls a cleanup engine, or writes a source value.
The source adapters supply complete original evidence and recheck it before saving.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from threading import Event
from typing import Any

from loan_tape._date_json import canonical
from loan_tape.column_definitions import DefinitionScope
from loan_tape.date_parser import DateEvidence
from loan_tape.date_reader import DateColumnEvidence
from loan_tape.pack_format import ID_PATTERN, VERSION_PATTERN, parse_json
from loan_tape.recipe_context import validate_recipe_context
from loan_tape.selection import SavedTable
from loan_tape.text_rule_types import (
    EXACT_ENGINE,
    EXACT_OPERATION,
    EXACT_VERSION,
    MAX_RULE_BYTES,
    exact_field,
    free_text,
    read_rule_parameters,
    validate_rule_field,
)
from loan_tape.workbook_index import check_cancelled

MAX_CELLS = 200_000
MAX_RESULT_BYTES = 128 * 1024 * 1024
MAX_TOKEN_BYTES = 16 * 1024
MAX_STEPS = 12
MAX_PAGE_SIZE = 200
FOUNDATION_VERSION = "1.0.0"
OUTCOMES = ("changed", "unchanged", "ineligible", "unresolved", "failed")


def _text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > 4_000:
        raise ValueError(f"{name} requires non-empty UTF-8 text of at most 4,000 bytes.")


def _bounded_json(value: Any) -> str:
    encoded = canonical(value)
    if len(encoded.encode("utf-8")) > MAX_RESULT_BYTES:
        raise ValueError("Transformation evidence exceeds the serialized result limit.")
    return encoded


def _retain(value: Any) -> Any:
    """Reference oversized source tokens without truncating or inventing their text."""
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        if len(encoded) > MAX_TOKEN_BYTES:
            return {
                "retained": False,
                "utf8_bytes": len(encoded),
                "sha256": hashlib.sha256(encoded).hexdigest(),
            }
    if isinstance(value, dict):
        return {key: _retain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_retain(item) for item in value]
    return value


def _has_reference(value: Any) -> bool:
    if isinstance(value, dict):
        return value.get("retained") is False or any(_has_reference(v) for v in value.values())
    return isinstance(value, list) and any(_has_reference(v) for v in value)


def _state(cell: DateEvidence, missing: tuple[str, ...]) -> str:
    if cell.kind == "blank":
        return "blank" if cell.present else "absent"
    if cell.kind != "text":
        return cell.kind
    if cell.raw == "":
        return "empty_text"
    if cell.raw is not None and cell.raw.isspace():
        return "whitespace_text"
    if cell.raw in missing:
        return "missing_token"
    return "text"


@dataclass(frozen=True)
class TransformationSnapshot:
    """Frozen original evidence. Obtain through a validated Excel, CSV or XML adapter."""

    document_json: str

    @property
    def id(self) -> str:
        return hashlib.sha256(self.document_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.document_json)  # type: ignore[no-any-return]


def build_snapshot(
    table: SavedTable,
    scope: DefinitionScope,
    columns: tuple[DateColumnEvidence, ...],
    headers: tuple[DateEvidence, ...],
    *,
    cancelled: Event | None = None,
) -> TransformationSnapshot:
    """Require complete, ordered evidence for every mapped cell, including blank tails."""
    check_cancelled(cancelled)
    if not scope.matches(table) or scope.table_name != table.name or not scope.definitions:
        raise ValueError(
            "Transformations require the current saved data set and explicit mappings."
        )
    selection = table.selection
    first = selection.header_row + 1 if selection.header_row is not None else selection.area.min_row
    rows = selection.area.max_row - first + 1
    definitions = tuple(sorted(scope.definitions, key=lambda item: item.column))
    if rows * len(definitions) > MAX_CELLS:
        raise ValueError("Transformation selection exceeds the mapped-cell limit.")
    if tuple(item.column for item in columns) != tuple(item.column for item in definitions):
        raise ValueError("Evidence must cover every mapped column once, in source order.")
    header_info: dict[int, dict[str, Any]] = {}
    if selection.header_row is None:
        if headers or any(item.source_header != "" for item in definitions):
            raise ValueError("A data set without headers cannot claim source header text.")
    else:
        expected = range(selection.area.min_column, selection.area.max_column + 1)
        if tuple(item.source.column for item in headers) != tuple(expected):
            raise ValueError("Read the complete original header row, including duplicate headers.")
        occurrences: dict[tuple[str, str | None], int] = {}
        for header in headers:
            _check_source(header, table, selection.header_row, header.source.column)
            key = header.kind, header.raw
            occurrences[key] = occurrences.get(key, 0) + 1
            header_info[header.source.column] = {
                "evidence": _retain(asdict(header)),
                "occurrence": occurrences[key],
            }
    fields = []
    for definition in definitions:
        if selection.header_row is not None:
            original = headers[definition.column - selection.area.min_column]
            if (
                original.kind not in {"text", "blank"}
                or (original.raw or "") != definition.source_header
            ):
                raise ValueError("Mapped header no longer matches literal original text.")
        fields.append(
            {"definition": asdict(definition), "header": header_info.get(definition.column)}
        )
    cells = []
    size = 0
    for column, definition in zip(columns, definitions, strict=True):
        if column.selection != selection or len(column.cells) != rows:
            raise ValueError("Incomplete or mismatched column evidence.")
        for row, cell in enumerate(column.cells, first):
            check_cancelled(cancelled)
            _check_source(cell, table, row, definition.column)
            retained = _retain(asdict(cell))
            record = {
                "row": row,
                "column": definition.column,
                "state": _state(cell, definition.rules.missing_tokens),
                "evidence": retained,
            }
            size += len(canonical(record).encode("utf-8"))
            if size > MAX_RESULT_BYTES:
                raise ValueError("Transformation evidence exceeds the serialized result limit.")
            cells.append(record)
    cells.sort(key=lambda item: (item["row"], item["column"]))
    document = {
        "format_version": 1,
        "foundation_version": FOUNDATION_VERSION,
        "dataset": asdict(table),
        "fields": fields,
        "cells": cells,
        "population": {
            "first_row": first,
            "row_count": rows,
            "mapped_cell_count": len(cells),
            "selected_column_count": selection.area.column_count,
            "unmapped_column_count": selection.area.column_count - len(definitions),
        },
    }
    check_cancelled(cancelled)
    return TransformationSnapshot(_bounded_json(document))


def _check_source(cell: DateEvidence, table: SavedTable, row: int, column: int) -> None:
    source = cell.source
    if (source.source_sha256, source.sheet, source.row, source.column) != (
        table.selection.workbook_sha256,
        table.selection.sheet,
        row,
        column,
    ):
        raise ValueError("Cell evidence has changed, missing or reordered source coordinates.")


@dataclass(frozen=True)
class TransformationOperation:
    id: str
    version: str
    engine: str
    engine_version: str
    parameters_json: str = "{}"

    def __post_init__(self) -> None:
        for name in ("id", "version", "engine", "engine_version"):
            _text(getattr(self, name), name)
        if not ID_PATTERN.fullmatch(self.id) or not VERSION_PATTERN.fullmatch(self.version):
            raise ValueError(
                "Operation requires a stable lowercase ID and major.minor.patch version."
            )
        parameters = parse_json(self.parameters_json, "transformation parameters")
        limit = MAX_TOKEN_BYTES
        if self.id == EXACT_OPERATION:
            if (
                self.version != EXACT_VERSION
                or self.engine != EXACT_ENGINE
                or self.engine_version != EXACT_VERSION
            ):
                raise ValueError("Unsupported exact-rule operation version or engine.")
            read_rule_parameters(self.parameters_json)
            limit = MAX_RULE_BYTES
        if not isinstance(parameters, dict) or len(self.parameters_json.encode("utf-8")) > limit:
            raise ValueError("Operation parameters require a bounded JSON object.")
        if "recipe" in parameters:
            validate_recipe_context(parameters["recipe"])
        object.__setattr__(self, "parameters_json", canonical(parameters))


@dataclass(frozen=True)
class CellProposal:
    row: int
    column: int
    input_text: str
    proposed_text: str | None
    rule_id: str
    reason: str
    status: str = "proposed"

    def __post_init__(self) -> None:
        if any(type(value) is not int or value < 1 for value in (self.row, self.column)):
            raise ValueError("Proposal coordinates must be positive source positions.")
        for name in ("rule_id", "reason"):
            _text(getattr(self, name), name)
        if not ID_PATTERN.fullmatch(self.rule_id):
            raise ValueError("Proposal requires a stable lowercase rule ID.")
        if self.status not in {"proposed", "unresolved", "failed"}:
            raise ValueError("Unsupported proposal status.")
        if (
            not isinstance(self.input_text, str)
            or len(self.input_text.encode("utf-8")) > MAX_TOKEN_BYTES
        ):
            raise ValueError("Proposal input must be bounded literal text.")
        if self.status == "proposed":
            if (
                not isinstance(self.proposed_text, str)
                or len(self.proposed_text.encode("utf-8")) > MAX_TOKEN_BYTES
            ):
                raise ValueError("Proposed text exceeds the token limit or is not text.")
        elif self.proposed_text is not None:
            raise ValueError("Unresolved and failed proposals cannot supply replacement text.")


@dataclass(frozen=True)
class TransformationPreview:
    document_json: str

    @property
    def id(self) -> str:
        return hashlib.sha256(self.document_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.document_json)  # type: ignore[no-any-return]

    def page(self, offset: int = 0, limit: int = MAX_PAGE_SIZE) -> tuple[dict[str, Any], ...]:
        if (
            type(offset) is not int
            or offset < 0
            or type(limit) is not int
            or not 1 <= limit <= MAX_PAGE_SIZE
        ):
            raise ValueError("Use a nonnegative offset and a page size between 1 and 200.")
        return tuple(self.to_dict()["decisions"][offset : offset + limit])


@dataclass(frozen=True)
class TransformationRevision:
    document_json: str

    @property
    def id(self) -> str:
        return hashlib.sha256(self.document_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.document_json)  # type: ignore[no-any-return]


def _values(
    snapshot: TransformationSnapshot, parent: TransformationRevision | None
) -> dict[tuple[int, int], str]:
    if parent is None:
        return {}
    data = parent.to_dict()
    if data["snapshot"] != snapshot.to_dict():
        raise ValueError("Parent revision belongs to different source evidence or mappings.")
    if len(data["steps"]) >= MAX_STEPS:
        raise ValueError("Transformation revision exceeds the ordered-step limit.")
    values = {}
    for step in data["steps"]:
        approved = {tuple(item) for item in step["approval"]["selected_cells"]}
        for decision in step["preview"]["decisions"]:
            key = decision["row"], decision["column"]
            if key in approved:
                values[key] = decision["proposed_text"]
    return values


def _preview_transformation(
    snapshot: TransformationSnapshot,
    operation: TransformationOperation,
    proposals: tuple[CellProposal, ...],
    *,
    parent: TransformationRevision | None = None,
    cancelled: Event | None = None,
) -> TransformationPreview:
    """Account for every mapped cell; a sparse proposal list never limits coverage."""
    check_cancelled(cancelled)
    if not isinstance(proposals, tuple) or len(proposals) > MAX_CELLS:
        raise ValueError("Proposals must be a bounded immutable sequence.")
    lookup = {(p.row, p.column): p for p in proposals}
    if len(lookup) != len(proposals):
        raise ValueError("Duplicate or conflicting proposals for a source cell.")
    data = snapshot.to_dict()
    if len(data["cells"]) > MAX_CELLS:
        raise ValueError("Transformation selection exceeds the mapped-cell limit.")
    fields = {item["definition"]["column"]: item["definition"] for item in data["fields"]}
    exact_column, exact_rules = None, {}
    if operation.id == EXACT_OPERATION:
        exact_column, settings = read_rule_parameters(operation.parameters_json)
        if exact_column not in fields:
            raise ValueError("Exact rules require a mapped source column.")
        validate_rule_field(fields[exact_column], settings)
        exact_rules = {rule.source: rule for rule in settings.rules}
    values = _values(snapshot, parent)
    decisions = []
    counts = dict.fromkeys(OUTCOMES, 0)
    eligible = 0
    size = len(snapshot.document_json.encode("utf-8"))
    for cell in data["cells"]:
        check_cancelled(cancelled)
        key = cell["row"], cell["column"]
        definition = fields[cell["column"]]
        field = definition["field"]
        proposal = lookup.pop(key, None)
        source_raw = cell["evidence"]["raw"]
        current = values.get(key, source_raw if isinstance(source_raw, str) else None)
        outcome, reason = "unchanged", "no_proposal"
        if _has_reference(cell["evidence"]):
            outcome, reason = "unresolved", "source_token_limit"
        elif cell["state"] == "unsupported":
            outcome, reason = "unresolved", "unsupported_source_evidence"
        elif not free_text(field) and not (key[1] == exact_column and exact_field(field)):
            outcome, reason = "ineligible", "mapped_field_not_free_text"
        elif cell["state"] != "text":
            outcome, reason = "ineligible", "source_" + cell["state"]
        else:
            eligible += 1
        if exact_column is not None:
            rule = (
                exact_rules.get(current)
                if key[1] == exact_column and outcome == "unchanged" and isinstance(current, str)
                else None
            )
            expected = (
                CellProposal(
                    key[0],
                    key[1],
                    rule.source,
                    rule.target,
                    rule.id,
                    "Reviewed exact literal replacement.",
                )
                if rule is not None
                else None
            )
            if proposal != expected:
                raise ValueError(
                    "Exact proposals must cover every eligible literal match and follow the saved rule table."
                )
        if proposal is not None:
            if outcome in {"ineligible", "unresolved"}:
                raise ValueError("A proposal targets an ineligible or unresolved source cell.")
            if proposal.input_text != current:
                raise ValueError("Proposal input differs from the current literal derived value.")
            reason = proposal.reason
            if proposal.status != "proposed":
                outcome = proposal.status
            elif proposal.proposed_text == current:
                outcome = "unchanged"
            elif (
                not proposal.proposed_text
                or proposal.proposed_text.isspace()
                or proposal.proposed_text in definition["rules"]["missing_tokens"]
            ):
                outcome, reason = "unresolved", "replacement_changes_missingness"
            else:
                outcome = "changed"
        decision = {
            "row": key[0],
            "column": key[1],
            "input_text": current,
            "proposed_text": proposal.proposed_text if proposal is not None else None,
            "outcome": outcome,
            "reason": reason,
            "rule_id": proposal.rule_id if proposal is not None else None,
        }
        counts[outcome] += 1
        size += len(canonical(decision).encode("utf-8"))
        if size > MAX_RESULT_BYTES:
            raise ValueError("Transformation evidence exceeds the serialized result limit.")
        decisions.append(decision)
    if lookup:
        raise ValueError("Proposal falls outside the complete mapped population.")
    document = {
        "format_version": 1,
        "foundation_version": FOUNDATION_VERSION,
        "snapshot_id": snapshot.id,
        "parent_revision_id": parent.id if parent else None,
        "operation": asdict(operation),
        "proposals": [asdict(item) for item in sorted(proposals, key=lambda p: (p.row, p.column))],
        "decisions": decisions,
        "reconciliation": {**data["population"], "eligible": eligible, **counts},
    }
    check_cancelled(cancelled)
    return TransformationPreview(_bounded_json(document))


@dataclass(frozen=True)
class TransformationApproval:
    preview_id: str
    selected_cells: tuple[tuple[int, int], ...]
    reviewer: str
    justification: str
    decided_at_utc: str

    def __post_init__(self) -> None:
        for name in ("reviewer", "justification"):
            _text(getattr(self, name), name)
        if not isinstance(self.selected_cells, tuple) or any(
            not isinstance(key, tuple)
            or len(key) != 2
            or any(type(v) is not int or v < 1 for v in key)
            for key in self.selected_cells
        ):
            raise ValueError("Approval requires explicit immutable source coordinates.")
        if len(set(self.selected_cells)) != len(self.selected_cells):
            raise ValueError("Approval contains duplicate source coordinates.")
        moment = datetime.fromisoformat(self.decided_at_utc)
        if moment.tzinfo is None or moment.utcoffset() != UTC.utcoffset(moment):
            raise ValueError("Approval requires an explicit UTC decision time.")


def _apply_transformation(
    snapshot: TransformationSnapshot,
    preview: TransformationPreview,
    approval: TransformationApproval,
    *,
    parent: TransformationRevision | None = None,
    cancelled: Event | None = None,
) -> TransformationRevision:
    """Validate and stage an entire revision before returning it; never mutate inputs."""
    data = preview.to_dict()
    reproduced = _preview_transformation(
        snapshot,
        TransformationOperation(**data["operation"]),
        tuple(CellProposal(**item) for item in data["proposals"]),
        parent=parent,
        cancelled=cancelled,
    )
    if reproduced != preview or approval.preview_id != preview.id:
        raise ValueError("Preview or approval is stale or has been modified; preview again.")
    if data["reconciliation"]["failed"]:
        raise ValueError("Failed transformation decisions block the entire revision.")
    changes = {
        (item["row"], item["column"]) for item in data["decisions"] if item["outcome"] == "changed"
    }
    if set(approval.selected_cells) - changes:
        raise ValueError("Approval may select only explicitly proposed changes.")
    previous = parent.to_dict()["steps"] if parent else []
    step = {
        "preview": data,
        "approval": asdict(approval),
        "applied_count": len(approval.selected_cells),
        "rejected_count": len(changes) - len(approval.selected_cells),
    }
    result = TransformationRevision(
        _bounded_json(
            {
                "format_version": 1,
                "foundation_version": FOUNDATION_VERSION,
                "snapshot": snapshot.to_dict(),
                "steps": [*previous, step],
            }
        )
    )
    check_cancelled(cancelled)
    return result


def replay_revision(
    snapshot: TransformationSnapshot, document_json: str, *, cancelled: Event | None = None
) -> TransformationRevision:
    """Check all decisions and approvals against current original evidence, without engines."""
    if len(document_json.encode("utf-8")) > MAX_RESULT_BYTES:
        raise ValueError("Transformation evidence exceeds the serialized result limit.")
    data = parse_json(document_json, "transformation revision")
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("steps"), list)
        or not 1 <= len(data["steps"]) <= MAX_STEPS
    ):
        raise ValueError("Invalid transformation revision or ordered-step limit.")
    if data.get("snapshot") != snapshot.to_dict():
        raise ValueError("Revision source evidence or dictionary mappings changed.")
    parent = None
    for step in data["steps"]:
        check_cancelled(cancelled)
        saved = step["approval"]
        approval = TransformationApproval(
            saved["preview_id"],
            tuple(tuple(key) for key in saved["selected_cells"]),
            saved["reviewer"],
            saved["justification"],
            saved["decided_at_utc"],
        )
        parent = _apply_transformation(
            snapshot,
            TransformationPreview(canonical(step["preview"])),
            approval,
            parent=parent,
            cancelled=cancelled,
        )
    assert parent is not None
    if parent.document_json != canonical(data):
        raise ValueError("Revision does not match replay; unsupported format or altered results.")
    return parent


def preview_transformation(
    snapshot: TransformationSnapshot,
    operation: TransformationOperation,
    proposals: tuple[CellProposal, ...],
    *,
    parent: TransformationRevision | None = None,
    cancelled: Event | None = None,
) -> TransformationPreview:
    """Preview a complete population, validating any supplied parent by replay first."""
    if parent is not None:
        parent = replay_revision(snapshot, parent.document_json, cancelled=cancelled)
    return _preview_transformation(
        snapshot, operation, proposals, parent=parent, cancelled=cancelled
    )


def apply_transformation(
    snapshot: TransformationSnapshot,
    preview: TransformationPreview,
    approval: TransformationApproval,
    *,
    parent: TransformationRevision | None = None,
    cancelled: Event | None = None,
) -> TransformationRevision:
    """Apply only explicitly selected changes to a verified parent; inputs are immutable."""
    if parent is not None:
        parent = replay_revision(snapshot, parent.document_json, cancelled=cancelled)
    return _apply_transformation(snapshot, preview, approval, parent=parent, cancelled=cancelled)


def derived_text_values(revision: TransformationRevision) -> tuple[tuple[int, int, str], ...]:
    """Return the approved text overlay only; original rows and other cells stay in source."""
    values: dict[tuple[int, int], str] = {}
    for step in revision.to_dict()["steps"]:
        selected = {tuple(key) for key in step["approval"]["selected_cells"]}
        for decision in step["preview"]["decisions"]:
            key = decision["row"], decision["column"]
            if key in selected:
                values[key] = decision["proposed_text"]
    return tuple((row, column, value) for (row, column), value in sorted(values.items()))
