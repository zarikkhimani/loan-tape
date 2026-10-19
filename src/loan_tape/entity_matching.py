"""Current-source checks, owned matcher execution, and atomic relationship artifacts."""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any
from uuid import uuid4

from loan_tape._date_json import fingerprint
from loan_tape.column_definitions import DefinitionScope, definitions_for_table
from loan_tape.entities import (
    MAX_BYTES,
    MAX_ROWS,
    EntityPopulation,
    EntityRun,
    PairLabel,
    bounded,
    labels_payload,
    prepare_population,
    validate_labels,
    validate_threshold,
)
from loan_tape.excel_process import start_in_job
from loan_tape.packs import Catalog, PackStore
from loan_tape.selection import SavedTable, load_tables
from loan_tape.transformation_excel import read_transformation_snapshot
from loan_tape.transformations import TransformationRevision
from loan_tape.workbook_index import check_cancelled


def entity_scope(table: SavedTable) -> DefinitionScope:
    return DefinitionScope(table.id, table.name, table.selection, definitions_for_table(table))


def read_population(
    source: Path,
    table: SavedTable,
    scope: DefinitionScope,
    catalog: Catalog,
    columns: tuple[int, ...],
    parent: TransformationRevision | None = None,
    *,
    cancelled: Event | None = None,
) -> EntityPopulation:
    selection = table.selection
    first = selection.header_row + 1 if selection.header_row is not None else selection.area.min_row
    if selection.area.max_row - first + 1 > MAX_ROWS:
        raise ValueError("Entity matching is limited to 500 selected data rows.")
    snapshot = read_transformation_snapshot(source, table, scope, catalog, cancelled=cancelled)
    return prepare_population(snapshot, columns, parent)


def runtime_python(root: Path | None = None) -> Path:
    if sys.platform != "win32":
        raise ValueError("Entity matching currently requires the verified Windows runtime.")
    runtime = (root or Path.cwd()) / ".tools/entity-matching"
    python = runtime / "Scripts/python.exe"
    try:
        report = json.loads((runtime / "loan-tape-runtime.json").read_text(encoding="utf-8"))
        if report["status"] != "passed" or not report["primary_environment_unchanged"]:
            raise ValueError("Runtime validation did not pass.")
        if not python.is_file():
            raise ValueError("Runtime interpreter is missing.")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(
            "Set up the optional runtime: dev.bat python scripts/setup_entity_matching.py --portable-compiler"
        ) from error
    return python.resolve()


def population_guard(
    source: Path,
    table: SavedTable,
    store: PackStore,
    population: EntityPopulation,
    columns: tuple[int, ...],
    parent: TransformationRevision | None,
    cancelled: Event | None = None,
) -> Callable[[], None]:
    def guard() -> None:
        check_cancelled(cancelled)
        saved = load_tables(table.selection.workbook_sha256)
        if next((t for t in saved.tables if t.id == table.id), None) != table:
            raise ValueError("The saved data set changed. Prepare and review again.")
        fresh = read_population(
            source,
            table,
            entity_scope(table),
            store.catalog(),
            columns,
            parent,
            cancelled=cancelled,
        )
        if fresh.id != population.id:
            raise ValueError(
                "Source, selected fields or dictionary changed. Prepare and review again."
            )

    return guard


def execute_worker(
    folder: Path,
    python: Path,
    cancelled: Event | None,
    timeout: float,
) -> None:
    """Run only this worker and its descendants in a kill-on-close Windows job."""
    jobs = importlib.import_module("win32job")
    events = importlib.import_module("win32event")
    processes = importlib.import_module("win32process")
    job = jobs.CreateJobObject(None, "LoanTapeEntity-" + uuid4().hex)
    process = None
    try:
        limits = jobs.QueryInformationJobObject(job, jobs.JobObjectExtendedLimitInformation)
        limits["BasicLimitInformation"]["LimitFlags"] |= jobs.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        jobs.SetInformationJobObject(job, jobs.JobObjectExtendedLimitInformation, limits)
        check_cancelled(cancelled)
        process, _ = start_in_job(
            str(python), ["-I", str(Path(__file__).with_name("entity_worker.py")), str(folder)], job
        )
        started = time.monotonic()
        while events.WaitForSingleObject(process, 100) != 0:
            check_cancelled(cancelled)
            if time.monotonic() - started > timeout:
                raise ValueError("Entity matching timed out; no result was published.")
        check_cancelled(cancelled)
        if processes.GetExitCodeProcess(process):
            raise ValueError("The matching worker failed; no result was published.")
    finally:
        try:
            jobs.TerminateJobObject(job, 0)
            if process is not None and events.WaitForSingleObject(process, 5000) != 0:
                raise RuntimeError("The owned matching worker did not shut down.")
            # A Windows venv launcher can exit before its interpreter child releases
            # request/model files. Wait for this job's complete process population.
            deadline = time.monotonic() + 5
            while jobs.QueryInformationJobObject(job, jobs.JobObjectBasicAccountingInformation)[
                "ActiveProcesses"
            ]:
                if time.monotonic() > deadline:
                    raise RuntimeError("Owned matching worker descendants are still shutting down.")
                time.sleep(0.01)
        finally:
            if process is not None:
                process.Close()
            job.Close()


