"""Synthetic date analysis: full population, conservative findings and saved provenance."""

import hashlib
from dataclasses import replace
from datetime import date
from pathlib import Path
from threading import Event

import pytest
from openpyxl import Workbook

from loan_tape.date_analysis import (
    CalendarBinding,
    DateBinding,
    DatePair,
    analyze_dates,
    analyze_standardized_dates,
    replay_analysis,
)
from loan_tape.date_calendar import build_calendar
from loan_tape.date_parser import DateEvidence, DateProfile, DateSource
from loan_tape.date_reader import DateColumnEvidence
from loan_tape.date_standardization import DateMapping, standardize_excel_dates
from loan_tape.pack_format import load_pack
from loan_tape.packs import Catalog
from loan_tape.ranges import parse_range
from loan_tape.selection import SavedTable, SourceSelection
from loan_tape.workbook_index import ScanCancelled

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = date(2026, 9, 17)


@pytest.fixture
def catalog():
    return Catalog("dates", (load_pack(ROOT / "packs/loan-dates"),))


def fixture_columns(values):
    selection = SourceSelection("a" * 64, "Dates", parse_range(f"C9:D{9 + len(values)}"), 9)
    table = SavedTable("b" * 32, "Synthetic dates", selection)
    columns = []
    for index, col in enumerate((3, 4)):
        cells = []
        for row, pair in enumerate(values, start=10):
            value = pair[index]
            kind, raw = value if isinstance(value, tuple) else ("text", value)
            cells.append(DateEvidence(DateSource("a" * 64, row, col, "Dates"), kind, raw))
        columns.append(DateColumnEvidence(selection, col, "1900", tuple(cells)))
    return table, tuple(columns)


def bindings(profile=None):
    profile = profile or DateProfile()
    return (
        DateBinding(3, "loan.dates:closing_date", profile),
        DateBinding(4, "loan.dates:current_maturity_date", profile),
    )


def run(catalog, values, **kwargs):
    table, columns = fixture_columns(values)
    return analyze_dates(
        table,
        columns,
        kwargs.pop("bindings", bindings()),
        catalog,
        reference_date=REFERENCE,
        pairs=kwargs.pop("pairs", (DatePair(3, 4),)),
        **kwargs,
    )


def test_population_statuses_raw_evidence_ordering_and_missingness(catalog):
    report = run(
        catalog,
        [
            ("2026-01-03", "2026-01-02"),
            ("2026-01-05", "2026-01-05"),
            ("2026-02-30", "2026-02-28"),
            ("03/04/2026", "2026-03-05"),
            (("blank", None), "2026-04-01"),
            (("error", "#N/A"), "2026-05-01"),
            (("formula", "=TODAY()"), "2026-06-01"),
            ("NA", "2026-07-01"),
        ],
        bindings=bindings(
            DateProfile(text_formats=("YYYY-MM-DD", "M/D/YYYY", "D/M/YYYY"), missing_tokens=("NA",))
        ),
    )
    document = report.to_dict()
    results = document["results"]
    assert results["row_count"] == 8 and results["cell_count"] == 16
    column = results["columns"][0]
    assert column["status_counts"] == dict(
        valid=2, invalid=1, ambiguous=1, missing=2, source_error=1, unsupported=1
    )
    assert column["missing_counts"] == {"blank": 1, "token": 1}
    pair = results["pairs"][0]
    assert pair["evaluated_count"] == 2 and pair["not_evaluable_count"] == 6
    assert pair["records"][0]["elapsed_calendar_days"] == -1
    assert pair["records"][1]["elapsed_calendar_days"] == 0
    ordering = [f for f in results["findings"] if f["rule_id"] == "date.pair_order"]
    assert ordering[0]["rows"] == [10] and len(ordering) == 1
    assert document["inputs"]["evidence"][0]["cells"][3]["raw"] == "03/04/2026"
    assert column["cells"][3]["candidates"] == ["2026-03-04", "2026-04-03"]
    assert replay_analysis(document).document_json == report.document_json


