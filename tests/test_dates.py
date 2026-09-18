"""Explicit interpretation and policy boundaries, using synthetic source evidence."""

import json
from dataclasses import FrozenInstanceError, replace
from datetime import date

import pytest

from loan_tape.date_parser import DateEvidence, DateProfile, DateSource, parse_date
from loan_tape.pack_format import load_pack
from loan_tape.packs import PackStore

SOURCE = DateSource("a" * 64, 7, 3, "Dates")


def interpret(raw, profile=None, kind="text", **evidence):
    return parse_date(DateEvidence(SOURCE, kind, raw, **evidence), profile or DateProfile())


def test_us_short_dates_require_an_explicit_century_and_preserve_raw():
    profile = DateProfile(text_formats=("M/D/YY",))
    pending = interpret("1/8/21", profile)
    assert pending.status == "ambiguous"
    assert pending.code == "two_digit_year_window_required"
    assert pending.parsed_date is None
    profile = replace(profile, two_digit_year_start=2000)
    result = interpret("1/8/21", profile)
    assert result.parsed_date == date(2021, 1, 8)
    assert result.evidence.raw == "1/8/21"
    assert result.evidence.source == SOURCE
    assert result.profile is profile
    with pytest.raises(FrozenInstanceError):
        result.status = "invalid"


@pytest.mark.parametrize(
    "text,expected", [("1/1/69", 2069), ("1/1/70", 1970), ("1/1/00", 2000), ("1/1/99", 1999)]
)
def test_explicit_window_boundary_has_no_system_pivot(text, expected):
    result = interpret(text, DateProfile(text_formats=("M/D/YY",), two_digit_year_start=1970))
    assert result.parsed_date.year == expected


def test_multiple_interpretations_never_choose_likely_day_order():
    profile = DateProfile(text_formats=("M/D/YYYY", "D/M/YYYY"))
    result = interpret("1/8/2021", profile)
    assert result.status == "ambiguous" and result.parsed_date is None
    assert result.candidates == (date(2021, 1, 8), date(2021, 8, 1))
    assert interpret("1/1/2021", profile).status == "valid"
    assert interpret("13/1/2021", profile).parsed_date == date(2021, 1, 13)
    assert interpret("13/1/2021", DateProfile(text_formats=("M/D/YYYY",))).status == "invalid"


@pytest.mark.parametrize(
    "text,valid",
    [
        ("2000-02-29", True),
        ("2100-02-29", False),
        ("2400-02-29", True),
        ("2023-02-29", False),
        ("2024-04-31", False),
        ("0001-01-01", True),
        ("9999-12-31", True),
        ("0000-01-01", False),
    ],
)
def test_calendar_validity_including_century_boundaries(text, valid):
    result = interpret(text)
    assert result.status == ("valid" if valid else "invalid")
    if not valid:
        assert result.parsed_date is None and result.code == "invalid_calendar_date"


@pytest.mark.parametrize(
    "text",
    [
        "01-08-2021",
        "20210108",
        "2021-W01-5",
        "Jan 8, 2021",
        "2021-1-8",
        "２021-01-08",
        "44104",
        "=DATE(2021,1,8)",
    ],
)
def test_unconfigured_formats_are_not_guessed(text):
    assert interpret(text).code == "format_mismatch"


def test_invalid_short_date_does_not_become_century_ambiguity():
    profile = DateProfile(text_formats=("M/D/YY",))
    assert interpret("13/40/21", profile).status == "invalid"
    assert interpret("2/29/01", profile).status == "invalid"
    assert interpret("2/29/00", profile).status == "ambiguous"


