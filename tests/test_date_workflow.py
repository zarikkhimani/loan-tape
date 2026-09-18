"""The desktop workflow converts only explicit choices into engine inputs."""

from datetime import date
from pathlib import Path

import pytest

from loan_tape.date_workflow import (
    CalendarSetting,
    MappingSetting,
    PairSetting,
    ReviewSetting,
    build_red_flag_inputs,
    build_standardization_inputs,
)
from loan_tape.pack_format import load_pack
from loan_tape.packs import Catalog

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def catalog():
    return Catalog("default", (load_pack(ROOT / "packs/loan-dates"),))


def test_explicit_workflow_choices_build_pinned_engine_inputs(catalog):
    mappings = (
        MappingSetting(
            "loan.dates:closing_date",
            3,
            ("M/D/YY", "YYYY-MM-DD"),
        ),
        MappingSetting("loan.dates:current_maturity_date", 4, ("M/D/YY",)),
    )
    calendars = (
        CalendarSetting("loan.dates:closing_date", "us.sifma_fixed_income", "closing"),
        CalendarSetting(
            "loan.dates:current_maturity_date",
            "us.sifma_fixed_income",
            "maturity",
            True,
            "Credit Agreement section 10.8",
        ),
    )
    standardized = build_standardization_inputs(
        catalog,
        mappings,
        two_digit_year_start=2000,
        missing_tokens=("NA", "N/A"),
        strip_whitespace=True,
        accept_timestamp_date=True,
    )
    bindings, pairs, snapshots = build_red_flag_inputs(
        standardized,
        reviews=(
            ReviewSetting(
                "loan.dates:closing_date",
                True,
                date(2000, 1, 1),
                date(2126, 12, 31),
                "flag_after",
            ),
        ),
        calendars=calendars,
        pair=PairSetting(
            "loan.dates:closing_date", "loan.dates:current_maturity_date", False, 1, 5000
        ),
    )

    assert [item.column for item in bindings] == [3, 4]
    assert bindings[0].profile.text_formats == ("M/D/YY", "YYYY-MM-DD")
    assert bindings[0].profile.numeric_dates == "excel_serial"
    assert bindings[0].profile.missing_tokens == ("NA", "N/A")
    assert bindings[0].calendar is not None
    assert bindings[1].calendar is not None
    assert bindings[1].calendar.require_business_day is True
    assert pairs[0].start_column == 3 and pairs[0].end_column == 4
    assert pairs[0].allow_equal is False
    assert [item.id for item in snapshots] == ["us.sifma_fixed_income"]
    assert snapshots[0].coverage[-1].year == 2126
    assert snapshots[0].coverage[-1].status == "unknown"


def test_standardization_and_red_flag_settings_are_separate(catalog):
    mappings = build_standardization_inputs(
        catalog,
        (MappingSetting("loan.dates:closing_date", 3, ("YYYY-MM-DD",)),),
    )
    assert mappings[0].field_id == "loan.dates:closing_date"
    assert not hasattr(mappings[0], "earliest")

    bindings, pairs, calendars = build_red_flag_inputs(
        mappings,
        reviews=(
            ReviewSetting(
                "loan.dates:closing_date",
                require_value=True,
                earliest=date(2020, 1, 1),
            ),
        ),
    )
    assert bindings[0].require_value is True
    assert bindings[0].earliest == date(2020, 1, 1)
    assert pairs == () and calendars == ()


@pytest.mark.parametrize(
    "mappings, match",
    [
        ((), "Map at least"),
        (
            (
                MappingSetting("loan.dates:closing_date", 3, ("YYYY-MM-DD",)),
                MappingSetting("loan.dates:current_maturity_date", 3, ("YYYY-MM-DD",)),
            ),
            "only once",
        ),
    ],
)
def test_incomplete_or_conflicting_standardization_choices_fail(catalog, mappings, match):
    with pytest.raises(ValueError, match=match):
        build_standardization_inputs(catalog, mappings)


@pytest.mark.parametrize(
    "calendars, pair, match",
    [
        (
            (
                CalendarSetting(
                    "loan.dates:current_maturity_date", "us.sifma_fixed_income", "maturity"
                ),
            ),
            None,
            "mapped fields",
        ),
        (
            (),
            PairSetting("loan.dates:closing_date", "loan.dates:current_maturity_date"),
            "both be mapped",
        ),
    ],
)
def test_incomplete_red_flag_choices_fail(catalog, calendars, pair, match):
    mappings = build_standardization_inputs(
        catalog,
        (MappingSetting("loan.dates:closing_date", 3, ("YYYY-MM-DD",)),),
    )
    with pytest.raises(ValueError, match=match):
        build_red_flag_inputs(mappings, calendars=calendars, pair=pair)


def test_two_digit_years_and_confirmed_business_day_rules_require_context(catalog):
    mapping = (MappingSetting("loan.dates:closing_date", 3, ("M/D/YY",)),)
    with pytest.raises(ValueError, match="year-window"):
        build_standardization_inputs(catalog, mapping)
    standardized = build_standardization_inputs(catalog, mapping, two_digit_year_start=2000)
    with pytest.raises(ValueError, match="agreement reference"):
        build_red_flag_inputs(
            standardized,
            calendars=(
                CalendarSetting(
                    "loan.dates:closing_date", "us.sifma_fixed_income", "closing", True
                ),
            ),
        )


def test_unsupported_calendar_fails_closed(catalog):
    mappings = build_standardization_inputs(
        catalog,
        (MappingSetting("loan.dates:closing_date", 3, ("YYYY-MM-DD",)),),
    )
    with pytest.raises(ValueError, match="Unsupported built-in calendar"):
        build_red_flag_inputs(
            mappings,
            calendars=(CalendarSetting("loan.dates:closing_date", "invented", "closing"),),
        )
