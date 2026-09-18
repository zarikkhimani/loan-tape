"""Saved date runs retain all evidence and fail closed on corruption or partial writes."""

import json
from datetime import date
from pathlib import Path
from threading import Event
from uuid import UUID

import pytest

from loan_tape._date_json import canonical, fingerprint
from loan_tape.date_analysis import CalendarBinding, DateAnalysis, DateBinding, analyze_dates
from loan_tape.date_calendar import build_calendar
from loan_tape.date_parser import DateEvidence, DateProfile, DateSource
from loan_tape.date_reader import DateColumnEvidence
from loan_tape.date_runs import check_run_source, load_date_run, save_date_run
from loan_tape.pack_format import load_pack
from loan_tape.packs import Catalog
from loan_tape.ranges import parse_range
from loan_tape.selection import SavedTable, SourceSelection
from loan_tape.workbook_index import ScanCancelled


@pytest.fixture
def analysis():
    pack = load_pack(Path(__file__).resolve().parents[1] / "packs/loan-dates")
    selection = SourceSelection("a" * 64, "Dates", parse_range("A1:A3"), 1)
    table = SavedTable("b" * 32, "Synthetic retained run", selection)
    cells = tuple(
        DateEvidence(DateSource("a" * 64, r, 1, "Dates"), "text", v)
        for r, v in ((2, "7/3/26"), (3, "1/2/27"))
    )
    column = DateColumnEvidence(selection, 1, "1900", cells)
    calendar = build_calendar("us.sifma_fixed_income")
    mapping = DateBinding(
        1,
        "loan.dates:closing_date",
        DateProfile(text_formats=("M/D/YY",), two_digit_year_start=2000),
        calendar=CalendarBinding(calendar.id),
    )
    return analyze_dates(
        table,
        (column,),
        (mapping,),
        Catalog("dates", (pack,)),
        reference_date=date(2026, 9, 17),
        calendars=(calendar,),
    )


def test_saved_run_reopens_without_original_pack_calendar_or_workbook(
    analysis, tmp_path, monkeypatch
):
    saved = save_date_run(analysis, tmp_path)
    before = saved.path.read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError("Replay attempted to consult current external state")

    monkeypatch.setattr("loan_tape.date_calendar.build_calendar", forbidden)
    monkeypatch.setattr("loan_tape.pack_format.load_pack", forbidden)
    reopened = load_date_run(saved.path)
    assert reopened.analysis.document_json == analysis.document_json
    assert reopened.analysis.fingerprint == analysis.fingerprint
    assert reopened.created_at.tzinfo is not None
    assert before == saved.path.read_bytes()
    assert check_run_source(reopened, tmp_path / "absent.xlsx") == "missing"
    changed = tmp_path / "changed.xlsx"
    changed.write_bytes(b"not the source")
    assert check_run_source(reopened, changed) == "changed"
    inputs = reopened.analysis.to_dict()["inputs"]
    assert inputs["evidence"][0]["cells"][0]["raw"] == "7/3/26"
    assert inputs["bindings"][0]["profile"]["two_digit_year_start"] == 2000
    assert inputs["dictionaries"][0]["files"]["fields.json"]
    assert inputs["calendars"][0]["snapshot"]["sources"]


@pytest.mark.parametrize(
    "mutation", ["result", "raw", "profile", "pack", "calendar", "engine", "lineage"]
)
def test_recomputed_outer_hash_cannot_hide_inconsistent_results_or_snapshots(
    analysis, tmp_path, mutation
):
    saved = save_date_run(analysis, tmp_path)
    envelope = json.loads(saved.path.read_text(encoding="utf-8"))
    document = envelope["run"]["analysis"]
    inputs = document["inputs"]
    if mutation == "result":
        document["results"]["row_count"] += 1
    elif mutation == "raw":
        inputs["evidence"][0]["cells"][0]["raw"] = "7/4/26"
    elif mutation == "profile":
        inputs["bindings"][0]["profile"]["two_digit_year_start"] = 1900
    elif mutation == "pack":
        inputs["dictionaries"][0]["files"]["fields.json"] += " "
    elif mutation == "calendar":
        inputs["calendars"][0]["snapshot"]["events"].pop()
    elif mutation == "engine":
        document["engine_version"] = "2.0.0"
    else:
        inputs["evidence"][0]["cells"][0]["source"]["row"] += 1
    envelope["sha256"] = fingerprint(envelope["run"])
    saved.path.write_text(canonical(envelope), encoding="utf-8")
    with pytest.raises(ValueError):
        load_date_run(saved.path)


def test_integrity_unknown_keys_versions_and_oversized_runs(analysis, tmp_path, monkeypatch):
    saved = save_date_run(analysis, tmp_path)
    envelope = json.loads(saved.path.read_text(encoding="utf-8"))
    original = canonical(envelope)
    envelope["run"]["created_at"] = "2026-01-01T00:00:00+00:00"
    saved.path.write_text(canonical(envelope), encoding="utf-8")
    with pytest.raises(ValueError, match="integrity"):
        load_date_run(saved.path)
    saved.path.write_text(original[:-1] + ',"sha256":"duplicate"}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_date_run(saved.path)
    saved.path.write_text(original, encoding="utf-8")
    monkeypatch.setattr("loan_tape.date_runs.MAX_RUN_BYTES", 100)
    with pytest.raises(ValueError, match="exceeds"):
        load_date_run(saved.path)
    with pytest.raises(ValueError, match="size limit"):
        save_date_run(analysis, tmp_path)


def test_atomic_publication_failure_and_cancellation_leave_no_completed_run(
    analysis, tmp_path, monkeypatch
):
    def failed_link(*args):
        raise OSError("Synthetic publish failure")

    monkeypatch.setattr("loan_tape.date_runs.os.link", failed_link)
    with pytest.raises(OSError, match="Synthetic publish failure"):
        save_date_run(analysis, tmp_path)
    assert list(tmp_path.iterdir()) == []
    cancelled = Event()
    monkeypatch.setattr("loan_tape.date_runs.os.fsync", lambda fd: cancelled.set())
    with pytest.raises(ScanCancelled):
        save_date_run(analysis, tmp_path, cancelled=cancelled)
    assert list(tmp_path.iterdir()) == []


def test_existing_runs_cannot_be_overwritten(analysis, tmp_path, monkeypatch):
    monkeypatch.setattr("loan_tape.date_runs.uuid4", lambda: UUID("c" * 32))
    saved = save_date_run(analysis, tmp_path)
    original = saved.path.read_bytes()
    with pytest.raises(FileExistsError):
        save_date_run(analysis, tmp_path)
    assert saved.path.read_bytes() == original
    assert len(list(tmp_path.iterdir())) == 1


def test_fabricated_completed_results_cannot_be_saved(analysis, tmp_path):
    document = analysis.to_dict()
    document["results"]["findings"] = []
    with pytest.raises(ValueError, match="replay"):
        save_date_run(DateAnalysis(canonical(document)), tmp_path)
    assert not list(tmp_path.iterdir())
