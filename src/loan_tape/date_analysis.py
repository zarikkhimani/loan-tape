"""Complete-row date analysis with explicit mappings, evidence and rule provenance."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, fields
from datetime import date
from fractions import Fraction
from threading import Event
from typing import Any

from loan_tape._date_json import canonical, fingerprint, integer, iso_date, text
from loan_tape.date_calendar import CalendarSnapshot, month_end
from loan_tape.date_parser import PARSER_VERSION, DateEvidence, DateProfile, DateSource, parse_date
from loan_tape.date_reader import DateColumnEvidence
from loan_tape.date_standardization import STANDARDIZATION_VERSION, DateMapping, DateStandardization
from loan_tape.pack_format import load_pack_files, object_keys, parse_json
from loan_tape.packs import Catalog
from loan_tape.ranges import parse_range
from loan_tape.selection import SavedTable, SourceSelection
from loan_tape.workbook_index import check_cancelled

ANALYSIS_VERSION = "1.0.0"
MAX_CELLS = 200_000
STATUSES = ("valid", "ambiguous", "invalid", "missing", "unsupported", "source_error")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass(frozen=True)
class CalendarBinding:
    calendar_id: str
    activity: str = "reference_screening"
    require_business_day: bool = False
    agreement_reference: str | None = None

    def __post_init__(self) -> None:
        text(self.calendar_id, "Calendar ID")
        if self.activity not in (
            "reference_screening",
            "closing",
            "maturity",
            "funding",
            "settlement",
            "delayed_compensation_start",
        ):
            raise ValueError("Unsupported date activity.")
        if type(self.require_business_day) is not bool:
            raise ValueError("Business-day requirement must be boolean.")
        if self.agreement_reference is not None:
            text(self.agreement_reference, "Agreement reference")
        if self.require_business_day and (
            not self.agreement_reference or self.activity == "reference_screening"
        ):
            raise ValueError(
                "A business-day requirement needs a confirmed activity and agreement reference."
            )


@dataclass(frozen=True)
class DateBinding:
    column: int
    field_id: str
    profile: DateProfile
    require_value: bool | None = None
    earliest: date | None = None
    latest: date | None = None
    reference_check: str = "none"
    calendar: CalendarBinding | None = None

    def __post_init__(self) -> None:
        integer(self.column, 1, 16384, "Original column")
        text(self.field_id, "Mapped field ID")
        if not isinstance(self.profile, DateProfile):
            raise ValueError("Date mapping requires an explicit validated parsing profile.")
        if self.require_value is not None and type(self.require_value) is not bool:
            raise ValueError("Value requirement must be boolean or unspecified.")
        for value in (self.earliest, self.latest):
            if value is not None and type(value) is not date:
                raise ValueError("Date bounds must be calendar dates.")
        if self.earliest and self.latest and self.earliest > self.latest:
            raise ValueError("Earliest date exceeds latest date.")
        if self.reference_check not in ("none", "flag_before", "flag_after"):
            raise ValueError("Unsupported reference-date check.")
        if self.calendar is not None and not isinstance(self.calendar, CalendarBinding):
            raise ValueError("Calendar mapping requires an explicit activity policy.")

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "profile": json.loads(self.profile.to_json()),
            "profile_fingerprint": self.profile.fingerprint,
        }

    @classmethod
    def from_dict(cls, value: Any) -> DateBinding:
        data = dict(
            object_keys(
                value,
                {f.name for f in fields(cls)} | {"profile_fingerprint"},
                set(),
                "date mapping",
            )
        )
        profile = DateProfile.from_json(canonical(data.pop("profile")))
        if data.pop("profile_fingerprint") != profile.fingerprint:
            raise ValueError("Date profile fingerprint mismatch.")
        for name in ("earliest", "latest"):
            if data[name] is not None:
                data[name] = iso_date(data[name])
        if data["calendar"] is not None:
            data["calendar"] = CalendarBinding(
                **object_keys(
                    data["calendar"],
                    {f.name for f in fields(CalendarBinding)},
                    set(),
                    "calendar mapping",
                )
            )
        return cls(profile=profile, **data)


@dataclass(frozen=True)
class DatePair:
    start_column: int
    end_column: int
    allow_equal: bool = True
    minimum_days: int | None = None
    maximum_days: int | None = None

    def __post_init__(self) -> None:
        for value in (self.start_column, self.end_column):
            integer(value, 1, 16384, "Pair column")
        if self.start_column == self.end_column or type(self.allow_equal) is not bool:
            raise ValueError("A date pair requires distinct columns and an equality policy.")
        for bound in (self.minimum_days, self.maximum_days):
            if bound is not None:
                integer(bound, 0, 3652058, "Elapsed-day bound")
        if (
            self.minimum_days is not None
            and self.maximum_days is not None
            and self.minimum_days > self.maximum_days
        ):
            raise ValueError("Minimum elapsed days exceeds maximum.")


@dataclass(frozen=True)
class DateAnalysis:
    """Canonical immutable result. to_dict returns a disposable, independent view."""

    document_json: str

    def to_dict(self) -> dict[str, Any]:
        return object_keys(
            parse_json(self.document_json, "date analysis"),
            {"format_version", "engine_version", "parser_version", "inputs", "results"},
            set(),
            "date analysis",
        )

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.to_dict())


def _quantile(values: list[int], numerator: int) -> Fraction:
    position = Fraction((len(values) - 1) * numerator, 4)
    index = position.numerator // position.denominator
    if index == len(values) - 1:
        return Fraction(values[index])
    return values[index] + (values[index + 1] - values[index]) * (position - index)


def _statistics(values: list[int]) -> dict[str, Any]:
    """Exact rational medians and inclusive, linearly interpolated IQR fences."""
    ordered = sorted(values)
    if not ordered:
        return {"count": 0, "minimum": None, "maximum": None, "median": None, "iqr": None}
    result: dict[str, Any] = {
        "count": len(values),
        "minimum": ordered[0],
        "maximum": ordered[-1],
        "median": str(_quantile(ordered, 2)),
        "iqr": None,
    }
    if len(ordered) >= 4:
        q1, q3 = _quantile(ordered, 1), _quantile(ordered, 3)
        spread = q3 - q1
        result["iqr"] = {
            "q1": str(q1),
            "q3": str(q3),
            "multiplier": "3/2",
            "lower": str(q1 - Fraction(3, 2) * spread),
            "upper": str(q3 + Fraction(3, 2) * spread),
            "method": "inclusive_linear",
        }
    return result


def _outside_iqr(value: int, stats: dict[str, Any]) -> bool:
    bounds = stats["iqr"]
    return bounds is not None and (
        value < Fraction(bounds["lower"]) or value > Fraction(bounds["upper"])
    )


def _evidence_from_dict(value: Any) -> DateEvidence:
    row = dict(object_keys(value, {f.name for f in fields(DateEvidence)}, set(), "date evidence"))
    row["source"] = DateSource(
        **object_keys(row["source"], {f.name for f in fields(DateSource)}, set(), "date source")
    )
    attrs = row["formula_attributes"]
    if not isinstance(attrs, list) or any(not isinstance(a, list) or len(a) != 2 for a in attrs):
        raise ValueError("Formula attributes must be pairs.")
    row["formula_attributes"] = tuple(tuple(a) for a in attrs)
    return DateEvidence(**row)


def analyze_dates(
    table: SavedTable,
    columns: tuple[DateColumnEvidence, ...],
    bindings: tuple[DateBinding, ...],
    catalog: Catalog,
    *,
    reference_date: date,
    reporting_date: date | None = None,
    pairs: tuple[DatePair, ...] = (),
    calendars: tuple[CalendarSnapshot, ...] = (),
    cancelled: Event | None = None,
) -> DateAnalysis:
    """Analyze every selected data row. No mapping, date adjustment or loan term is inferred."""
    check_cancelled(cancelled)
    if type(reference_date) is not date or (
        reporting_date is not None and type(reporting_date) is not date
    ):
        raise ValueError("Reference/reporting dates must be explicit calendar dates.")
    if not isinstance(table, SavedTable) or not isinstance(catalog, Catalog):
        raise ValueError("Analysis requires a saved data set and dictionary catalog.")
    for values, cls in (
        (columns, DateColumnEvidence),
        (bindings, DateBinding),
        (pairs, DatePair),
        (calendars, CalendarSnapshot),
    ):
        if not isinstance(values, tuple) or any(not isinstance(v, cls) for v in values):
            raise ValueError("Analysis inputs must be tuples of validated objects.")
    if not bindings:
        raise ValueError("Choose at least one explicitly mapped date column.")
    selection = table.selection
    first = selection.header_row + 1 if selection.header_row is not None else selection.area.min_row
    rows = range(first, selection.area.max_row + 1)
    if len(rows) * len(bindings) > MAX_CELLS:
        raise ValueError(f"Date analysis exceeds the {MAX_CELLS:,}-cell limit.")
    by_column = {c.column: c for c in columns}
    mapped = {b.column: b for b in bindings}
    if (
        len(by_column) != len(columns)
        or len(mapped) != len(bindings)
        or by_column.keys() != mapped.keys()
    ):
        raise ValueError(
            "Every analyzed column needs one mapping and one complete evidence column."
        )
    if len({p.id for p in catalog.packs}) != len(catalog.packs):
        raise ValueError("Dictionary catalog has duplicate pack IDs.")
    # Validate supplied catalog objects against their exact retained source texts.
    for pack in catalog.packs:
        if load_pack_files(dict(pack.files)) != pack:
            raise ValueError("Dictionary object differs from its retained source snapshot.")
    calendar_map = {c.id: c for c in calendars}
    if len(calendar_map) != len(calendars):
        raise ValueError("Duplicate calendar snapshot IDs.")
    used_calendars = {b.calendar.calendar_id for b in bindings if b.calendar}
    if used_calendars != calendar_map.keys():
        raise ValueError("Provide exactly the calendar snapshots explicitly selected by mappings.")
    pair_keys = [(p.start_column, p.end_column) for p in pairs]
    if len(set(pair_keys)) != len(pairs) or any(
        a not in mapped or b not in mapped for a, b in pair_keys
    ):
        raise ValueError("Date pairs require distinct, explicitly mapped columns.")
    for binding in bindings:
        definition = catalog.get_field(binding.field_id).field
        if definition.data_type != "date":
            raise ValueError("Mapped dictionary field is not a date.")
        evidence = by_column[binding.column]
        if (
            evidence.selection != selection
            or not selection.area.min_column <= binding.column <= selection.area.max_column
        ):
            raise ValueError("Date evidence belongs to a different selection or column.")
        if evidence.date_system not in ("1900", "1904") or len(evidence.cells) != len(rows):
            raise ValueError("Incomplete date evidence or invalid workbook date system.")
        if not isinstance(evidence.cells, tuple) or any(
            not isinstance(c, DateEvidence) for c in evidence.cells
        ):
            raise ValueError("Date evidence cells must be an immutable tuple.")
        for row, cell in zip(rows, evidence.cells, strict=True):
            check_cancelled(cancelled)
            expected = DateSource(selection.workbook_sha256, row, binding.column, selection.sheet)
            if cell.source != expected or cell.date_system not in (None, evidence.date_system):
                raise ValueError("Date evidence is missing, reordered or has inconsistent lineage.")

    findings: list[dict[str, Any]] = []

    def flag(
        rule: str,
        severity: str,
        columns: list[int],
        affected: list[int],
        message: str,
        **details: Any,
    ) -> None:
        findings.append(
            {
                "rule_id": rule,
                "rule_version": ANALYSIS_VERSION,
                "severity": severity,
                "columns": columns,
                "rows": affected,
                "message": message,
                "details": details,
            }
        )

    outputs = []
    dates: dict[int, dict[int, date]] = {}
    for binding in sorted(bindings, key=lambda b: b.column):
        cells = by_column[binding.column].cells
        definition = catalog.get_field(binding.field_id).field
        required = (
            binding.require_value
            if binding.require_value is not None
            else definition.blank_allowed is False
        )
        dates[binding.column] = valid = {}
        cell_outputs: list[dict[str, Any]] = []
        counts: Counter[str] = Counter()
        missing: Counter[str] = Counter()
        duplicates: dict[str, list[int]] = defaultdict(list)
        raw_groups: dict[str, list[int]] = defaultdict(list)
        formats: Counter[str] = Counter()
        source_kinds: Counter[str] = Counter()
        number_formats: Counter[str] = Counter()
        for cell in cells:
            check_cancelled(cancelled)
            result = parse_date(cell, binding.profile)
            row = cell.source.row
            counts[result.status] += 1
            source_kinds[cell.kind] += 1
            if cell.number_format is not None:
                number_formats[cell.number_format] += 1
            if result.missing_kind:
                missing[result.missing_kind] += 1
            else:
                raw_groups[
                    canonical({"kind": cell.kind, "raw": cell.raw, "date_system": cell.date_system})
                ].append(row)
            output = {
                key: value
                for key, value in asdict(result).items()
                if key not in ("evidence", "profile")
            }
            output.update(row=row, calendar=None)
            cell_outputs.append(output)
            if result.status != "valid":
                severity = (
                    "error"
                    if result.status in ("invalid", "source_error")
                    or (result.status == "missing" and required)
                    else "review"
                )
                if result.status != "missing" or required:
                    flag(
                        "date." + result.status,
                        severity,
                        [binding.column],
                        [row],
                        "Date was not interpreted; the original evidence is retained.",
                        code=result.code,
                        missing_kind=result.missing_kind,
                    )
                continue
            day = result.parsed_date
            assert day is not None
            valid[row] = day
            duplicates[day.isoformat()].append(row)
            formats.update(result.matched_formats)
            if result.notes:
                flag(
                    "date.interpretation_notes",
                    "info",
                    [binding.column],
                    [row],
                    "Explicit interpretation policy changed the parsing input only.",
                    notes=list(result.notes),
                )
            if (binding.earliest and day < binding.earliest) or (
                binding.latest and day > binding.latest
            ):
                flag(
                    "date.configured_bounds",
                    "review",
                    [binding.column],
                    [row],
                    "Date is outside the configured review bounds.",
                )
            if (binding.reference_check == "flag_before" and day < reference_date) or (
                binding.reference_check == "flag_after" and day > reference_date
            ):
                flag(
                    "date.reference_comparison",
                    "review",
                    [binding.column],
                    [row],
                    "Date crosses the explicitly selected reference-date threshold.",
                    reference_date=reference_date,
                )
            if binding.calendar:
                policy = binding.calendar
                check = calendar_map[policy.calendar_id].check(day)
                check["applicability"] = (
                    "confirmed_requirement" if policy.require_business_day else "screening_only"
                )
                output["calendar"] = check
                if check["business_day"] is False:
                    confirmed = policy.require_business_day and check["decision_basis"] in (
                        "published",
                        "weekday_calculation",
                    )
                    flag(
                        "calendar.non_business_day",
                        "error" if confirmed else "review",
                        [binding.column],
                        [row],
                        "Date is a non-business day under the selected calendar.",
                        agreement_reference=policy.agreement_reference,
                        activity=policy.activity,
                        decision_basis=check["decision_basis"],
                    )
                if check["holiday_coverage"] != "published":
                    flag(
                        "calendar." + check["holiday_coverage"] + "_coverage",
                        "review",
                        [binding.column],
                        [row],
                        "Holiday coverage is not a complete published annual schedule.",
                    )
                if check["conflicts"]:
                    flag(
                        "calendar.source_conflict",
                        "review",
                        [binding.column],
                        [row],
                        "Sources differ; the saved calendar records the competing claims and resolution.",
                    )
                if any(e["kind"] == "early_close" for e in check["events"]):
                    flag(
                        "calendar.early_close",
                        "info",
                        [binding.column],
                        [row],
                        "Published early close; this does not establish a full-day closure.",
                    )
            elif day.weekday() >= 5:
                flag(
                    "date.weekend",
                    "review",
                    [binding.column],
                    [row],
                    "Date falls on Saturday or Sunday; no agreement requirement is assumed.",
                )
        stats = _statistics([d.toordinal() for d in valid.values()])
        outliers = [r for r, d in valid.items() if _outside_iqr(d.toordinal(), stats)]
        if outliers:
            flag(
                "date.iqr_outlier",
                "review",
                [binding.column],
                outliers,
                "Date lies outside 1.5-IQR fences; this is a distribution heuristic, not an invalid date.",
            )
        repeated: list[dict[str, Any]] = [
            {"date": d, "rows": rs, "count": len(rs)}
            for d, rs in sorted(duplicates.items())
            if len(rs) > 1
        ]
        if repeated:
            flag(
                "date.repeated_dates",
                "info",
                [binding.column],
                sorted(r for item in repeated for r in item["rows"]),
                "Multiple records share interpreted dates; this does not establish duplicate loans.",
            )
        if len(formats) > 1 or len(source_kinds) > 1 or len(number_formats) > 1:
            flag(
                "date.mixed_representations",
                "info",
                [binding.column],
                [],
                "The column contains multiple formats or storage kinds; inspect the recorded distributions.",
            )
        all_dates = list(valid.values())
        outputs.append(
            {
                "column": binding.column,
                "field_id": binding.field_id,
                "effective_require_value": required,
                "row_count": len(rows),
                "status_counts": {s: counts[s] for s in STATUSES},
                "missing_counts": dict(missing),
                "valid_count": len(valid),
                "unresolved_count": len(rows) - len(valid),
                "earliest": min(all_dates) if all_dates else None,
                "latest": max(all_dates) if all_dates else None,
                "ordinal_statistics": stats,
                "duplicate_dates": repeated,
                "duplicate_raw_values": [
                    {"value": json.loads(value), "rows": rs, "count": len(rs)}
                    for value, rs in sorted(raw_groups.items())
                    if len(rs) > 1
                ],
                "source_kinds": dict(source_kinds),
                "number_formats": dict(number_formats),
                "matched_formats": dict(formats),
                "month_end_count": sum(month_end(d) for d in all_dates),
                "year_counts": dict(Counter(str(d.year) for d in all_dates)),
                "month_counts": {
                    str(m): sum(d.month == m for d in all_dates) for m in range(1, 13)
                },
                "day_of_month_counts": {
                    str(n): sum(d.day == n for d in all_dates) for n in range(1, 32)
                },
                "weekday_counts": {
                    name: sum(d.weekday() == n for d in all_dates)
                    for n, name in enumerate(WEEKDAYS)
                },
                "cells": cell_outputs,
            }
        )

    pair_outputs = []
    for pair in sorted(pairs, key=lambda p: (p.start_column, p.end_column)):
        pair_columns = [pair.start_column, pair.end_column]
        records: list[dict[str, Any]] = []
        gaps = []
        repeated_pairs: dict[tuple[date, date], list[int]] = defaultdict(list)
        for row in rows:
            check_cancelled(cancelled)
            start, end = dates[pair.start_column].get(row), dates[pair.end_column].get(row)
            days = (end - start).days if start is not None and end is not None else None
            records.append(
                {
                    "row": row,
                    "elapsed_calendar_days": days,
                    "status": "evaluated" if days is not None else "not_evaluable",
                }
            )
            if days is None:
                continue
            assert start is not None and end is not None
            gaps.append(days)
            repeated_pairs[(start, end)].append(row)
            if days < 0 or (days == 0 and not pair.allow_equal):
                flag(
                    "date.pair_order",
                    "error",
                    pair_columns,
                    [row],
                    "Dates violate the explicitly selected start/end order or equality policy.",
                )
            if (pair.minimum_days is not None and days < pair.minimum_days) or (
                pair.maximum_days is not None and days > pair.maximum_days
            ):
                flag(
                    "date.pair_bounds",
                    "review",
                    pair_columns,
                    [row],
                    "Elapsed calendar days fall outside the configured review bounds.",
                )
        stats = _statistics(gaps)
        outliers = [
            r["row"]
            for r in records
            if r["elapsed_calendar_days"] is not None
            and _outside_iqr(r["elapsed_calendar_days"], stats)
        ]
        if outliers:
            flag(
                "date.pair_iqr_outlier",
                "review",
                pair_columns,
                outliers,
                "Elapsed days lie outside 1.5-IQR fences; contractual tenor is not inferred.",
            )
        repeated = [
            {"start": a, "end": b, "rows": rs, "count": len(rs)}
            for (a, b), rs in sorted(repeated_pairs.items())
            if len(rs) > 1
        ]
        if repeated:
            flag(
                "date.repeated_pairs",
                "info",
                pair_columns,
                sorted(r for item in repeated for r in item["rows"]),
                "Records share a date pair; loan identity is not established by these fields.",
            )
        pair_outputs.append(
            {
                **asdict(pair),
                "row_count": len(rows),
                "evaluated_count": len(gaps),
                "not_evaluable_count": len(rows) - len(gaps),
                "statistics": stats,
                "negative_gap_count": sum(d < 0 for d in gaps),
                "same_day_count": sum(d == 0 for d in gaps),
                "positive_gap_count": sum(d > 0 for d in gaps),
                "duplicate_pairs": repeated,
                "records": records,
            }
        )
    findings.sort(key=lambda f: (f["columns"], f["rows"], f["rule_id"]))
    check_cancelled(cancelled)
    used_packs = {catalog.get_field(b.field_id).pack_id for b in bindings}
    inputs = {
        "dataset": {
            "id": table.id,
            "name": table.name,
            "source_sha256": selection.workbook_sha256,
            "sheet": selection.sheet,
            "range": selection.area.address,
            "header_row": selection.header_row,
        },
        "reference_date": reference_date,
        "reporting_date": reporting_date,
        "bindings": [b.to_dict() for b in sorted(bindings, key=lambda b: b.column)],
        "pairs": [asdict(p) for p in sorted(pairs, key=lambda p: (p.start_column, p.end_column))],
        "catalog_profile": catalog.profile,
        "dictionaries": [
            {"id": p.id, "version": p.version, "fingerprint": p.fingerprint, "files": dict(p.files)}
            for p in sorted(catalog.packs, key=lambda p: p.id)
            if p.id in used_packs
        ],
        "calendars": [
            {"fingerprint": c.fingerprint, "snapshot": c.to_dict()}
            for c in sorted(calendars, key=lambda c: c.id)
        ],
        "evidence": [
            {
                "column": c.column,
                "date_system": c.date_system,
                "cells": [asdict(e) for e in c.cells],
            }
            for c in sorted(columns, key=lambda c: c.column)
        ],
    }
    interpreted_rows = sum(all(r in dates[b.column] for b in bindings) for r in rows)
    results = {
        "row_count": len(rows),
        "cell_count": len(rows) * len(bindings),
        "column_count": len(bindings),
        "columns": outputs,
        "pairs": pair_outputs,
        "findings": findings,
        "finding_counts": {
            s: sum(f["severity"] == s for f in findings) for s in ("error", "review", "info")
        },
        "affected_row_count": len({r for f in findings for r in f["rows"]}),
        "all_dates_interpreted_row_count": interpreted_rows,
        "rows_with_unresolved_dates": len(rows) - interpreted_rows,
    }
    return DateAnalysis(
        canonical(
            {
                "format_version": 1,
                "engine_version": ANALYSIS_VERSION,
                "parser_version": PARSER_VERSION,
                "inputs": inputs,
                "results": results,
            }
        )
    )


def analyze_standardized_dates(
    standardization: DateStandardization,
    bindings: tuple[DateBinding, ...],
    *,
    reference_date: date,
    reporting_date: date | None = None,
    pairs: tuple[DatePair, ...] = (),
    calendars: tuple[CalendarSnapshot, ...] = (),
    cancelled: Event | None = None,
) -> DateAnalysis:
    """Run red flags against a completed parser-only handoff, without importing data."""
    if not isinstance(standardization, DateStandardization):
        raise ValueError("A completed date standardization is required.")
    if standardization.engine_version != STANDARDIZATION_VERSION:
        raise ValueError("Unsupported date standardization version.")
    expected = standardization.mappings
    actual = tuple(
        sorted(
            (
                DateMapping(binding.column, binding.field_id, binding.profile)
                for binding in bindings
            ),
            key=lambda item: item.column,
        )
    )
    if actual != expected:
        raise ValueError(
            "Red-flag mappings do not match the completed date standardization; standardize again."
        )
    return analyze_dates(
        standardization.table,
        standardization.evidence,
        bindings,
        standardization.catalog,
        reference_date=reference_date,
        reporting_date=reporting_date,
        pairs=pairs,
        calendars=calendars,
        cancelled=cancelled,
    )


def replay_analysis(value: Any, *, cancelled: Event | None = None) -> DateAnalysis:
    """Recompute using only retained evidence/settings; refuse incompatible engine versions."""
    document = object_keys(
        value,
        {"format_version", "engine_version", "parser_version", "inputs", "results"},
        set(),
        "analysis",
    )
    if type(document["format_version"]) is not int or document["format_version"] != 1:
        raise ValueError("Unsupported date analysis format.")
    if (
        document["engine_version"] != ANALYSIS_VERSION
        or document["parser_version"] != PARSER_VERSION
    ):
        raise ValueError("Replay requires the recorded analysis and parser versions.")
    inputs = object_keys(
        document["inputs"],
        {
            "dataset",
            "reference_date",
            "reporting_date",
            "bindings",
            "pairs",
            "catalog_profile",
            "dictionaries",
            "calendars",
            "evidence",
        },
        set(),
        "analysis inputs",
    )
    for name in ("bindings", "pairs", "dictionaries", "calendars", "evidence"):
        if not isinstance(inputs[name], list):
            raise ValueError(f"{name} must be an array.")
    text(inputs["catalog_profile"], "Catalog profile")
    data = object_keys(
        inputs["dataset"],
        {"id", "name", "source_sha256", "sheet", "range", "header_row"},
        set(),
        "data set",
    )
    table = SavedTable(
        data["id"],
        data["name"],
        SourceSelection(
            data["source_sha256"], data["sheet"], parse_range(data["range"]), data["header_row"]
        ),
    )
    packs = []
    for value in inputs["dictionaries"]:
        item = object_keys(
            value, {"id", "version", "fingerprint", "files"}, set(), "dictionary snapshot"
        )
        if not isinstance(item["files"], dict):
            raise ValueError("Dictionary files must be an object.")
        pack = load_pack_files(item["files"])
        if (pack.id, pack.version, pack.fingerprint) != (
            item["id"],
            item["version"],
            item["fingerprint"],
        ):
            raise ValueError("Dictionary snapshot identity mismatch.")
        packs.append(pack)
    calendars = []
    for value in inputs["calendars"]:
        item = object_keys(value, {"snapshot", "fingerprint"}, set(), "calendar snapshot envelope")
        snapshot = CalendarSnapshot.from_dict(item["snapshot"])
        if snapshot.fingerprint != item["fingerprint"]:
            raise ValueError("Calendar snapshot fingerprint mismatch.")
        calendars.append(snapshot)
    columns = []
    for value in inputs["evidence"]:
        item = object_keys(value, {"column", "date_system", "cells"}, set(), "date evidence column")
        if not isinstance(item["cells"], list):
            raise ValueError("Evidence cells must be an array.")
        columns.append(
            DateColumnEvidence(
                table.selection,
                item["column"],
                item["date_system"],
                tuple(_evidence_from_dict(c) for c in item["cells"]),
            )
        )
    return analyze_dates(
        table,
        tuple(columns),
        tuple(DateBinding.from_dict(b) for b in inputs["bindings"]),
        Catalog(inputs["catalog_profile"], tuple(packs)),
        reference_date=iso_date(inputs["reference_date"]),
        reporting_date=iso_date(inputs["reporting_date"])
        if inputs["reporting_date"] is not None
        else None,
        pairs=tuple(
            DatePair(**object_keys(p, {f.name for f in fields(DatePair)}, set(), "date pair"))
            for p in inputs["pairs"]
        ),
        calendars=tuple(calendars),
        cancelled=cancelled,
    )
