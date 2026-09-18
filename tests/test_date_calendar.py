"""SIFMA published facts, unknown coverage and agreement applicability remain distinguishable."""

import json
from dataclasses import replace
from datetime import date

import pytest

from loan_tape._date_json import canonical
from loan_tape.date_calendar import (
    CALENDAR_IDS,
    CalendarCoverage,
    CalendarEvent,
    CalendarSnapshot,
    build_calendar,
)


def test_single_builtin_calendar_uses_published_sifma_2026_schedule():
    assert CALENDAR_IDS == ("us.sifma_fixed_income",)
    cal = build_calendar(CALENDAR_IDS[0])
    full = cal.check(date(2026, 7, 3))
    assert full["business_day"] is False
    assert full["holiday_coverage"] == full["decision_basis"] == "published"
    assert full["events"][0]["name"] == "U.S. Independence Day"
    good_friday = cal.check(date(2026, 4, 3))
    assert good_friday["business_day"] is True
    assert good_friday["events"][0]["kind"] == "early_close"
    assert cal.check(date(2026, 10, 12))["business_day"] is False
    assert all(source.id.startswith("sifma-") for source in cal.sources)
    assert not cal.conflicts


@pytest.mark.parametrize("day", ["2026-04-03", "2026-11-27", "2026-12-24", "2027-11-26"])
def test_published_early_closes_remain_business_days(day):
    check = build_calendar("us.sifma_fixed_income").check(date.fromisoformat(day))
    assert check["business_day"] is True
    assert check["events"][0]["kind"] == "early_close"


def test_published_good_friday_exceptions_are_retained():
    cal = build_calendar("us.sifma_fixed_income")
    assert cal.check(date(2021, 4, 2))["business_day"] is True
    assert cal.check(date(2021, 4, 2))["events"][0]["kind"] == "early_close"
    assert cal.check(date(2022, 4, 15))["business_day"] is False
    assert cal.check(date(2023, 4, 7))["business_day"] is True
    assert cal.check(date(2025, 4, 18))["business_day"] is False


def test_published_observance_and_new_year_boundary():
    cal = build_calendar("us.sifma_fixed_income")
    for day in (date(2027, 6, 18), date(2027, 7, 5), date(2027, 12, 24)):
        assert cal.check(day)["business_day"] is False
    early = cal.check(date(2027, 12, 31))
    assert early["business_day"] is True
    assert early["events"][0]["kind"] == "early_close"
    event = cal.check(date(2027, 6, 18))["events"][0]
    assert event["actual_day"] == date(2027, 6, 19)


def test_unpublished_future_weekdays_are_unknown_and_weekends_remain_deterministic():
    cal = build_calendar("us.sifma_fixed_income")
    future = cal.check(date(2126, 6, 19))
    assert future["business_day"] is None
    assert future["decision_basis"] == future["holiday_coverage"] == "unknown"
    historical = cal.check(date(2020, 6, 19))
    assert historical["business_day"] is True
    assert historical["holiday_coverage"] == "published"
    assert not historical["events"]
    old_weekday = cal.check(date(2018, 6, 19))
    assert old_weekday["business_day"] is None
    assert old_weekday["holiday_coverage"] == "unknown"
    future_weekend = cal.check(date(2100, 3, 27))
    assert future_weekend["business_day"] is False
    assert future_weekend["decision_basis"] == "weekday_calculation"


def test_extended_horizon_does_not_invent_holidays():
    cal = build_calendar("us.sifma_fixed_income", first_year=2099, last_year=2126)
    assert cal.check(date(2100, 3, 26))["business_day"] is None
    assert cal.check(date(2100, 3, 1))["weekday"] == "Monday"
    assert len(cal.coverage) == 28
    assert all(item.status == "unknown" for item in cal.coverage)
    with pytest.raises(ValueError):
        date(2100, 2, 29)
    assert cal.check(date(2127, 1, 2))["holiday_coverage"] == "unknown"


def test_snapshot_round_trip_read_only_indexes_and_v1_replay():
    original = build_calendar("us.sifma_fixed_income")
    encoded = canonical(original.to_dict())
    reopened = CalendarSnapshot.from_dict(json.loads(encoded))
    assert original == reopened and original.fingerprint == reopened.fingerprint
    legacy = replace(original, engine_version="1.0.0")
    assert CalendarSnapshot.from_dict(json.loads(canonical(legacy.to_dict()))) == legacy
    with pytest.raises(ValueError, match="Unsupported calendar engine"):
        replace(original, engine_version="0.9.0")
    day = date(2026, 1, 1)
    check = original.check(day)
    check["events"].clear()
    assert original.check(day)["business_day"] is False
    with pytest.raises(TypeError):
        original._coverage[2026] = "unknown"
    with pytest.raises(TypeError):
        original._index[day] = ()


@pytest.mark.parametrize(
    "change",
    [
        {"calendar_id": "invented"},
        {"first_year": True},
        {"first_year": 2028, "last_year": 2027},
        {"first_year": 1, "last_year": 2126},
    ],
)
def test_invalid_build_policies_fail(change):
    options = {"calendar_id": "us.sifma_fixed_income", **change}
    with pytest.raises(ValueError):
        build_calendar(**options)


def test_calendar_rejects_duplicate_and_unreferenced_facts():
    cal = build_calendar("us.sifma_fixed_income")
    with pytest.raises(ValueError, match="Duplicate calendar events"):
        replace(cal, events=cal.events + cal.events[:1])
    with pytest.raises(ValueError, match="Unknown calendar source"):
        replace(
            cal,
            events=(
                CalendarEvent(
                    date(2026, 2, 3), None, "Unknown", "full_closure", "published", ("missing",)
                ),
            ),
        )
    with pytest.raises(ValueError, match="Projected events require"):
        replace(cal, events=(replace(cal.events[0], certainty="projected"),))
    with pytest.raises(ValueError, match="Duplicate calendar sources or coverage"):
        replace(cal, coverage=cal.coverage + (CalendarCoverage(2026, "unknown", ()),))


def test_published_schedule_is_exact_and_unpublished_year_has_no_events():
    cal = build_calendar("us.sifma_fixed_income")
    published = {
        event.day.isoformat()
        for event in cal.events
        if event.kind == "full_closure" and event.day.year == 2026
    }
    assert published == {
        "2026-01-01",
        "2026-01-19",
        "2026-02-16",
        "2026-05-25",
        "2026-06-19",
        "2026-07-03",
        "2026-09-07",
        "2026-10-12",
        "2026-11-11",
        "2026-11-26",
        "2026-12-25",
    }
    assert not [event for event in cal.events if event.day.year == 2028]
    check = cal.check(date(2028, 7, 4))
    assert check["business_day"] is None
    assert check["holiday_coverage"] == "unknown"
