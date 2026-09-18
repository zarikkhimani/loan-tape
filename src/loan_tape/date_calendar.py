"""Versioned calendar facts and explicit projections, never automatic date adjustment."""

from __future__ import annotations

import calendar
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date
from functools import cached_property
from importlib.resources import files
from types import MappingProxyType
from typing import Any

from loan_tape._date_json import canonical, fingerprint, integer, iso_date, text
from loan_tape.pack_format import VERSION_PATTERN, object_keys, parse_json

CALENDAR_ENGINE_VERSION = "2.0.0"
SUPPORTED_CALENDAR_ENGINE_VERSIONS = ("1.0.0", CALENDAR_ENGINE_VERSION)
CALENDAR_IDS = ("us.sifma_fixed_income",)


@dataclass(frozen=True)
class CalendarSource:
    id: str
    title: str
    url: str
    published_on: date | None
    verified_on: date

    def __post_init__(self) -> None:
        for name in ("id", "title", "url"):
            text(getattr(self, name), name)
        if not self.url.startswith("https://"):
            raise ValueError("Calendar sources require an HTTPS reference.")
        if type(self.verified_on) is not date or (
            self.published_on is not None and type(self.published_on) is not date
        ):
            raise ValueError("Calendar source dates must be calendar dates.")
        if self.published_on is not None and self.published_on > self.verified_on:
            raise ValueError("A source cannot be verified before publication.")


@dataclass(frozen=True)
class CalendarEvent:
    day: date
    actual_day: date | None
    name: str
    kind: str
    certainty: str
    source_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.day) is not date or (
            self.actual_day is not None and type(self.actual_day) is not date
        ):
            raise ValueError("Calendar events require calendar dates.")
        text(self.name, "Event name")
        if self.kind not in ("full_closure", "early_close"):
            raise ValueError("Unsupported calendar event kind.")
        if self.certainty not in ("published", "projected"):
            raise ValueError("Unsupported calendar event certainty.")
        if not isinstance(self.source_ids, tuple) or not self.source_ids:
            raise ValueError("Events must retain their source IDs.")


@dataclass(frozen=True)
class CalendarCoverage:
    year: int
    status: str
    source_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        integer(self.year, 1, 9999, "Coverage year")
        if self.status not in ("published", "projected", "unknown"):
            raise ValueError("Unsupported holiday coverage status.")
        if not isinstance(self.source_ids, tuple):
            raise ValueError("Coverage source IDs must be immutable.")
        if self.status != "unknown" and not self.source_ids:
            raise ValueError("Known coverage requires sources.")


@dataclass(frozen=True)
class CalendarConflict:
    day: date
    description: str
    resolution: str
    source_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.day) is not date:
            raise ValueError("Calendar conflicts require a date.")
        text(self.description, "Conflict description")
        text(self.resolution, "Conflict resolution")
        if not isinstance(self.source_ids, tuple) or len(self.source_ids) < 2:
            raise ValueError("Calendar conflicts require the competing sources.")