def test_duplicates_distributions_iqr_and_same_day_policy(catalog):
    values = [("2026-01-05", "2026-01-05")] * 5 + [("2099-12-31", "2100-01-01")]
    report = run(catalog, values, pairs=(DatePair(3, 4, allow_equal=False),)).to_dict()["results"]
    col = report["columns"][0]
    assert col["duplicate_dates"] == [
        {"date": "2026-01-05", "rows": list(range(10, 15)), "count": 5}
    ]
    assert col["weekday_counts"]["Monday"] == 5
    assert col["month_end_count"] == 1
    assert sum(col["year_counts"].values()) == col["valid_count"]
    assert report["pairs"][0]["duplicate_pairs"][0]["count"] == 5
    assert any(f["rule_id"] == "date.iqr_outlier" and f["rows"] == [15] for f in report["findings"])
    assert len([f for f in report["findings"] if f["rule_id"] == "date.pair_order"]) == 5
    assert all(
        f["severity"] == "info"
        for f in report["findings"]
        if f["rule_id"].startswith("date.repeated")
    )


def test_calendar_severity_requires_agreement_and_published_or_weekend_evidence(catalog):
    calendar = build_calendar("us.sifma_fixed_income")
    base = bindings()
    policy = CalendarBinding(calendar.id, "closing", True, "Synthetic agreement section 1.1")
    mapped = (replace(base[0], calendar=policy), base[1])
    report = run(
        catalog,
        [
            ("2026-07-03", "2028-01-01"),
            ("2027-06-18", "2028-01-01"),
            ("2126-06-19", "2028-01-01"),
            ("2020-06-20", "2028-01-01"),
        ],
        bindings=mapped,
        calendars=(calendar,),
    ).to_dict()["results"]
    nonbusiness = [f for f in report["findings"] if f["rule_id"] == "calendar.non_business_day"]
    assert [(f["rows"], f["severity"]) for f in nonbusiness] == [
        ([10], "error"),
        ([11], "error"),
        ([13], "error"),
    ]
    assert not any(f["rule_id"] == "calendar.source_conflict" for f in report["findings"])
    assert report["columns"][0]["cells"][2]["calendar"]["business_day"] is None
    review = run(
        catalog,
        [("2026-07-03", "2028-01-01")],
        bindings=(replace(base[0], calendar=CalendarBinding(calendar.id)), base[1]),
        calendars=(calendar,),
    )
    assert all(
        f["severity"] == "review"
        for f in review.to_dict()["results"]["findings"]
        if f["rule_id"] == "calendar.non_business_day"
    )


def test_reference_reporting_bounds_required_value_and_exact_fraction_statistics(catalog):
    base = bindings()
    mapped = (
        replace(
            base[0], require_value=True, earliest=date(2026, 1, 1), reference_check="flag_after"
        ),
        base[1],
    )
    report = run(
        catalog,
        [
            ("2025-12-31", "2026-01-01"),
            ("2027-01-01", "2027-01-03"),
            (("blank", None), "2028-01-01"),
        ],
        bindings=mapped,
        reporting_date=date(2020, 1, 1),
        pairs=(DatePair(3, 4, maximum_days=1),),
    ).to_dict()
    assert report["inputs"]["reporting_date"] == "2020-01-01"
    assert report["results"]["pairs"][0]["statistics"]["median"] == "3/2"
    flags = report["results"]["findings"]
    assert any(f["rule_id"] == "date.missing" and f["severity"] == "error" for f in flags)
    assert any(f["rule_id"] == "date.reference_comparison" and f["rows"] == [11] for f in flags)
    assert any(f["rule_id"] == "date.configured_bounds" and f["rows"] == [10] for f in flags)
    assert any(f["rule_id"] == "date.pair_bounds" and f["rows"] == [11] for f in flags)


@pytest.mark.parametrize(
    "change", ["missing_row", "row_order", "source", "selection", "date_system", "duplicate_column"]
)
def test_incomplete_or_misaligned_evidence_fails(catalog, change):
    table, cols = fixture_columns([("2026-01-01", "2027-01-01"), ("2026-01-02", "2027-01-02")])
    first = cols[0]
    if change == "missing_row":
        first = replace(first, cells=first.cells[:1])
    elif change == "row_order":
        first = replace(first, cells=tuple(reversed(first.cells)))
    elif change == "source":
        first = replace(
            first,
            cells=(
                replace(first.cells[0], source=DateSource("c" * 64, 10, 3, "Dates")),
                first.cells[1],
            ),
        )
    elif change == "selection":
        first = replace(first, selection=replace(first.selection, sheet="Other"))
    elif change == "date_system":
        first = replace(first, cells=(replace(first.cells[0], date_system="1904"), first.cells[1]))
    else:
        cols = (first, first)
    with pytest.raises(ValueError):
        analyze_dates(table, (first, cols[1]), bindings(), catalog, reference_date=REFERENCE)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: CalendarBinding("us.sifma_fixed_income", "closing", True),
        lambda: CalendarBinding("us.sifma_fixed_income", "reference_screening", True, "agreement"),
        lambda: DateBinding(True, "loan.dates:closing_date", DateProfile()),
        lambda: DatePair(3, 3),
        lambda: DatePair(3, 4, minimum_days=-1),
        lambda: DatePair(3, 4, minimum_days=9, maximum_days=8),
    ],
)
def test_invalid_rule_policies_fail(factory):
    with pytest.raises(ValueError):
        factory()


