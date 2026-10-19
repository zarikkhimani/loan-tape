"""Compose approved text and compatible date results over complete raw source evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any

from loan_tape._date_json import canonical
from loan_tape.column_definitions import DefinitionScope
from loan_tape.date_parser import DateEvidence
from loan_tape.date_reader import read_excel_date_columns
from loan_tape.date_runs import SavedDateRun, verify_analysis
from loan_tape.packs import Catalog
from loan_tape.ranges import column_label
from loan_tape.recipe_context import validate_complete_recipe_history
from loan_tape.selection import SavedTable
from loan_tape.text_export_excel import MAX_EXPORT_BYTES, validate_payload
from loan_tape.transformation_excel import read_transformation_snapshot
from loan_tape.transformations import TransformationRevision, derived_text_values, replay_revision
from loan_tape.workbook_index import check_cancelled

EXPORT_VERSION = "1.0.0"
MAX_COMPLETE_CELLS = 200_000
JSON_CHUNK_SIZE = 8000


class _Budget:
    def __init__(self, cancelled: Event | None) -> None:
        self.bytes = 0
        self.cancelled = cancelled

    def append(self, rows: list[list[Any]], row: list[Any]) -> None:
        check_cancelled(self.cancelled)
        self.bytes += len(canonical(row).encode("utf-8")) + 1
        if self.bytes > MAX_EXPORT_BYTES or len(rows) >= 1_048_576:
            raise ValueError("Export evidence exceeds its byte or worksheet row limit.")
        rows.append(row)

    def extend(self, rows: list[list[Any]], values: Iterable[list[Any]]) -> None:
        for row in values:
            self.append(rows, row)


def _chunks(section: str, identity: str, value: Any) -> list[list[Any]]:
    encoded = canonical(value)
    parts = [encoded[i : i + JSON_CHUNK_SIZE] for i in range(0, len(encoded), JSON_CHUNK_SIZE)]
    return [[section, identity, i + 1, len(parts), part] for i, part in enumerate(parts)]


def _utc(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _literal(cell: DateEvidence) -> str | None:
    if cell.kind == "formula":
        if not cell.formula:
            raise ValueError(
                "A source formula lacks literal expression text; export cannot preserve it."
            )
        return "=" + cell.formula
    if cell.kind == "unsupported":
        raise ValueError("An unsupported source cell cannot be exported faithfully.")
    return cell.raw


def _date_overlay(
    run: SavedDateRun,
    table: SavedTable,
    scope: DefinitionScope,
    catalog: Catalog,
    evidence: dict[tuple[int, int], DateEvidence],
    cancelled: Event | None,
) -> tuple[dict[tuple[int, int], str], dict[str, Any]]:
    verify_analysis(run.analysis, cancelled=cancelled)
    data = run.analysis.to_dict()
    inputs = data["inputs"]
    selection = table.selection
    if inputs["dataset"] != {
        "id": table.id,
        "name": table.name,
        "source_sha256": selection.workbook_sha256,
        "sheet": selection.sheet,
        "range": selection.area.address,
        "header_row": selection.header_row,
    }:
        raise ValueError(
            "Date and text results must use the same source and complete saved data set."
        )
    active = {pack.id: pack for pack in catalog.packs}
    for saved in inputs["dictionaries"]:
        pack = active.get(saved["id"])
        if pack is None or (pack.version, pack.fingerprint) != (
            saved["version"],
            saved["fingerprint"],
        ):
            raise ValueError(
                "Date dictionary changed; review the date run before composing results."
            )
    definitions = {definition.column: definition for definition in scope.definitions}
    for binding in inputs["bindings"]:
        definition = definitions.get(binding["column"])
        if definition is not None:
            profile = binding["profile"]
            if (
                definition.field.id != binding["field_id"]
                or definition.field.data_type != "date"
                or list(definition.date_formats) != profile["text_formats"]
                or definition.two_digit_year_start != profile["two_digit_year_start"]
                or list(definition.rules.missing_tokens) != profile["missing_tokens"]
            ):
                raise ValueError(
                    "Date and text column mappings or interpretation settings conflict."
                )
    for column in inputs["evidence"]:
        for saved_cell in column["cells"]:
            check_cancelled(cancelled)
            location = saved_cell["source"]
            current = evidence.get((location["row"], location["column"]))
            if current is None or canonical(asdict(current)) != canonical(saved_cell):
                raise ValueError("Date run evidence differs from the complete original source.")
    overlay = {}
    for column in data["results"]["columns"]:
        for cell in column["cells"]:
            if cell["status"] == "valid":
                overlay[(cell["row"], column["column"])] = cell["parsed_date"]
    return overlay, data


def build_text_export(
    source: Path,
    table: SavedTable,
    scope: DefinitionScope,
    catalog: Catalog,
    revision: TransformationRevision,
    *,
    date_run: SavedDateRun | None = None,
    writer_version: str = "Unwritten payload preview",
    cancelled: Event | None = None,
) -> dict[str, Any]:
    check_cancelled(cancelled)
    area = table.selection.area
    if area.row_count * area.column_count > MAX_COMPLETE_CELLS:
        raise ValueError("Text export exceeds the 200,000 complete selected-cell limit.")
    snapshot = read_transformation_snapshot(source, table, scope, catalog, cancelled=cancelled)
    revision = replay_revision(snapshot, revision.document_json, cancelled=cancelled)
    validate_complete_recipe_history(revision.to_dict()["steps"], snapshot.id)
    budget = _Budget(cancelled)
    columns = read_excel_date_columns(
        source,
        replace(table.selection, header_row=None),
        tuple(range(area.min_column, area.max_column + 1)),
        cancelled=cancelled,
        max_rows=MAX_COMPLETE_CELLS,
    )
    raw = {(cell.source.row, cell.source.column): cell for col in columns for cell in col.cells}
    text = {(r, c): value for r, c, value in derived_text_values(revision)}
    dates, date_data = (
        _date_overlay(date_run, table, scope, catalog, raw, cancelled) if date_run else ({}, None)
    )
    if text.keys() & dates.keys():
        raise ValueError(
            "Text and date results propose conflicting changes to the same source cell."
        )
    overlay = text | dates
    rows: list[list[Any]] = []
    evidence_rows: list[list[Any]] = [
        ["Record", "Source cell", "Part", "Parts", "Exact evidence JSON"]
    ]
    for row in range(area.min_row, area.max_row + 1):
        check_cancelled(cancelled)
        output = []
        for column in range(area.min_column, area.max_column + 1):
            key = row, column
            cell = raw[key]
            value = overlay.get(key, _literal(cell))
            output.append(value)
            address = f"{column_label(column)}{row}"
            record = {
                "source": asdict(cell),
                "export_cell": f"{column_label(column - area.min_column + 1)}{row - area.min_row + 1}",
                "export_value": value,
                "applied_from": "text" if key in text else "date" if key in dates else "source",
            }
            budget.extend(evidence_rows, _chunks("cell", address, record))
        budget.append(rows, output)
    steps: list[list[Any]] = [
        [
            "Step",
            "Operation",
            "Version",
            "Engine",
            "Engine version",
            "Approved",
            "Rejected",
            "Reviewer",
            "Reason",
            "Decision UTC",
            "Preview ID",
            "Recipe ID",
            "Recipe version",
            "Recipe fingerprint",
        ]
    ]
    decisions: list[list[Any]] = [
        [
            "Step",
            "Source cell",
            "Input",
            "Proposed",
            "Output after step",
            "Outcome",
            "Approved",
            "Rule",
            "Reason",
        ]
    ]
    summary: list[list[Any]] = [
        ["Reviewed loan tape", "Value"],
        ["Text revision", revision.id],
        ["Source SHA-256", table.selection.workbook_sha256],
        ["Data set", table.name],
        ["Worksheet", table.selection.sheet],
        ["Source range", area.address],
        ["Selected rows including header", area.row_count],
        ["Selected columns", area.column_count],
        ["Selected cells", len(raw)],
        ["Mapped cells", snapshot.to_dict()["population"]["mapped_cell_count"]],
        ["Approved step decisions", 0],
        ["Final text cells differing from source", sum(v != raw[k].raw for k, v in text.items())],
        ["Standardized date values", len(dates)],
        ["Date run", date_run.id if date_run else "Not included"],
        [
            "Representation",
            "Source tokens and standardized ISO dates are literal text. Numeric values are not rounded or retyped.",
        ],
        [
            "Source formulas",
            "Literal expressions only; never calculated. Source Evidence retains storage kinds and missing/empty states.",
        ],
        [
            "Workbook features",
            "New values-only workbook; original formatting, hidden rows, formulas, links and macros are not copied.",
        ],
        ["Writer", "xlwings"],
        ["Writer version", writer_version],
        ["Export version", EXPORT_VERSION],
    ]
    for index, step in enumerate(revision.to_dict()["steps"], 1):
        check_cancelled(cancelled)
        approval = step["approval"]
        chosen = {tuple(key) for key in approval["selected_cells"]}
        operation = step["preview"]["operation"]
        recipe = json.loads(operation["parameters_json"]).get("recipe", {})
        steps.append(
            [
                index,
                operation["id"],
                operation["version"],
                operation["engine"],
                operation["engine_version"],
                step["applied_count"],
                step["rejected_count"],
                approval["reviewer"],
                approval["justification"],
                _utc(approval["decided_at_utc"]),
                approval["preview_id"],
                recipe.get("id"),
                recipe.get("version"),
                recipe.get("fingerprint"),
            ]
        )
        summary[10][1] += len(chosen)
        for item in step["preview"]["decisions"]:
            key = item["row"], item["column"]
            approved = key in chosen
            budget.append(
                decisions,
                [
                    index,
                    f"{column_label(key[1])}{key[0]}",
                    item["input_text"],
                    item["proposed_text"],
                    item["proposed_text"] if approved else item["input_text"],
                    item["outcome"],
                    approved,
                    item["rule_id"],
                    item["reason"],
                ],
            )
    audit = [["Record", "Identity", "Part", "Parts", "Exact JSON (join parts in order)"]]
    budget.extend(audit, _chunks("text_revision", revision.id, revision.to_dict()))
    if date_run:
        budget.extend(
            audit,
            _chunks(
                "date_run",
                date_run.id,
                {
                    "id": date_run.id,
                    "created_at": date_run.created_at.isoformat(),
                    "analysis": date_data,
                },
            ),
        )
    header = table.selection.header_row
    sheets = [
        {
            "name": "Loan Tape",
            "header_row": header - area.min_row + 1 if header is not None else None,
            "rows": rows,
        },
        {"name": "Summary", "header_row": 1, "rows": summary},
        {"name": "Steps", "header_row": 1, "rows": steps},
        {"name": "Cell Decisions", "header_row": 1, "rows": decisions},
        {"name": "Source Evidence", "header_row": 1, "rows": evidence_rows},
        {"name": "Audit", "header_row": 1, "rows": audit},
    ]
    if date_data:
        date_rows = [["Source cell", "Field", "Status", "Standardized date", "Code"]]
        for col in date_data["results"]["columns"]:
            budget.extend(
                date_rows,
                [
                    [
                        f"{column_label(col['column'])}{cell['row']}",
                        col["field_id"],
                        cell["status"],
                        cell["parsed_date"],
                        cell["code"],
                    ]
                    for cell in col["cells"]
                ],
            )
        findings = [["Record", "Identity", "Part", "Parts", "Exact finding JSON"]]
        for index, finding in enumerate(date_data["results"]["findings"], 1):
            budget.extend(findings, _chunks("date_finding", str(index), finding))
        sheets.extend(
            [
                {"name": "Date Results", "header_row": 1, "rows": date_rows},
                {"name": "Date Findings", "header_row": 1, "rows": findings},
            ]
        )
    payload = {
        "format_version": 1,
        "export_version": EXPORT_VERSION,
        "revision_id": revision.id,
        "source_sha256": table.selection.workbook_sha256,
        "date_run_id": date_run.id if date_run else None,
        "sheets": sheets,
    }
    payload["fingerprint"] = hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()
    validate_payload(payload)
    check_cancelled(cancelled)
    return payload