def test_missing_categories_zero_and_source_errors_are_distinct():
    profile = DateProfile(missing_tokens=("NA",))
    rows = [
        interpret(None, profile, "blank", present=False),
        interpret(None, profile, "blank"),
        interpret("", profile),
        interpret(" \t", profile),
        interpret("NA", profile),
    ]
    assert [r.missing_kind for r in rows] == [
        "absent",
        "blank",
        "empty_text",
        "whitespace",
        "token",
    ]
    assert all(r.status == "missing" for r in rows)
    assert interpret("na", profile).status == "invalid"
    assert interpret("0", profile).status == "invalid"
    assert interpret("0", profile, "number").status == "unsupported"
    assert interpret("1", profile, "boolean").status == "unsupported"
    assert interpret("#VALUE!", profile, "error").status == "source_error"


def test_whitespace_requires_policy_and_records_transform():
    assert interpret(" 2024-02-29 ").code == "surrounding_whitespace"
    result = interpret(" 2024-02-29 ", DateProfile(whitespace="strip"))
    assert result.parsed_date == date(2024, 2, 29)
    assert result.evidence.raw == " 2024-02-29 " and result.notes
    assert (
        interpret(" NA ", DateProfile(whitespace="strip", missing_tokens=("NA",))).missing_kind
        == "token"
    )


def test_iso_timestamps_need_explicit_date_component_policy_and_keep_local_day():
    raw = "2026-01-01T00:30:00+14:00"
    profile = DateProfile(text_formats=("ISO_DATETIME",))
    assert interpret(raw, profile).code == "timestamp_requires_policy"
    result = interpret(raw, replace(profile, timestamps="date_component"))
    assert result.parsed_date == date(2026, 1, 1)
    assert result.evidence.raw == raw and "without timezone conversion" in result.notes[0]
    assert interpret("2026-01-01T00:00:00", kind="iso_date").code == "timestamp_requires_policy"
    assert interpret("2026-01-01", DateProfile(text_formats=()), "iso_date").status == "valid"


@pytest.mark.parametrize(
    "text",
    [
        "2021-02-29T01:01:01",
        "2021-01-01T24:00:00",
        "2021-01-01T00:00:00+01:99",
        "2021-01-01T00:00:00+25:00",
        "2021-01-01T00:00:60Z",
        "2021-01-01T00:00:00.0000001Z",
    ],
)
def test_invalid_and_unsupported_timestamps_never_lose_information(text):
    result = interpret(
        text, DateProfile(text_formats=("ISO_DATETIME",), timestamps="date_component")
    )
    assert result.status == "invalid" and result.parsed_date is None


@pytest.mark.parametrize(
    "system,serial,expected",
    [
        ("1900", "1", date(1900, 1, 1)),
        ("1900", "59", date(1900, 2, 28)),
        ("1900", "61", date(1900, 3, 1)),
        ("1900", "1462", date(1904, 1, 1)),
        ("1904", "0", date(1904, 1, 1)),
        ("1904", "1", date(1904, 1, 2)),
        ("1900", "2958465", date(9999, 12, 31)),
        ("1904", "2957003", date(9999, 12, 31)),
    ],
)
def test_excel_serial_systems_and_range(system, serial, expected):
    result = interpret(
        serial, DateProfile(numeric_dates="excel_serial"), "number", date_system=system
    )
    assert result.parsed_date == expected and result.evidence.raw == serial


@pytest.mark.parametrize(
    "system,serial,code",
    [
        ("1900", "60", "excel_fictitious_1900_02_29"),
        ("1900", "60.5", "excel_fictitious_1900_02_29"),
        ("1900", "0", "excel_time_without_calendar_date"),
        ("1900", "0.5", "excel_time_without_calendar_date"),
        ("1900", "-1", "excel_serial_out_of_range"),
        ("1904", "2957004", "excel_serial_out_of_range"),
        ("1900", "2958466", "excel_serial_out_of_range"),
        ("1900", "NaN", "invalid_excel_serial"),
        ("1900", "Infinity", "invalid_excel_serial"),
        (None, "44104", "excel_date_system_required"),
    ],
)
def test_unsupported_and_invalid_serials_are_not_corrected(system, serial, code):
    result = interpret(
        serial,
        DateProfile(numeric_dates="excel_serial", timestamps="date_component"),
        "number",
        date_system=system,
    )
    assert result.code == code and result.parsed_date is None


