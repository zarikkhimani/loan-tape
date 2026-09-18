"""Validated desktop date-workflow settings, independent of Tk widgets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from loan_tape.date_analysis import CalendarBinding, DateBinding, DatePair
from loan_tape.date_calendar import CalendarSnapshot, build_calendar
from loan_tape.date_parser import DateProfile
from loan_tape.date_standardization import DateMapping
from loan_tape.packs import Catalog

LOAN_DATE_FIELDS = (
    "loan.dates:closing_date",
    "loan.dates:original_maturity_date",
    "loan.dates:current_maturity_date",
    "loan.dates:reporting_date",
)
FIELD_ACTIVITIES = {
    "loan.dates:closing_date": {"reference_screening", "closing"},
    "loan.dates:original_maturity_date": {"reference_screening", "maturity"},
    "loan.dates:current_maturity_date": {"reference_screening", "maturity"},
    "loan.dates:reporting_date": {"reference_screening"},
}


@dataclass(frozen=True)
class MappingSetting:
    field_id: str
    column: int
    text_formats: tuple[str, ...]


@dataclass(frozen=True)
class ReviewSetting:
    """Red-flag policy for an already mapped field."""

    field_id: str
    require_value: bool | None = None
    earliest: date | None = None
    latest: date | None = None
    reference_check: str = "none"


@dataclass(frozen=True)
class CalendarSetting:
    field_id: str
    calendar_id: str
    activity: str
    require_business_day: bool = False
    agreement_reference: str | None = None


@dataclass(frozen=True)
class PairSetting:
    start_field_id: str
    end_field_id: str
    allow_equal: bool = True
    minimum_days: int | None = None
    maximum_days: int | None = None


def build_standardization_inputs(
    catalog: Catalog,
    mappings: tuple[MappingSetting, ...],
    *,
    two_digit_year_start: int | None = None,
    missing_tokens: tuple[str, ...] = (),
    strip_whitespace: bool = False,
    accept_timestamp_date: bool = False,
) -> tuple[DateMapping, ...]:
    """Build only source mappings and interpretation profiles; no rules are applied."""
    available = {item.id for item in catalog.fields}
    if not set(LOAN_DATE_FIELDS).issubset(available):
        raise ValueError("Activate the loan.dates dictionary pack before standardizing dates.")
    if not mappings:
        raise ValueError("Map at least one source column to a date field.")
    if any(item.field_id not in LOAN_DATE_FIELDS for item in mappings):
        raise ValueError("Date mappings must use the maintained loan.dates fields.")
    fields = [item.field_id for item in mappings]
    columns = [item.column for item in mappings]
    if len(fields) != len(set(fields)) or len(columns) != len(set(columns)):
        raise ValueError("Each date field and source column can be mapped only once.")

    result = []
    for mapping in mappings:
        if not mapping.text_formats:
            raise ValueError("Choose at least one accepted text format for every mapped column.")
        if (
            any(value in {"M/D/YY", "D/M/YY"} for value in mapping.text_formats)
            and two_digit_year_start is None
        ):
            raise ValueError("Two-digit text dates require an explicit year-window start.")
        profile = DateProfile(
            id="desktop.explicit-dates",
            text_formats=mapping.text_formats,
            two_digit_year_start=two_digit_year_start,
            missing_tokens=missing_tokens,
            whitespace="strip" if strip_whitespace else "reject",
            timestamps="date_component" if accept_timestamp_date else "reject",
            numeric_dates="excel_serial",
        )
        result.append(DateMapping(mapping.column, mapping.field_id, profile))
    return tuple(sorted(result, key=lambda item: item.column))


def build_red_flag_inputs(
    mappings: tuple[DateMapping, ...],
    *,
    reviews: tuple[ReviewSetting, ...] = (),
    calendars: tuple[CalendarSetting, ...] = (),
    pair: PairSetting | None = None,
) -> tuple[tuple[DateBinding, ...], tuple[DatePair, ...], tuple[CalendarSnapshot, ...]]:
    """Build review rules for an existing standardization without import settings."""
    if not mappings or any(not isinstance(item, DateMapping) for item in mappings):
        raise ValueError("Run date standardization before configuring red flags.")
    fields = [item.field_id for item in mappings]
    columns = [item.column for item in mappings]
    if len(fields) != len(set(fields)) or len(columns) != len(set(columns)):
        raise ValueError("Standardized date mappings must be unique.")

    review_by_field = {item.field_id: item for item in reviews}
    if len(review_by_field) != len(reviews) or set(review_by_field) - set(fields):
        raise ValueError("Review policies must be unique and belong to mapped fields.")
    calendar_by_field = {item.field_id: item for item in calendars}
    if len(calendar_by_field) != len(calendars) or set(calendar_by_field) - set(fields):
        raise ValueError("Calendar policies must be unique and belong to mapped fields.")
    for calendar_setting in calendars:
        if calendar_setting.activity not in FIELD_ACTIVITIES[calendar_setting.field_id]:
            raise ValueError(
                "The selected calendar activity does not match the mapped field meaning."
            )

    bindings = []
    for mapping in mappings:
        review = review_by_field.get(mapping.field_id, ReviewSetting(mapping.field_id))
        calendar = calendar_by_field.get(mapping.field_id)
        policy = (
            CalendarBinding(
                calendar.calendar_id,
                calendar.activity,
                calendar.require_business_day,
                calendar.agreement_reference,
            )
            if calendar
            else None
        )
        bindings.append(
            DateBinding(
                mapping.column,
                mapping.field_id,
                mapping.profile,
                review.require_value,
                review.earliest,
                review.latest,
                review.reference_check,
                policy,
            )
        )

    pairs: tuple[DatePair, ...] = ()
    by_field = {item.field_id: item.column for item in mappings}
    if pair is not None:
        if pair.start_field_id not in by_field or pair.end_field_id not in by_field:
            raise ValueError("The pair start and end fields must both be mapped.")
        pairs = (
            DatePair(
                by_field[pair.start_field_id],
                by_field[pair.end_field_id],
                pair.allow_equal,
                pair.minimum_days,
                pair.maximum_days,
            ),
        )
    snapshots = tuple(
        build_calendar(calendar_id)
        for calendar_id in sorted({item.calendar_id for item in calendars})
    )
    return tuple(bindings), pairs, snapshots