@dataclass(frozen=True)
class CalendarSnapshot:
    id: str
    version: str
    coverage: tuple[CalendarCoverage, ...]
    events: tuple[CalendarEvent, ...]
    sources: tuple[CalendarSource, ...]
    assumptions: tuple[str, ...]
    conflicts: tuple[CalendarConflict, ...] = ()
    engine_version: str = CALENDAR_ENGINE_VERSION

    def __post_init__(self) -> None:
        text(self.id, "Calendar ID")
        if not isinstance(self.version, str) or not VERSION_PATTERN.fullmatch(self.version):
            raise ValueError("Calendar version must be major.minor.patch.")
        if self.engine_version not in SUPPORTED_CALENDAR_ENGINE_VERSIONS:
            raise ValueError("Unsupported calendar engine version.")
        for name, cls in (
            ("coverage", CalendarCoverage),
            ("events", CalendarEvent),
            ("sources", CalendarSource),
            ("conflicts", CalendarConflict),
        ):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(v, cls) for v in values):
                raise ValueError(f"{name} must contain immutable validated objects.")
        if not isinstance(self.assumptions, tuple) or any(
            not isinstance(v, str) or not v.strip() for v in self.assumptions
        ):
            raise ValueError("Calendar assumptions must be immutable text.")
        ids = {s.id for s in self.sources}
        years = {c.year: c.status for c in self.coverage}
        if len(ids) != len(self.sources) or len(years) != len(self.coverage):
            raise ValueError("Duplicate calendar sources or coverage years.")
        if not years or len(years) > 1000 or len(self.events) > 30000:
            raise ValueError("Calendar snapshot exceeds supported coverage limits.")
        referenced: tuple[CalendarEvent | CalendarCoverage | CalendarConflict, ...] = (
            *self.events,
            *self.coverage,
            *self.conflicts,
        )
        for item in referenced:
            if any(not isinstance(v, str) or v not in ids for v in item.source_ids):
                raise ValueError("Unknown calendar source reference.")
            if len(set(item.source_ids)) != len(item.source_ids):
                raise ValueError("Duplicate calendar source reference.")
        keys = [(e.day, e.name, e.kind) for e in self.events]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate calendar events.")
        for event in self.events:
            if event.day.year not in years:
                raise ValueError("Calendar event lies outside coverage years.")
            if event.certainty == "projected" and years[event.day.year] != "projected":
                raise ValueError("Projected events require projected year coverage.")
        if any(c.day.year not in years for c in self.conflicts):
            raise ValueError("Calendar conflict lies outside coverage years.")

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {"format_version": 1, **asdict(self)}

    @classmethod
    def from_dict(cls, value: Any) -> CalendarSnapshot:
        data = object_keys(
            value, set(cls.__dataclass_fields__) | {"format_version"}, set(), "calendar snapshot"
        )
        if type(data["format_version"]) is not int or data["format_version"] != 1:
            raise ValueError("Unsupported calendar snapshot format.")
        for key in ("coverage", "events", "sources", "assumptions", "conflicts"):
            if not isinstance(data[key], list):
                raise ValueError(f"Calendar {key} must be an array.")
        sources = []
        for value in data["sources"]:
            row = object_keys(value, set(CalendarSource.__dataclass_fields__), set(), "source")
            sources.append(
                CalendarSource(
                    row["id"],
                    row["title"],
                    row["url"],
                    iso_date(row["published_on"]) if row["published_on"] is not None else None,
                    iso_date(row["verified_on"]),
                )
            )
        converted: dict[str, list[Any]] = {"coverage": [], "events": [], "conflicts": []}
        for key, constructor in (
            ("coverage", CalendarCoverage),
            ("events", CalendarEvent),
            ("conflicts", CalendarConflict),
        ):
            for value in data[key]:
                row = dict(object_keys(value, set(constructor.__dataclass_fields__), set(), key))
                if not isinstance(row["source_ids"], list):
                    raise ValueError("Source IDs must be an array.")
                row["source_ids"] = tuple(row["source_ids"])
                for field in ("day", "actual_day"):
                    if field in row and row[field] is not None:
                        row[field] = iso_date(row[field])
                converted[key].append(constructor(**row))
        return cls(
            data["id"],
            data["version"],
            tuple(converted["coverage"]),
            tuple(converted["events"]),
            tuple(sources),
            tuple(data["assumptions"]),
            tuple(converted["conflicts"]),
            data["engine_version"],
        )

    @cached_property
    def _index(self) -> Mapping[date, tuple[CalendarEvent, ...]]:
        result: dict[date, list[CalendarEvent]] = {}
        for event in self.events:
            result.setdefault(event.day, []).append(event)
        return MappingProxyType({day: tuple(events) for day, events in result.items()})

    @cached_property
    def _coverage(self) -> Mapping[int, str]:
        return MappingProxyType({item.year: item.status for item in self.coverage})

    def check(self, day: date) -> dict[str, Any]:
        if type(day) is not date:
            raise ValueError("Calendar checks accept calendar dates, not timestamps.")
        events = self._index.get(day, ())
        coverage = self._coverage.get(day.year, "unknown")
        closures = [e for e in events if e.kind == "full_closure"]
        weekend = day.weekday() >= 5
        business_day: bool | None = not (weekend or closures)
        certainty = coverage
        if weekend:
            certainty = "weekday_calculation"
        elif closures:
            certainty = (
                "published" if any(e.certainty == "published" for e in closures) else "projected"
            )
        elif coverage == "unknown":
            business_day = None
        return {
            "calendar_id": self.id,
            "calendar_version": self.version,
            "weekday": (
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
                "Sunday",
            )[day.weekday()],
            "weekend": weekend,
            "holiday_coverage": coverage,
            "business_day": business_day,
            "decision_basis": certainty,
            "events": [asdict(e) for e in events],
            "conflicts": [asdict(c) for c in self.conflicts if c.day == day],
        }


