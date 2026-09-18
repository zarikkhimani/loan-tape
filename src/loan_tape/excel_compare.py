"""Compare independent preview readers without changing either source."""

from __future__ import annotations

import hashlib
import importlib
import json
import re
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any
from uuid import uuid4
from zipfile import ZipFile

from defusedxml.ElementTree import iterparse  # type: ignore[import-untyped]

from loan_tape.excel_process import start_excel, start_in_job
from loan_tape.inspection import (
    CancellableReader,
    FilePreview,
    InspectionError,
    PreviewCell,
    check_read_cancelled,
    read_preview,
)
from loan_tape.ooxml_safety import validate_ooxml_archive
from loan_tape.ranges import CellRange


@dataclass(frozen=True)
class ComparedPreview:
    primary: FilePreview
    secondary: FilePreview | None
    message: str
    differences: frozenset[tuple[int, int]] = frozenset()


class ComparisonSkipped(InspectionError):
    """Excel must not open this source under the project's inspection policy."""


def check_excel_input(path: Path, cancelled: Event | None = None) -> None:
    """Conservatively admit plain OOXML data workbooks before Excel sees them.

    This is an inspection-policy gate, not a general malware scanner. Refuse
    unrecognized package features instead of trying to disable them after opening.
    """
    allowed = re.compile(
        r"(?:\[Content_Types\]\.xml|_rels/\.rels|docProps/(?:app|core|custom)\.xml|"
        r"xl/(?:workbook|styles|sharedStrings)\.xml|xl/_rels/workbook\.xml\.rels|"
        r"xl/theme/theme\d+\.xml|xl/worksheets/sheet\d+\.xml)"
    )
    check_read_cancelled(cancelled)
    with CancellableReader(path, cancelled) as source, ZipFile(source) as archive:
        members = validate_ooxml_archive(
            archive,
            error_type=ComparisonSkipped,
            cancelled=lambda: check_read_cancelled(cancelled),
        )
        if sum(item.file_size for item in members) > 200 * 1024 * 1024:
            raise ComparisonSkipped("Excel comparison skipped: workbook exceeds inspection limits.")
        for item in members:
            if not allowed.fullmatch(item.filename):
                raise ComparisonSkipped(
                    "Excel comparison skipped: workbook contains features beyond plain data sheets "
                    "(such as macros, links, connections, tables, or embedded objects)."
                )
            with archive.open(item) as stream:
                for _, element in iterparse(stream, events=("end",)):
                    check_read_cancelled(cancelled)
                    local_name = element.tag.rsplit("}", 1)[-1]
                    if local_name in {"f", "formula", "formula1", "formula2", "definedName"}:
                        raise ComparisonSkipped(
                            "Excel comparison skipped: workbook contains formulas or named definitions. "
                            "Inspection does not run source formulas."
                        )
                    if (
                        local_name == "Relationship"
                        and element.get("TargetMode", "").lower() == "external"
                    ):
                        raise ComparisonSkipped(
                            "Excel comparison skipped: workbook contains external links."
                        )
                    element.clear()


def _decode_preview(payload: dict[str, Any]) -> FilePreview:
    return FilePreview(
        rows=tuple(tuple(PreviewCell(**cell) for cell in row) for row in payload["rows"]),
        column_count=payload["column_count"],
        more_rows=payload["more_rows"],
        more_columns=payload["more_columns"],
        sheets=tuple(payload["sheets"]),
        selected_sheet=payload["selected_sheet"],
        reading_note=payload["reading_note"],
        start_row=payload.get("start_row", 1),
        start_column=payload.get("start_column", 1),
    )