def validate_engine(result: dict[str, Any], rows: set[int]) -> None:
    if result.get("name") != "dedupe" or result.get("version") != "3.0.3":
        raise ValueError("Unexpected entity engine result.")
    used: set[int] = set()
    for group in result["groups"]:
        members = group["rows"]
        if (
            len(members) < 2
            or len(members) != len(set(members))
            or used.intersection(members)
            or not set(members) <= rows
            or len(group["scores"]) != len(members)
        ):
            raise ValueError("Invalid or overlapping candidate groups.")
        used.update(members)
        for value in group["scores"]:
            if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("Invalid candidate score.")
        ordered = sorted(zip(members, group["scores"], strict=True))
        group["rows"] = [row for row, _ in ordered]
        group["scores"] = [score for _, score in ordered]
        group["id"] = fingerprint({"model": result["model_sha256"], "rows": group["rows"]})
    result["groups"].sort(key=lambda group: group["rows"])
    seen = set()
    for pair in result["pairs"]:
        key = tuple(pair["rows"])
        if len(key) != 2 or key[0] >= key[1] or not set(key) <= rows or key in seen:
            raise ValueError("Invalid or repeated candidate pair.")
        seen.add(key)
        if pair["score"] is None and pair.get("scoring_status") == "not_returned_by_dedupe":
            continue
        if (
            type(pair["score"]) not in {int, float}
            or not math.isfinite(pair["score"])
            or not 0 <= pair["score"] <= 1
        ):
            raise ValueError("Invalid candidate pair score.")
    result["unclustered_rows"] = sorted(rows - used)


@contextmanager
def worker_directory(workspace: Path) -> Iterator[Path]:
    """Remove only the created workspace; allow bounded Windows file-handle release."""
    work = Path(tempfile.mkdtemp(prefix="worker-", dir=workspace))
    try:
        yield work
    finally:
        if work.resolve().parent != workspace.resolve() or work.is_symlink() or work.is_junction():
            raise RuntimeError("Matching worker cleanup path changed; temporary files retained.")
        deadline = time.monotonic() + 5
        while True:
            try:
                shutil.rmtree(work)
                break
            except PermissionError as error:
                if getattr(error, "winerror", None) not in {32, 33} or time.monotonic() >= deadline:
                    raise RuntimeError(
                        f"Matching temporary files could not be removed: {work}"
                    ) from error
                # Job termination is already verified. Other file handles can briefly
                # retain a sharing lock; never change permissions or ignore leftovers.
                time.sleep(0.05)


def publish_bytes(target: Path, content: bytes, guard: Callable[[], None]) -> Path:
    """Publish a new file; preserve a competing file even if it appears during validation."""
    if target.exists() or target.is_symlink():
        raise ValueError("Choose a new output path; existing files cannot be overwritten.")
    if len(content) > MAX_BYTES:
        raise ValueError("Entity artifact exceeds 64 MiB.")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name + "." + uuid4().hex + ".tmp")
    owns_staging = False
    linked = False
    try:
        with staging.open("xb") as stream:
            owns_staging = True
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        guard()
        os.link(staging, target)
        linked = True
        if target.read_bytes() != content:
            raise ValueError("Published entity artifact did not match its evidence.")
        guard()
        return target
    except BaseException:
        if linked and target.exists() and target.samefile(staging):
            target.unlink()
        raise
    finally:
        if owns_staging:
            staging.unlink(missing_ok=True)


def train_entities(
    population: EntityPopulation,
    labels: tuple[PairLabel, ...],
    threshold: float,
    representative_labels: bool,
    guard: Callable[[], None],
    *,
    cancelled: Event | None = None,
    runtime_root: Path | None = None,
    timeout: float = 300,
) -> tuple[EntityRun, Path]:
    validate_labels(population, labels)
    validate_threshold(threshold)
    if representative_labels is not True:
        raise ValueError("Confirm that labels represent the selected borrower population.")
    check_cancelled(cancelled)
    guard()
    python = runtime_python(runtime_root)
    runtime_report = json.loads(
        (python.parent.parent / "loan-tape-runtime.json").read_text(encoding="utf-8")
    )
    data = population.to_dict()
    records = {row["row"]: row["values"] for row in data["rows"] if not row["exclusions"]}
    workspace = (Path.cwd() / ".artifacts/entity-matching").resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    source_hash = data["snapshot"]["dataset"]["selection"]["workbook_sha256"]
    stem = source_hash + "-" + uuid4().hex

    def current() -> None:
        check_cancelled(cancelled)
        guard()

    with worker_directory(workspace) as work:
        request = {
            "records": records,
            "features": data["features"],
            "labels": labels_payload(labels),
            "threshold": threshold,
            "runtime_packages": runtime_report["packages"],
        }
        (work / "request.json").write_text(bounded(request), encoding="utf-8")
        execute_worker(work, python, cancelled, timeout)
        output = work / "result.json"
        if output.stat().st_size > MAX_BYTES:
            raise ValueError("Matching output exceeds the result limit.")
        result = json.loads(output.read_text(encoding="utf-8"))
        if "error" in result:
            raise ValueError("Dedupe failed: " + result["error"])
        validate_engine(result, set(records))
        result["runtime_setup"] = runtime_report
        model = work / "model.bin"
        if model.stat().st_size > MAX_BYTES:
            raise ValueError("Matching model exceeds the model limit.")
        model_bytes = model.read_bytes()
        if hashlib.sha256(model_bytes).hexdigest() != result["model_sha256"]:
            raise ValueError("Matching model hash mismatch.")
        result["model_file"] = stem + ".bin"
        run = EntityRun(
            bounded(
                {
                    "format_version": 1,
                    "population_id": population.id,
                    "population": data,
                    "labels": labels_payload(labels),
                    "representative_labels_confirmed": True,
                    "created_at_utc": datetime.now(UTC).isoformat(),
                    "engine": result,
                }
            )
        )
        current()
        model_target = publish_bytes(workspace / (stem + ".bin"), model_bytes, current)
        try:
            path = publish_bytes(
                workspace / (stem + ".json"), run.document_json.encode("utf-8"), current
            )
        except BaseException:
            model_target.unlink(missing_ok=True)
            raise
        return run, path