def test_serial_fraction_does_not_round_into_next_day():
    raw = "61.999999999999999999999999999999"
    profile = DateProfile(numeric_dates="excel_serial")
    assert interpret(raw, profile, "number", date_system="1900").code == "timestamp_requires_policy"
    result = interpret(
        raw, replace(profile, timestamps="date_component"), "number", date_system="1900"
    )
    assert result.parsed_date == date(1900, 3, 1) and result.evidence.raw == raw
    assert result.notes
    assert interpret("61", profile).status == "invalid"  # numeric text is not a serial


def test_formula_cache_never_becomes_valid_date():
    evidence = DateEvidence(
        SOURCE, "formula", "45000", raw_token="45000", formula="TODAY()", date_system="1900"
    )
    result = parse_date(evidence, DateProfile(numeric_dates="excel_serial"))
    assert result.code == "formula_not_evaluated" and result.parsed_date is None
    assert result.evidence.formula == "TODAY()" and result.evidence.raw_token == "45000"


def test_profile_roundtrip_and_fingerprint_are_content_bound():
    profile = DateProfile(
        id="source-us",
        text_formats=("M/D/YY",),
        two_digit_year_start=2000,
        missing_tokens=("ND",),
        whitespace="strip",
    )
    reopened = DateProfile.from_json(profile.to_json())
    assert reopened == profile and reopened.fingerprint == profile.fingerprint
    assert replace(profile, two_digit_year_start=1900).fingerprint != profile.fingerprint


@pytest.mark.parametrize(
    "key,value",
    [
        ("format_version", True),
        ("format_version", 2),
        ("two_digit_year_start", True),
        ("two_digit_year_start", 9901),
        ("text_formats", ["auto"]),
        ("text_formats", "YYYY-MM-DD"),
        ("text_formats", ["YYYY-MM-DD", "YYYY-MM-DD"]),
        ("missing_tokens", [" NA "]),
        ("numeric_dates", "infer"),
        ("timestamps", "utc"),
        ("version", "latest"),
        ("extra", "unexpected"),
    ],
)
def test_invalid_profile_contract_fails_clearly(key, value):
    document = json.loads(DateProfile().to_json())
    document[key] = value
    with pytest.raises(ValueError):
        DateProfile.from_json(json.dumps(document))


def test_duplicate_json_keys_and_nonfinite_json_rejected():
    text = DateProfile().to_json()
    with pytest.raises(ValueError, match="duplicate"):
        DateProfile.from_json(
            text.replace('"format_version": 1', '"format_version": 1, "format_version": 1')
        )
    with pytest.raises(ValueError):
        DateProfile.from_json(
            text.replace('"two_digit_year_start": null', '"two_digit_year_start": NaN')
        )


def test_date_dictionary_has_distinct_meanings_and_stays_inactive(tmp_path):
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    pack = load_pack(root / "packs" / "loan-dates")
    assert {f.id for f in pack.fields} == {
        "closing_date",
        "original_maturity_date",
        "current_maturity_date",
        "reporting_date",
    }
    assert all(
        f.data_type == "date" and f.required is None and f.blank_allowed is None
        for f in pack.fields
    )
    store = PackStore(root / "packs", tmp_path / "state")
    assert store.catalog().fields == ()
    store.activate("loan.dates")
    assert store.catalog().get_field("loan.dates:reporting_date").field.entity == "report"
    assert (
        store.catalog().get_field("loan.dates:current_maturity_date").field.context[1]
        == "reporting_date"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"raw": 45000},
        {"kind": "blank", "raw": "value"},
        {"present": False},
        {"present": 1},
        {"date_system": []},
        {"formula": "TODAY()"},
        {"formula_attributes": [("t", "shared")]},
    ],
)
def test_evidence_rejects_inconsistent_or_mutable_representations(changes):
    with pytest.raises(ValueError):
        DateEvidence(**{"source": SOURCE, "kind": "text", "raw": "2021-01-08", **changes})
