"""Publish a saved date run through an isolated xlwings/Excel process."""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import time
import warnings
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from datetime import time as clock_time
from pathlib import Path
from threading import Event
from typing import Any
from uuid import uuid4

from openpyxl import load_workbook  # type: ignore[import-untyped]

from loan_tape._date_json import canonical
from loan_tape.date_runs import SavedDateRun, check_run_source, verify_analysis
from loan_tape.excel_process import start_excel, start_in_job
from loan_tape.inspection import CancellableReader, InspectionError, preflight_ooxml
from loan_tape.ooxml_safety import validate_ooxml_archive
from loan_tape.pack_format import load_pack_files
from loan_tape.ranges import parse_range
from loan_tape.workbook_index import _digest, check_cancelled

EXPORT_VERSION = "1.1.0"
MAX_EXPORT_BYTES = 256 * 1024 * 1024
MAX_EXCEL_ROWS = 1_048_576
MAX_LOAN_TAPE_CELLS = 5_000_000
EXPECTED_SHEETS = (
    "Loan Tape",
    "Summary",
    "Findings",
    "Date Results",
    "Pair Results",
    "Audit",
)


@dataclass(frozen=True)
class DateExport:
    path: Path
    sha256: str
    writer: str
    writer_version: str
    run_id: str
    analysis_fingerprint: str
    row_counts: tuple[tuple[str, int], ...]


def _field_definitions(inputs: dict[str, Any]) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for saved in inputs["dictionaries"]:
        pack = load_pack_files(saved["files"], "saved date-run dictionary")
        for field in pack.fields:
            result[f"{pack.id}:{field.id}"] = (field.label, field.definition)
    return result


def _display(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (dict, list, tuple)):
        return canonical(value)
    return str(value)


def _source_value(cell: Any) -> tuple[Any, bool]:
    """Return a values-only export value and whether Excel should receive a typed date."""
    value = cell.value
    if cell.data_type == "f":
        formula = value if isinstance(value, str) else getattr(value, "text", None)
        if not isinstance(formula, str) or not formula:
            raise InspectionError(f"Formula text is unavailable at {cell.coordinate}.")
        return formula, False
    if value is None or isinstance(value, (str, int, float, bool)):
        return value, False
    if isinstance(value, datetime):
        return value.isoformat(), True
    if isinstance(value, date):
        return value.isoformat(), True
    if isinstance(value, clock_time):
        return value.isoformat(), False
    raise InspectionError(
        f"The saved data set contains an unsupported value at {cell.coordinate}: "
        f"{type(value).__name__}."
    )


def _column_widths(rows: list[list[Any]], width: int) -> list[int]:
    sizes = [10] * width
    for row in rows:
        for index, value in enumerate(row):
            length = len(_display(value))
            sizes[index] = min(40, max(sizes[index], length + 2))
    return sizes


