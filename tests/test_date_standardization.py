"""Date import/interpretation is a distinct handoff before red-flag review."""

from datetime import date
from pathlib import Path

import pytest

from loan_tape.date_analysis import DateBinding, analyze_standardized_dates
from loan_tape.date_parser import DateEvidence, DateProfile, DateSource
from loan_tape.date_reader import DateColumnEvidence
from loan_tape.date_standardization import DateMapping, standardize_dates
from loan_tape.pack_format import load_pack
from loan_tape.packs import Catalog
from loan_tape.ranges import parse_range
from loan_tape.selection import SavedTable, SourceSelection

ROOT = Path(__file__).resolve().parents[1]


def _prepared():
    selection = SourceSelection("a" * 64, "Dates", parse_range("A1:A4"), 1)
    table = SavedTable("b" * 32, "Separated date phases", selection)
    column = DateColumnEvidence(
        selection,
        1,
        "1900",
        tuple(
            DateEvidence(DateSource("a" * 64, row, 1, "Dates"), kind, raw)
            for row, kind, raw in (
                (2, "text", "2026-09-17"),
                (3, "text", "not-a-date"),
                (4, "blank", None),
            )
        ),
    )
    profile = DateProfile(text_formats=("YYYY-MM-DD",))
    mapping = DateMapping(1, "loan.dates:closing_date", profile)
    catalog = Catalog("default", (load_pack(ROOT / "packs/loan-dates"),))
    return standardize_dates(table, (column,), (mapping,), catalog), profile


def test_standardization_has_parser_outcomes_but_no_red_flag_result():
    prepared, _ = _prepared()
    assert prepared.row_count == 3
    assert prepared.cell_count == 3
    assert dict(prepared.columns[0].status_counts) == {
        "valid": 1,
        "ambiguous": 0,
        "invalid": 1,
        "missing": 1,
        "unsupported": 0,
        "source_error": 0,
    }
    assert not hasattr(prepared, "findings")


def test_red_flags_consume_the_completed_standardization():
    prepared, profile = _prepared()
    review = analyze_standardized_dates(
        prepared,
        (DateBinding(1, "loan.dates:closing_date", profile, require_value=True),),
        reference_date=date(2026, 9, 17),
    )
    findings = review.to_dict()["results"]["findings"]
    assert any(item["rule_id"] == "date.invalid" for item in findings)
    assert any(item["rule_id"] == "date.missing" for item in findings)


def test_red_flags_reject_changed_mapping_after_standardization():
    prepared, profile = _prepared()
    with pytest.raises(ValueError, match="do not match"):
        analyze_standardized_dates(
            prepared,
            (DateBinding(2, "loan.dates:closing_date", profile),),
            reference_date=date(2026, 9, 17),
        )
