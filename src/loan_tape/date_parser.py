"""Explicit date interpretation, independent of loan rules, calendars, Excel and UI."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal

from loan_tape.pack_format import VERSION_PATTERN, object_keys, parse_json

PARSER_VERSION = "1.0.0"
TEXT_FORMATS = {
    "YYYY-MM-DD": (r"([0-9]{4})-([0-9]{2})-([0-9]{2})", "ymd"),
    "M/D/YYYY": (r"([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})", "mdy"),
    "D/M/YYYY": (r"([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})", "dmy"),
    "M/D/YY": (r"([0-9]{1,2})/([0-9]{1,2})/([0-9]{2})", "mdy"),
    "D/M/YY": (r"([0-9]{1,2})/([0-9]{1,2})/([0-9]{2})", "dmy"),
}
ISO_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})?"
)
DateSystem = Literal["1900", "1904"]
DateKind = Literal[
    "blank", "text", "number", "iso_date", "formula", "error", "boolean", "unsupported"
]
DateStatus = Literal["valid", "ambiguous", "invalid", "missing", "unsupported", "source_error"]


@dataclass(frozen=True)
class DateProfile:
    """A serializable interpretation policy; it neither maps fields nor validates loans."""

    id: str = "explicit-dates"
    version: str = "1.0.0"
    text_formats: tuple[str, ...] = ("YYYY-MM-DD",)
    two_digit_year_start: int | None = None
    missing_tokens: tuple[str, ...] = ()
    whitespace: Literal["reject", "strip"] = "reject"
    timestamps: Literal["reject", "date_component"] = "reject"
    numeric_dates: Literal["reject", "excel_serial"] = "reject"

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not re.fullmatch(r"[a-z][a-z0-9._-]{0,99}", self.id):
            raise ValueError("Date profile requires a stable lowercase ID.")
        if not isinstance(self.version, str) or not VERSION_PATTERN.fullmatch(self.version):
            raise ValueError("Date profile version must be major.minor.patch.")
        for name, values in (
            ("text_formats", self.text_formats),
            ("missing_tokens", self.missing_tokens),
        ):
            if not isinstance(values, tuple) or any(
                not isinstance(v, str) or not v for v in values
            ):
                raise ValueError(f"{name} must be a tuple of non-empty strings.")
            if len(set(values)) != len(values):
                raise ValueError(f"{name} contains duplicates.")
        if set(self.text_formats) - (set(TEXT_FORMATS) | {"ISO_DATETIME"}):
            raise ValueError("Unsupported date text format.")
        if self.two_digit_year_start is not None and (
            type(self.two_digit_year_start) is not int or not 1 <= self.two_digit_year_start <= 9900
        ):
            raise ValueError("Two-digit year window must start between 1 and 9900.")
        if not isinstance(self.whitespace, str) or self.whitespace not in {"reject", "strip"}:
            raise ValueError("Unsupported whitespace policy.")
        if not isinstance(self.timestamps, str) or self.timestamps not in {
            "reject",
            "date_component",
        }:
            raise ValueError("Unsupported timestamp policy.")
        if not isinstance(self.numeric_dates, str) or self.numeric_dates not in {
            "reject",
            "excel_serial",
        }:
            raise ValueError("Unsupported numeric date policy.")
        if any(v != v.strip() for v in self.missing_tokens):
            raise ValueError("Missing tokens must not contain surrounding whitespace.")

    def to_json(self) -> str:
        return json.dumps({"format_version": 1, **asdict(self)}, sort_keys=True, ensure_ascii=False)

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_json(cls, text: str) -> DateProfile:
        fields = set(cls.__dataclass_fields__)
        data = object_keys(
            parse_json(text, "date profile"), fields | {"format_version"}, set(), "date profile"
        )
        if type(data["format_version"]) is not int or data["format_version"] != 1:
            raise ValueError("Unsupported date profile format_version.")
        for name in ("text_formats", "missing_tokens"):
            if not isinstance(data[name], list):
                raise ValueError(f"{name} must be a JSON array.")
        return cls(
            id=data["id"],
            version=data["version"],
            text_formats=tuple(data["text_formats"]),
            two_digit_year_start=data["two_digit_year_start"],
            missing_tokens=tuple(data["missing_tokens"]),
            whitespace=data["whitespace"],
            timestamps=data["timestamps"],
            numeric_dates=data["numeric_dates"],
        )


@dataclass(frozen=True)
class DateSource:
    source_sha256: str
    row: int
    column: int
    sheet: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.source_sha256
        ):
            raise ValueError("Date source requires a SHA-256 identity.")
        if any(type(v) is not int or v < 1 for v in (self.row, self.column)):
            raise ValueError("Date source requires positive original row and column positions.")
        if self.sheet is not None and (not isinstance(self.sheet, str) or not self.sheet):
            raise ValueError("Worksheet name must be non-empty when supplied.")


@dataclass(frozen=True)
class DateEvidence:
    source: DateSource
    kind: DateKind
    raw: str | None
    storage_type: str | None = None
    raw_token: str | None = None
    number_format: str | None = None
    date_system: DateSystem | None = None
    present: bool = True
    formula: str | None = None
    formula_attributes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.source, DateSource):
            raise ValueError("Date evidence requires a validated source location.")
        if not isinstance(self.kind, str) or self.kind not in {
            "blank",
            "text",
            "number",
            "iso_date",
            "formula",
            "error",
            "boolean",
            "unsupported",
        }:
            raise ValueError("Unsupported date evidence kind.")
        for value in (
            self.raw,
            self.storage_type,
            self.raw_token,
            self.number_format,
            self.formula,
        ):
            if value is not None and not isinstance(value, str):
                raise ValueError(
                    "Retain source representations as text, not converted numbers/dates."
                )
        if self.date_system is not None and (
            not isinstance(self.date_system, str) or self.date_system not in {"1900", "1904"}
        ):
            raise ValueError("Unsupported Excel date system.")
        if type(self.present) is not bool or (not self.present and self.kind != "blank"):
            raise ValueError("Only absent blank cells may have present=False.")
        if self.kind == "blank" and self.raw is not None:
            raise ValueError("Blank evidence cannot contain a value; use text for empty text.")
        if self.raw is None and self.kind not in {"blank", "formula", "unsupported"}:
            raise ValueError("Nonblank evidence requires its source representation.")
        if not isinstance(self.formula_attributes, tuple) or any(
            not isinstance(pair, tuple)
            or len(pair) != 2
            or not all(isinstance(value, str) for value in pair)
            for pair in self.formula_attributes
        ):
            raise ValueError("Formula attributes must be immutable text pairs.")
        if len({key for key, _ in self.formula_attributes}) != len(self.formula_attributes):
            raise ValueError("Duplicate formula attributes.")
        if self.kind != "formula" and (self.formula is not None or self.formula_attributes):
            raise ValueError("Formula metadata requires formula evidence.")


@dataclass(frozen=True)
class DateResult:
    evidence: DateEvidence
    profile: DateProfile
    status: DateStatus
    parsed_date: date | None
    code: str
    candidates: tuple[date, ...] = ()
    matched_formats: tuple[str, ...] = ()
    missing_kind: str | None = None
    notes: tuple[str, ...] = ()
    parser_version: str = PARSER_VERSION


def parse_date(evidence: DateEvidence, profile: DateProfile) -> DateResult:
    """Interpret only explicitly permitted representations; never pick a likely date."""
    notes: list[str] = []

    def result(
        status: DateStatus,
        code: str,
        parsed: date | None = None,
        *,
        candidates: tuple[date, ...] = (),
        matched_formats: tuple[str, ...] = (),
        missing_kind: str | None = None,
    ) -> DateResult:
        # Explicitly typed construction keeps the public result immutable.
        return DateResult(
            evidence,
            profile,
            status,
            parsed,
            code,
            candidates,
            matched_formats,
            missing_kind,
            tuple(notes),
        )

    if evidence.kind == "formula":
        return result("unsupported", "formula_not_evaluated")
    if evidence.kind == "error":
        return result("source_error", "stored_source_error")
    if evidence.kind in {"boolean", "unsupported"}:
        return result("unsupported", "unsupported_source_type")
    if evidence.kind == "blank":
        return result(
            "missing", "missing_value", missing_kind="blank" if evidence.present else "absent"
        )
    assert evidence.raw is not None
    raw = evidence.raw
    if evidence.kind == "number":
        if profile.numeric_dates != "excel_serial":
            return result("unsupported", "numeric_date_not_enabled")
        if evidence.date_system is None:
            return result("ambiguous", "excel_date_system_required")
        if len(raw) > 256 or not re.fullmatch(
            r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?", raw
        ):
            return result("invalid", "invalid_excel_serial")
        try:
            serial = Decimal(raw)
        except InvalidOperation:
            return result("invalid", "invalid_excel_serial")
        if not serial.is_finite() or serial < 0 or serial >= 2958466:
            return result("invalid", "excel_serial_out_of_range")
        day = int(serial)
        if evidence.date_system == "1900" and day == 60:
            return result("invalid", "excel_fictitious_1900_02_29")
        if evidence.date_system == "1900" and day == 0:
            return result("unsupported", "excel_time_without_calendar_date")
        if serial != day:
            if profile.timestamps == "reject":
                return result("unsupported", "timestamp_requires_policy")
            notes.append(
                "Date component selected; the fractional serial remains in source evidence."
            )
        origin = date(1904, 1, 1) if evidence.date_system == "1904" else date(1899, 12, 31)
        offset = day - (1 if evidence.date_system == "1900" and day > 60 else 0)
        try:
            parsed = origin + timedelta(days=offset)
        except OverflowError:
            return result("invalid", "excel_serial_out_of_range")
        return result("valid", "excel_serial", parsed)

    if raw == "":
        return result("missing", "missing_value", missing_kind="empty_text")
    if raw.isspace():
        return result("missing", "missing_value", missing_kind="whitespace")
    if raw != raw.strip():
        if profile.whitespace == "reject":
            return result("invalid", "surrounding_whitespace")
        raw = raw.strip()
        notes.append("Surrounding whitespace stripped for interpretation; original retained.")
    if evidence.kind == "text" and raw in profile.missing_tokens:
        return result("missing", "declared_missing_token", missing_kind="token")
    if len(raw) > 256:
        return result("unsupported", "unsupported_text_representation")
    formats = (
        ("YYYY-MM-DD", "ISO_DATETIME") if evidence.kind == "iso_date" else profile.text_formats
    )
    candidates: set[date] = set()
    matched: list[str] = []
    needs_century = timestamp_blocked = syntax_matched = False
    for name in formats:
        if name == "ISO_DATETIME":
            if not ISO_TIMESTAMP.fullmatch(raw):
                continue
            syntax_matched = True
            try:
                stamp = datetime.fromisoformat(raw)
                # datetime normalizes offset minutes; reject non-clock offsets explicitly.
                if re.search(r"[+-][0-9]{2}:[0-9]{2}$", raw) and int(raw[-2:]) > 59:
                    continue
            except ValueError:
                continue
            if profile.timestamps == "reject":
                timestamp_blocked = True
                continue
            candidates.add(stamp.date())
            matched.append(name)
            notes.append(
                "Date component taken as written, without timezone conversion; timestamp retained."
            )
            continue
        pattern, order = TEXT_FORMATS[name]
        match = re.fullmatch(pattern, raw)
        if match is None:
            continue
        syntax_matched = True
        parts = dict(zip(order, map(int, match.groups()), strict=True))
        if name.endswith("/YY"):
            start = profile.two_digit_year_start
            if start is None:
                # Nonzero year suffixes share leap status across Gregorian centuries.
                try:
                    date(2000 + parts["y"], parts["m"], parts["d"])
                except ValueError:
                    continue
                needs_century = True
                continue
            parts["y"] = start + (parts["y"] - start % 100) % 100
        try:
            candidates.add(date(parts["y"], parts["m"], parts["d"]))
            matched.append(name)
        except ValueError:
            continue
    options = tuple(sorted(candidates))
    if needs_century:
        return result(
            "ambiguous",
            "two_digit_year_window_required",
            candidates=options,
            matched_formats=tuple(matched),
        )
    if len(options) > 1:
        return result(
            "ambiguous",
            "multiple_date_interpretations",
            candidates=options,
            matched_formats=tuple(matched),
        )
    if len(options) == 1:
        return result(
            "valid", "parsed_date", options[0], candidates=options, matched_formats=tuple(matched)
        )
    if timestamp_blocked:
        return result("unsupported", "timestamp_requires_policy")
    return result("invalid", "invalid_calendar_date" if syntax_matched else "format_mismatch")