def _loan_tape_sheet(
    run: SavedDateRun,
    source_path: Path,
    document: dict[str, Any],
    *,
    cancelled: Event | None = None,
) -> dict[str, Any]:
    """Read the complete saved data set and apply only successful date interpretations."""
    if source_path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise InspectionError("A refined loan-tape export requires its .xlsx or .xlsm source.")
    if check_run_source(run, source_path) != "unchanged":
        raise InspectionError(
            "The preserved source changed or is unavailable; export was not started."
        )

    dataset = document["inputs"]["dataset"]
    area = parse_range(dataset["range"])
    cell_count = area.row_count * area.column_count
    if cell_count > MAX_LOAN_TAPE_CELLS:
        raise ValueError(
            f"The saved data set contains {cell_count:,} cells; the refined export limit is "
            f"{MAX_LOAN_TAPE_CELLS:,}."
        )

    replacements: dict[tuple[int, int], str] = {}
    mapped_columns: set[int] = set()
    for column in document["results"]["columns"]:
        source_column = column["column"]
        mapped_columns.add(source_column)
        for cell in column["cells"]:
            if cell["status"] == "valid":
                parsed = cell["parsed_date"]
                if not isinstance(parsed, str):
                    raise InspectionError("A valid standardized date is missing its parsed value.")
                replacements[(cell["row"], source_column)] = parsed

    rows: list[list[Any]] = []
    typed_date_columns: set[int] = set()
    applied = 0
    preflight_ooxml(source_path, cancelled)
    with CancellableReader(source_path, cancelled) as source:
        book = load_workbook(source, read_only=True, data_only=False, keep_links=False)
        try:
            if dataset["sheet"] not in book.sheetnames:
                raise InspectionError("The saved data-set worksheet is unavailable.")
            sheet = book[dataset["sheet"]]
            sheet.reset_dimensions()
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "error", message="Cell .* marked as a date.*", category=UserWarning
                )
                for row_number, source_row in enumerate(
                    sheet.iter_rows(
                        min_row=area.min_row,
                        max_row=area.max_row,
                        min_col=area.min_column,
                        max_col=area.max_column,
                    ),
                    start=area.min_row,
                ):
                    check_cancelled(cancelled)
                    if len(source_row) != area.column_count:
                        raise InspectionError("The workbook data-set width changed while reading.")
                    values: list[Any] = []
                    for offset, cell in enumerate(source_row):
                        source_column = area.min_column + offset
                        replacement = replacements.get((row_number, source_column))
                        if replacement is not None:
                            values.append(replacement)
                            typed_date_columns.add(offset)
                            applied += 1
                            continue
                        value, typed_date = _source_value(cell)
                        values.append(value)
                        if typed_date:
                            typed_date_columns.add(offset)
                    rows.append(values)
                rows.extend([[None] * area.column_count for _ in range(area.row_count - len(rows))])
        finally:
            book.close()

    if len(rows) != area.row_count or applied != len(replacements):
        raise InspectionError(
            "The complete refined loan tape could not be reconciled to its source."
        )
    if _digest(source_path, cancelled) != dataset["source_sha256"]:
        raise InspectionError("The preserved source changed while the refined export was prepared.")

    header_row = dataset["header_row"]
    relative_header = header_row - area.min_row + 1 if header_row is not None else None
    return {
        "name": "Loan Tape",
        "kind": "loan_tape",
        "rows": rows,
        "header_row": relative_header,
        "date_columns": sorted(typed_date_columns),
        "refined_columns": sorted(column - area.min_column for column in mapped_columns),
        "refined_date_count": applied,
        "widths": _column_widths(rows, area.column_count),
    }