def test_complete_excel_source_execution_and_cancel(catalog, tmp_path, monkeypatch):
    import loan_tape.date_standardization as standardization

    path = tmp_path / "synthetic.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "Dates"
    sheet.append(["Closing", "Maturity"])
    sheet.append(["2026-01-03", "2026-01-02"])
    sheet.append([60, "2027-01-01"])
    sheet.row_dimensions[3].hidden = True
    book.save(path)
    book.close()
    before = path.read_bytes()
    selection = SourceSelection(
        hashlib.sha256(before).hexdigest(), "Dates", parse_range("A1:B4"), 1
    )
    table = SavedTable("a" * 32, "Synthetic workbook", selection)
    profile = DateProfile(numeric_dates="excel_serial")
    mapped = tuple(replace(b, column=i, profile=profile) for i, b in enumerate(bindings(), start=1))
    mappings = tuple(DateMapping(item.column, item.field_id, item.profile) for item in mapped)
    scans = []
    bulk_read = standardization.read_excel_date_columns

    def record_bulk_read(*args, **kwargs):
        scans.append(args[2])
        return bulk_read(*args, **kwargs)

    monkeypatch.setattr(standardization, "read_excel_date_columns", record_bulk_read)
    standardized = standardize_excel_dates(path, table, mappings, catalog)
    assert scans == [(1, 2)]
    result = analyze_standardized_dates(
        standardized, mapped, reference_date=REFERENCE, pairs=(DatePair(1, 2),)
    )
    assert result.to_dict()["results"]["row_count"] == 3
    assert (
        result.to_dict()["results"]["columns"][0]["cells"][1]["code"]
        == "excel_fictitious_1900_02_29"
    )
    assert path.read_bytes() == before
    cancelled = Event()
    cancelled.set()
    with pytest.raises(ScanCancelled):
        standardize_excel_dates(path, table, mappings, catalog, cancelled=cancelled)
    path.write_bytes(before + b"changed")
    with pytest.raises(ValueError, match="identity|changed|match"):
        standardize_excel_dates(path, table, mappings, catalog)


def test_deterministic_results_are_independent_of_input_order_and_returned_views(catalog):
    table, cols = fixture_columns([("2026-01-01", "2027-01-01")])
    result = analyze_dates(table, cols, bindings(), catalog, reference_date=REFERENCE)
    reversed_result = analyze_dates(
        table, tuple(reversed(cols)), tuple(reversed(bindings())), catalog, reference_date=REFERENCE
    )
    assert result.fingerprint == reversed_result.fingerprint
    view = result.to_dict()
    view["results"]["columns"].clear()
    assert len(result.to_dict()["results"]["columns"]) == 2


def test_missing_mapping_calendar_duplicate_pair_and_limits_fail(catalog, monkeypatch):
    table, cols = fixture_columns([("2026-01-01", "2027-01-01")])
    with pytest.raises(ValueError, match="active profile"):
        analyze_dates(table, cols, bindings(), Catalog("empty", ()), reference_date=REFERENCE)
    with pytest.raises(ValueError, match="calendar snapshots"):
        analyze_dates(
            table,
            cols,
            bindings(),
            catalog,
            reference_date=REFERENCE,
            calendars=(build_calendar("us.sifma_fixed_income"),),
        )
    with pytest.raises(ValueError, match="Date pairs"):
        analyze_dates(
            table,
            cols,
            bindings(),
            catalog,
            reference_date=REFERENCE,
            pairs=(DatePair(3, 4), DatePair(3, 4)),
        )
    monkeypatch.setattr("loan_tape.date_analysis.MAX_CELLS", 1)
    with pytest.raises(ValueError, match="cell limit"):
        analyze_dates(table, cols, bindings(), catalog, reference_date=REFERENCE)
