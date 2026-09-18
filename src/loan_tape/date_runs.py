"""Atomic, self-contained date runs with integrity checks and deterministic replay."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from uuid import uuid4

from loan_tape._date_json import canonical, fingerprint
from loan_tape.date_analysis import DateAnalysis, replay_analysis
from loan_tape.pack_format import object_keys, parse_json, read_text
from loan_tape.workbook_index import _digest, check_cancelled

MAX_RUN_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True)
class SavedDateRun:
    id: str
    created_at: datetime
    analysis: DateAnalysis
    path: Path


def verify_analysis(analysis: DateAnalysis, *, cancelled: Event | None = None) -> None:
    """Check reconciliation and results by replay, not just a self-reported checksum."""
    reproduced = replay_analysis(analysis.to_dict(), cancelled=cancelled)
    if reproduced.document_json != canonical(analysis.to_dict()):
        raise ValueError("Saved results or inputs do not match deterministic replay.")


def save_date_run(
    analysis: DateAnalysis, directory: Path, *, cancelled: Event | None = None
) -> SavedDateRun:
    """Publish a new run without replacing an existing file; never save partial results."""
    check_cancelled(cancelled)
    if not isinstance(analysis, DateAnalysis):
        raise ValueError("Only a completed date analysis can be saved.")
    if len(analysis.document_json.encode("utf-8")) > MAX_RUN_BYTES:
        raise ValueError("Date run exceeds the supported size limit.")
    verify_analysis(analysis, cancelled=cancelled)
    run_id, created = uuid4().hex, datetime.now(UTC)
    body = {
        "format_version": 1,
        "run_id": run_id,
        "created_at": created.isoformat(),
        "analysis": analysis.to_dict(),
    }
    encoded = canonical({"sha256": fingerprint(body), "run": body}).encode("utf-8")
    if len(encoded) > MAX_RUN_BYTES:
        raise ValueError("Date run exceeds the supported size limit.")
    check_cancelled(cancelled)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (run_id + ".json")
    temporary = directory / ("." + run_id + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        check_cancelled(cancelled)
        # Atomic publication with no replacement on both Windows and POSIX.
        # An unsupported filesystem fails visibly; there is no non-atomic fallback.
        os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return SavedDateRun(run_id, created, analysis, target)


def load_date_run(path: Path, *, cancelled: Event | None = None) -> SavedDateRun:
    """Load and replay using embedded evidence, definitions, policies and calendars only."""
    check_cancelled(cancelled)
    envelope = object_keys(
        parse_json(read_text(path, limit=MAX_RUN_BYTES), "date run"),
        {"sha256", "run"},
        set(),
        "date run",
    )
    body = object_keys(
        envelope["run"],
        {"format_version", "run_id", "created_at", "analysis"},
        set(),
        "date run body",
    )
    if type(body["format_version"]) is not int or body["format_version"] != 1:
        raise ValueError("Unsupported saved date-run format.")
    if not isinstance(envelope["sha256"], str) or envelope["sha256"] != fingerprint(body):
        raise ValueError("Date-run integrity check failed.")
    if not isinstance(body["run_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", body["run_id"]):
        raise ValueError("Invalid saved date-run identity.")
    if not isinstance(body["created_at"], str):
        raise ValueError("Date-run creation time must be an aware ISO timestamp.")
    created = datetime.fromisoformat(body["created_at"])
    if created.tzinfo is None or created.utcoffset() is None:
        raise ValueError("Date-run creation time must include its timezone.")
    analysis = DateAnalysis(canonical(body["analysis"]))
    verify_analysis(analysis, cancelled=cancelled)
    check_cancelled(cancelled)
    return SavedDateRun(body["run_id"], created, analysis, path)


def check_run_source(run: SavedDateRun, source: Path) -> str:
    """Source availability is distinct from reproducibility of retained evidence."""
    expected = run.analysis.to_dict()["inputs"]["dataset"]["source_sha256"]
    if not source.exists():
        return "missing"
    return "unchanged" if _digest(source, None) == expected else "changed"