def build_export_payload(
    run: SavedDateRun,
    source_path: Path | None = None,
    *,
    cancelled: Event | None = None,
) -> dict[str, Any]:
    """Build plain, inspectable rows; the Excel worker owns presentation only."""
    if not isinstance(run, SavedDateRun):
        raise ValueError("A completed saved date run is required for export.")
    if source_path is None:
        raise ValueError("A refined loan-tape export requires the preserved source workbook.")
    source_path = source_path.resolve()
    verify_analysis(run.analysis, cancelled=cancelled)
    document = run.analysis.to_dict()
    inputs, results = document["inputs"], document["results"]
    loan_tape = _loan_tape_sheet(
        run,
        source_path,
        document,
        cancelled=cancelled,
    )
    fields = _field_definitions(inputs)
    bindings = {item["column"]: item for item in inputs["bindings"]}
    evidence = {item["column"]: item["cells"] for item in inputs["evidence"]}

    summary_rows: list[list[Any]] = [
        ["Refined loan tape and date review"],
        ["Run", run.id],
        ["Created", run.created_at.isoformat()],
        ["Data set", inputs["dataset"]["name"]],
        ["Worksheet", inputs["dataset"]["sheet"]],
        ["Selected range", inputs["dataset"]["range"]],
        ["Reference date", inputs["reference_date"]],
        ["Reporting date", inputs["reporting_date"] or "Not supplied"],
        ["Exported rows", len(loan_tape["rows"])],
        ["Exported columns", len(loan_tape["widths"])],
        ["Standardized date values applied", loan_tape["refined_date_count"]],
        [],
        ["Review summary"],
        ["Data rows", results["row_count"]],
        ["Mapped date cells", results["cell_count"]],
        ["Rows with all mapped dates interpreted", results["all_dates_interpreted_row_count"]],
        ["Rows with unresolved dates", results["rows_with_unresolved_dates"]],
        ["Rows with findings", results["affected_row_count"]],
        ["Errors", results["finding_counts"]["error"]],
        ["Review items", results["finding_counts"]["review"]],
        ["Information items", results["finding_counts"]["info"]],
        [],
        ["Mapped columns"],
        ["Source column", "Field", "Valid", "Unresolved", "Earliest", "Latest"],
    ]
    for column in results["columns"]:
        label = fields[column["field_id"]][0]
        summary_rows.append(
            [
                column["column"],
                label,
                column["valid_count"],
                column["unresolved_count"],
                column["earliest"] or "",
                column["latest"] or "",
            ]
        )

    finding_headers = ["Severity", "Rule ID", "Columns", "Source rows", "Message", "Details"]
    finding_rows = [
        [
            item["severity"].upper(),
            item["rule_id"],
            ", ".join(map(str, item["columns"])),
            ", ".join(map(str, item["rows"])),
            item["message"],
            canonical(item["details"]),
        ]
        for item in results["findings"]
    ]

    date_headers = [
        "Source row",
        "Source cell",
        "Source column",
        "Field",
        "Original kind",
        "Original value",
        "Storage type",
        "Stored token",
        "Number format",
        "Date system",
        "Present in source",
        "Formula text",
        "Formula attributes",
        "Status",
        "Reason code",
        "Parsed date",
        "Candidates",
        "Matched formats",
        "Missing kind",
        "Notes",
        "Calendar",
        "Calendar business day",
        "Calendar coverage",
        "Calendar basis",
        "Calendar events",
    ]
    date_rows: list[list[Any]] = []
    for column in results["columns"]:
        original_cells = evidence[column["column"]]
        binding = bindings[column["column"]]
        label = fields[binding["field_id"]][0]
        for original, parsed in zip(original_cells, column["cells"], strict=True):
            source = original["source"]
            calendar = parsed["calendar"] or {}
            address = f"{_column_label(source['column'])}{source['row']}"
            date_rows.append(
                [
                    source["row"],
                    address,
                    source["column"],
                    label,
                    original["kind"],
                    original["raw"],
                    original["storage_type"],
                    original["raw_token"],
                    original["number_format"],
                    original["date_system"],
                    _display(original["present"]),
                    original["formula"],
                    _display(original["formula_attributes"]),
                    parsed["status"],
                    parsed["code"],
                    parsed["parsed_date"],
                    ", ".join(parsed["candidates"]),
                    ", ".join(parsed["matched_formats"]),
                    parsed["missing_kind"],
                    "; ".join(parsed["notes"]),
                    calendar.get("calendar_id", ""),
                    _display(calendar.get("business_day")),
                    calendar.get("holiday_coverage", ""),
                    calendar.get("decision_basis", ""),
                    _display(calendar.get("events", [])),
                ]
            )

    parsed_by_column = {
        column["column"]: {cell["row"]: cell["parsed_date"] for cell in column["cells"]}
        for column in results["columns"]
    }
    pair_headers = [
        "Start column",
        "Start field",
        "End column",
        "End field",
        "Source row",
        "Start date",
        "End date",
        "Elapsed calendar days",
        "Status",
    ]
    pair_rows: list[list[Any]] = []
    for pair in results["pairs"]:
        start_label = fields[bindings[pair["start_column"]]["field_id"]][0]
        end_label = fields[bindings[pair["end_column"]]["field_id"]][0]
        for record in pair["records"]:
            row = record["row"]
            pair_rows.append(
                [
                    pair["start_column"],
                    start_label,
                    pair["end_column"],
                    end_label,
                    row,
                    parsed_by_column[pair["start_column"]].get(row),
                    parsed_by_column[pair["end_column"]].get(row),
                    record["elapsed_calendar_days"],
                    record["status"],
                ]
            )

    status_total = sum(sum(column["status_counts"].values()) for column in results["columns"])
    severity_total = sum(results["finding_counts"].values())
    audit_rows: list[list[Any]] = [
        ["Date analysis audit"],
        ["Export format version", EXPORT_VERSION],
        ["Writer", "xlwings"],
        ["Run ID", run.id],
        ["Run created", run.created_at.isoformat()],
        ["Analysis fingerprint", run.analysis.fingerprint],
        ["Analysis engine", document["engine_version"]],
        ["Parser engine", document["parser_version"]],
        ["Source SHA-256", inputs["dataset"]["source_sha256"]],
        ["Worksheet", inputs["dataset"]["sheet"]],
        ["Selected range", inputs["dataset"]["range"]],
        ["Header row", inputs["dataset"]["header_row"]],
        ["Reference date", inputs["reference_date"]],
        ["Reporting date", inputs["reporting_date"] or "Not supplied"],
        [],
        ["Reconciliation", "Expected", "Actual", "Status"],
        [
            "Mapped cell count",
            results["cell_count"],
            status_total,
            "OK" if results["cell_count"] == status_total else "FAILED",
        ],
        [
            "Finding count",
            len(results["findings"]),
            severity_total,
            "OK" if len(results["findings"]) == severity_total else "FAILED",
        ],
        [
            "Column row coverage",
            results["row_count"] * results["column_count"],
            sum(column["row_count"] for column in results["columns"]),
            "OK"
            if results["row_count"] * results["column_count"]
            == sum(column["row_count"] for column in results["columns"])
            else "FAILED",
        ],
        [
            "Exported loan-tape cells",
            len(loan_tape["rows"]) * len(loan_tape["widths"]),
            sum(len(row) for row in loan_tape["rows"]),
            "OK",
        ],
        [
            "Standardized date values applied",
            sum(column["valid_count"] for column in results["columns"]),
            loan_tape["refined_date_count"],
            "OK"
            if sum(column["valid_count"] for column in results["columns"])
            == loan_tape["refined_date_count"]
            else "FAILED",
        ],
        [],
        ["Dictionary snapshots", "Version", "Fingerprint"],
    ]
    for saved in inputs["dictionaries"]:
        audit_rows.append([saved["id"], saved["version"], saved["fingerprint"]])
    audit_rows.extend([[], ["Calendar snapshots", "Version", "Fingerprint"]])
    for saved in inputs["calendars"]:
        snapshot = saved["snapshot"]
        audit_rows.append([snapshot["id"], snapshot["version"], saved["fingerprint"]])
    audit_rows.extend(
        [[], ["Calendar sources and conflict references", "Title", "URL", "Published", "Verified"]]
    )
    seen_sources: set[str] = set()
    for saved in inputs["calendars"]:
        for source in saved["snapshot"]["sources"]:
            if source["id"] in seen_sources:
                continue
            seen_sources.add(source["id"])
            audit_rows.append(
                [
                    source["id"],
                    source["title"],
                    source["url"],
                    source["published_on"] or "Not stated",
                    source["verified_on"],
                ]
            )
    audit_rows.extend([[], ["Calendar assumptions"]])
    assumptions: set[str] = set()
    for saved in inputs["calendars"]:
        assumptions.update(saved["snapshot"]["assumptions"])
    audit_rows.extend([[item] for item in sorted(assumptions)])

    sheets = [
        loan_tape,
        {"name": "Summary", "kind": "summary", "rows": summary_rows},
        {"name": "Findings", "kind": "table", "headers": finding_headers, "rows": finding_rows},
        {"name": "Date Results", "kind": "table", "headers": date_headers, "rows": date_rows},
        {"name": "Pair Results", "kind": "table", "headers": pair_headers, "rows": pair_rows},
        {"name": "Audit", "kind": "audit", "rows": audit_rows},
    ]
    for sheet in sheets:
        total = len(sheet["rows"]) + (1 if "headers" in sheet else 0)
        if total > MAX_EXCEL_ROWS:
            raise ValueError(f"{sheet['name']} exceeds Excel's row limit.")
    return {
        "format_version": 2,
        "export_version": EXPORT_VERSION,
        "run_id": run.id,
        "analysis_fingerprint": run.analysis.fingerprint,
        "source_sha256": inputs["dataset"]["source_sha256"],
        "sheets": sheets,
    }