def read_xlwings_preview(
    path: Path,
    *,
    sheet: str | None = None,
    cancelled: Event | None = None,
    timeout: float = 45,
    area: CellRange | None = None,
) -> FilePreview:
    if sys.platform != "win32":
        raise InspectionError(
            "Excel comparison unavailable: this reader requires Windows and desktop Excel."
        )
    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise ComparisonSkipped("Excel comparison supports .xlsx and .xlsm data workbooks.")
    if cancelled is not None and cancelled.is_set():
        raise InspectionError("Excel comparison cancelled.")
    # Copy to a project-local workspace. Excel never opens the original or intake copy.
    workspace = (Path.cwd() / ".artifacts" / "excel-comparison").resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="read-", dir=workspace) as directory:
        work = Path(directory)
        assert work.resolve().is_relative_to(workspace)
        snapshot = work / ("source" + path.suffix.lower())
        with CancellableReader(path, cancelled) as source, snapshot.open("wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
        check_excel_input(snapshot, cancelled)
        with CancellableReader(snapshot, cancelled) as stream:
            before = hashlib.file_digest(stream, "sha256").digest()
        win32job = importlib.import_module("win32job")
        job_name = "LoanTapeRead-" + uuid4().hex
        job = win32job.CreateJobObject(None, job_name)
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
            check_read_cancelled(cancelled)
            excel_process, excel_pid = start_excel(job)
            python = Path(sys.executable)
            if python.name.lower() == "pythonw.exe":
                python = python.with_name("python.exe")
            result_path = work / "result.json"
            arguments = [
                "-m",
                "loan_tape.excel_worker",
                str(snapshot),
                sheet or "",
                str(excel_pid),
                area.address if area else "",
                str(result_path),
            ]
            check_read_cancelled(cancelled)
            worker_process, _ = start_in_job(str(python), arguments, job)
            events = importlib.import_module("win32event")
            process_api = importlib.import_module("win32process")
            started = time.monotonic()
            while True:
                check_read_cancelled(cancelled)
                if time.monotonic() - started > timeout:
                    raise InspectionError(
                        "Excel comparison timed out. The openpyxl preview remains available."
                    )
                if events.WaitForSingleObject(worker_process, 200) == 0:
                    break
            if process_api.GetExitCodeProcess(worker_process):
                raise InspectionError(
                    "Excel comparison could not start. Check that desktop Excel is available."
                )
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            if "error" in payload:
                raise InspectionError(payload["error"])
        finally:
            # Both processes (including any Python launcher children) are in the
            # job before their first instruction. Never terminate by image name.
            try:
                win32job.TerminateJobObject(job, 0)
                events = importlib.import_module("win32event")
                for handle in (worker_process, excel_process):
                    if handle is not None and events.WaitForSingleObject(handle, 5000) != 0:
                        raise InspectionError(
                            "An owned Excel reader process did not finish shutting down."
                        )
                deadline = time.monotonic() + 5
                while win32job.QueryInformationJobObject(
                    job, win32job.JobObjectBasicAccountingInformation
                )["ActiveProcesses"]:
                    if time.monotonic() > deadline:
                        raise InspectionError(
                            "Owned Excel reader processes are still shutting down."
                        )
                    time.sleep(0.01)
            finally:
                for handle in (worker_process, excel_process):
                    if handle is not None:
                        handle.Close()
                job.Close()
        with snapshot.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").digest() != before:
                raise InspectionError(
                    "Excel changed its temporary copy; comparison results were discarded."
                )
        return _decode_preview(payload["preview"])


def compare_previews(primary: FilePreview, secondary: FilePreview) -> ComparedPreview:
    if (
        primary.sheets != secondary.sheets
        or primary.selected_sheet != secondary.selected_sheet
        or (primary.start_row, primary.start_column)
        != (secondary.start_row, secondary.start_column)
    ):
        return ComparedPreview(
            primary, secondary, "Readers report different worksheet lists or selections."
        )
    differences: set[tuple[int, int]] = set()
    for row in range(max(len(primary.rows), len(secondary.rows))):
        left = primary.rows[row] if row < len(primary.rows) else ()
        right = secondary.rows[row] if row < len(secondary.rows) else ()
        for column in range(max(len(left), len(right))):
            a = left[column].text if column < len(left) else ""
            b = right[column].text if column < len(right) else ""
            if a != b:
                differences.add((row, column))
    count = len(differences)
    message = (
        f"Excel comparison: {count} cell value differences in the preview. Highlighted rows need review."
        if count
        else "Excel comparison: displayed cell values agree. This checks the preview only."
    )
    return ComparedPreview(primary, secondary, message, frozenset(differences))


def read_parallel_preview(
    path: Path,
    *,
    sheet: str | None = None,
    encoding: str = "Automatic",
    delimiter: str = "Automatic",
    cancelled: Event | None = None,
    area: CellRange | None = None,
) -> FilePreview | ComparedPreview:
    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        return read_preview(
            path, sheet=sheet, encoding=encoding, delimiter=delimiter, cancelled=cancelled
        )
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="preview-reader") as readers:
        primary = readers.submit(read_preview, path, sheet=sheet, area=area, cancelled=cancelled)
        secondary = readers.submit(
            read_xlwings_preview, path, sheet=sheet, cancelled=cancelled, area=area
        )
        source = primary.result()
        try:
            excel = secondary.result()
        except InspectionError as error:
            return ComparedPreview(source, None, str(error))
        except Exception:
            return ComparedPreview(
                source, None, "Excel comparison failed. The openpyxl preview remains available."
            )
        return compare_previews(source, excel)