def build_calendar(
    calendar_id: str, *, first_year: int = 1900, last_year: int = 2126
) -> CalendarSnapshot:
    """Freeze published SIFMA facts across a bounded review horizon.

    Unpublished years stay unknown; current rules are never backcast or projected.
    Weekends remain deterministic in every year. Callers can supply separately
    sourced CalendarSnapshots for other coverage.
    """
    if calendar_id not in CALENDAR_IDS:
        raise ValueError("Unsupported built-in calendar; provide a sourced custom snapshot.")
    integer(first_year, 1, 9999, "First year")
    integer(last_year, first_year, min(9999, first_year + 999), "Last year")
    raw = (
        files("loan_tape")
        .joinpath("calendar_data/sifma_us_fixed_income.json")
        .read_text(encoding="utf-8")
    )
    data = object_keys(
        parse_json(raw, "bundled calendar data"),
        {
            "format_version",
            "version",
            "verified_year",
            "sources",
            "assumptions",
            "calendars",
            "conflicts",
        },
        set(),
        "bundled calendar data",
    )
    if type(data["format_version"]) is not int or data["format_version"] != 1:
        raise ValueError("Unsupported bundled calendar format.")
    integer(data["verified_year"], 1, 9999, "Calendar verification year")
    specifications = object_keys(data["calendars"], set(CALENDAR_IDS), set(), "calendar IDs")
    spec = object_keys(
        specifications[calendar_id],
        {"published_years", "source_ids", "projection_sources", "events", "assumptions"},
        set(),
        "calendar schedule",
    )
    for owner, names in (
        (data, ("sources", "assumptions", "conflicts")),
        (spec, ("published_years", "source_ids", "projection_sources", "events", "assumptions")),
    ):
        if any(not isinstance(owner[name], list) for name in names):
            raise ValueError("Calendar schedule collections must be arrays.")
    for year in spec["published_years"]:
        integer(year, 1, 9999, "Published calendar year")
    if len(set(spec["published_years"])) != len(spec["published_years"]):
        raise ValueError("Duplicate published calendar years.")
    if any(
        not isinstance(row, list) or len(row) != 5 or not isinstance(row[4], list)
        for row in spec["events"]
    ):
        raise ValueError("Malformed published calendar event.")
    sources = tuple(
        CalendarSource(
            s["id"],
            s["title"],
            s["url"],
            iso_date(s["published_on"]) if s["published_on"] else None,
            iso_date(s["verified_on"]),
        )
        for s in data["sources"]
    )
    events = []
    coverage = []
    known_years = set(spec["published_years"])
    for year in range(first_year, last_year + 1):
        status = "unknown"
        source_ids: tuple[str, ...] = ()
        if year in known_years:
            status, source_ids = "published", tuple(spec["source_ids"])
        coverage.append(CalendarCoverage(year, status, source_ids))
    for row in spec["events"]:
        day = iso_date(row[0])
        if first_year <= day.year <= last_year:
            events.append(
                CalendarEvent(
                    day,
                    iso_date(row[1]) if row[1] else None,
                    row[2],
                    row[3],
                    "published",
                    tuple(row[4]),
                )
            )
    conflicts = tuple(
        CalendarConflict(
            iso_date(c["day"]), c["description"], c["resolution"], tuple(c["source_ids"])
        )
        for c in data["conflicts"]
        if first_year <= iso_date(c["day"]).year <= last_year
    )
    snapshot = CalendarSnapshot(
        calendar_id,
        data["version"],
        tuple(coverage),
        tuple(sorted(events, key=lambda e: (e.day, e.name, e.kind))),
        sources,
        tuple(data["assumptions"] + spec["assumptions"]),
        conflicts,
    )
    # Exercise the same strict boundary used when reopening saved runs.
    return CalendarSnapshot.from_dict(json.loads(canonical(snapshot.to_dict())))


def month_end(day: date) -> bool:
    return day.day == calendar.monthrange(day.year, day.month)[1]