def _column_label(column: int) -> str:
    result = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _normalized_cell(value: Any) -> Any:
    """Normalize Excel's typed date objects and intentional blank cells for comparison."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.time().isoformat() == "00:00:00":
            return value.date().isoformat()
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _validate_output(path: Path, payload: dict[str, Any]) -> tuple[tuple[str, int], ...]:
    if not path.is_file() or path.stat().st_size == 0:
        raise InspectionError("Excel did not create the refined loan-tape workbook.")
    if path.stat().st_size > MAX_EXPORT_BYTES:
        raise InspectionError("The refined loan-tape workbook exceeds the export size limit.")
    try:
        with zipfile.ZipFile(path) as archive:
            validate_ooxml_archive(archive, error_type=InspectionError)
            names = archive.namelist()
            if any(
                name.startswith(("xl/externalLinks/", "xl/connections"))
                or name.endswith(("vbaProject.bin", ".bin"))
                for name in names
            ):
                raise InspectionError(
                    "The refined loan-tape workbook contains unexpected executable or linked content."
                )
        book = load_workbook(path, read_only=True, data_only=False, keep_links=False)
        try:
            if tuple(book.sheetnames) != EXPECTED_SHEETS:
                raise InspectionError(
                    "The refined loan-tape workbook has unexpected or missing worksheets: "
                    f"{book.sheetnames}."
                )
            expected_sheets = {item["name"]: item for item in payload["sheets"]}
            actual: list[tuple[str, int]] = []
            for sheet in book.worksheets:
                specification = expected_sheets[sheet.title]
                expected_rows = (
                    [specification["headers"], *specification["rows"]]
                    if "headers" in specification
                    else specification["rows"]
                )
                expected_width = max((len(row) for row in expected_rows), default=1)
                if sheet.max_column != expected_width:
                    raise InspectionError(
                        f"{sheet.title} column count does not reconcile: "
                        f"expected {expected_width}, found {sheet.max_column}."
                    )
                if sheet.max_row != len(expected_rows):
                    raise InspectionError(
                        f"{sheet.title} row count does not reconcile: "
                        f"expected {len(expected_rows)}, found {sheet.max_row}."
                    )
                for row_number, (cells, expected) in enumerate(
                    zip(
                        sheet.iter_rows(
                            min_row=1,
                            max_row=len(expected_rows),
                            min_col=1,
                            max_col=expected_width,
                        ),
                        expected_rows,
                        strict=True,
                    ),
                    start=1,
                ):
                    padded = [*expected, *([None] * (expected_width - len(expected)))]
                    for column_number, (cell, expected_value) in enumerate(
                        zip(cells, padded, strict=True), start=1
                    ):
                        if cell.data_type == "f":
                            raise InspectionError(
                                "The refined loan-tape workbook contains a formula; "
                                "source text must remain literal."
                            )
                        if _normalized_cell(cell.value) != _normalized_cell(expected_value):
                            address = f"{_column_label(column_number)}{row_number}"
                            raise InspectionError(
                                f"{sheet.title}!{address} does not match the analyzed payload."
                            )
                actual.append((sheet.title, sheet.max_row))
            audit = book["Audit"]
            if audit["B3"].value != "xlwings" or audit["B4"].value != payload["run_id"]:
                raise InspectionError(
                    "The refined loan-tape workbook lost its writer or run identity."
                )
            if audit["B6"].value != payload["analysis_fingerprint"]:
                raise InspectionError("The refined loan-tape workbook lost its analysis identity.")
            return tuple(actual)
        finally:
            book.close()
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        raise InspectionError(
            f"The saved refined loan-tape workbook could not be validated: {error}"
        ) from error


def export_date_run(
    run: SavedDateRun,
    target: Path,
    *,
    source_path: Path | None = None,
    cancelled: Event | None = None,
    timeout: float = 120,
) -> DateExport:
    """Create a new .xlsx with xlwings. No source workbook is opened or overwritten."""
    check_cancelled(cancelled)
    if sys.platform != "win32":
        raise InspectionError(
            "Refined loan-tape export requires Windows and desktop Microsoft Excel."
        )
    if target.suffix.lower() != ".xlsx":
        raise ValueError("Refined loan-tape exports require a new .xlsx file.")
    target = target.resolve()
    if target.exists():
        raise FileExistsError("Choose a new output name; existing files are not overwritten.")
    if source_path is not None:
        source_path = source_path.resolve()
        if target == source_path:
            raise ValueError("The refined loan tape must be separate from the preserved source.")
        source_state = check_run_source(run, source_path)
        if source_state != "unchanged":
            raise InspectionError(
                f"The preserved source is {source_state}; export was not started."
            )
    if source_path is None:
        raise ValueError("A refined loan-tape export requires the preserved source workbook.")
    payload = build_export_payload(run, source_path, cancelled=cancelled)
    encoded = canonical(payload).encode("utf-8")
    if len(encoded) > MAX_EXPORT_BYTES:
        raise ValueError("Date export payload exceeds the supported size limit.")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.stem}.{uuid4().hex}.tmp.xlsx")
    workspace = (Path.cwd() / ".artifacts" / "date-exports").resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="write-", dir=workspace) as directory:
        work = Path(directory)
        payload_path, result_path = work / "payload.json", work / "result.json"
        payload_path.write_bytes(encoded)
        win32job = importlib.import_module("win32job")
        job = win32job.CreateJobObject(None, "LoanTapeDateExport-" + uuid4().hex)
        excel_process = worker_process = None
        try:
            limits = win32job.QueryInformationJobObject(
                job, win32job.JobObjectExtendedLimitInformation
            )
            limits["BasicLimitInformation"]["LimitFlags"] |= (
                win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            win32job.SetInformationJobObject(
                job, win32job.JobObjectExtendedLimitInformation, limits
            )
            check_cancelled(cancelled)
            excel_process, excel_pid = start_excel(job)
            python = Path(sys.executable)
            if python.name.lower() == "pythonw.exe":
                python = python.with_name("python.exe")
            worker_process, _ = start_in_job(
                str(python),
                [
                    "-m",
                    "loan_tape.date_export_worker",
                    str(payload_path),
                    str(staging),
                    str(result_path),
                    str(excel_pid),
                ],
                job,
            )
            events = importlib.import_module("win32event")
            process_api = importlib.import_module("win32process")
            started = time.monotonic()
            while True:
                check_cancelled(cancelled)
                if time.monotonic() - started > timeout:
                    raise InspectionError(
                        "Refined loan-tape export timed out; no completed file was published."
                    )
                if events.WaitForSingleObject(worker_process, 200) == 0:
                    break
            if process_api.GetExitCodeProcess(worker_process):
                raise InspectionError("Excel could not create the refined loan-tape workbook.")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            if "error" in result:
                detail = result.get("detail", "No additional detail was returned.")
                raise InspectionError(f"{result['error']} {detail}")
        finally:
            export_failed = sys.exc_info()[0] is not None
            try:
                win32job.TerminateJobObject(job, 0)
                events = importlib.import_module("win32event")
                for handle in (worker_process, excel_process):
                    if handle is not None and events.WaitForSingleObject(handle, 5000) != 0:
                        raise InspectionError("An owned Excel export process did not shut down.")
            finally:
                for handle in (worker_process, excel_process):
                    if handle is not None:
                        handle.Close()
                job.Close()
                if export_failed or sys.exc_info()[0] is not None:
                    staging.unlink(missing_ok=True)
        try:
            check_cancelled(cancelled)
            counts = _validate_output(staging, payload)
            if source_path is not None and check_run_source(run, source_path) != "unchanged":
                raise InspectionError(
                    "The preserved source changed during export; no file was published."
                )
            os.link(staging, target)
            check_cancelled(cancelled)
            if _validate_output(target, payload) != counts:
                raise InspectionError(
                    "The published refined loan tape differs from its validated staging file."
                )
            digest = _digest(target, cancelled)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        finally:
            staging.unlink(missing_ok=True)
    return DateExport(
        target,
        digest,
        "xlwings",
        str(result["writer_version"]),
        run.id,
        run.analysis.fingerprint,
        counts,
    )
