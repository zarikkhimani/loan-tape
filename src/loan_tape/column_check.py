"""Explicit, read-only column rules with complete, paged source-cell findings."""

from __future__ import annotations

import re
import sqlite3
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from threading import Event

from loan_tape.column_profile import (
    MISSING_KINDS,
    ColumnExample,
    ColumnProfile,
    ColumnTable,
    inspect_column,
    limit_xml_storage,
)
from loan_tape.inspection import InspectionError
from loan_tape.session import AnalysisSession
from loan_tape.xml_selection import SavedXmlTable

EXPECTED_TYPES = ("Identifier", "Text", "Number", "Date")
DATE_FORMATS = {
    "Excel dates only": None,
    "YYYY-MM-DD": (r"[0-9]{4}-[0-9]{2}-[0-9]{2}", "%Y-%m-%d"),
    "MM/DD/YYYY": (r"[0-9]{2}/[0-9]{2}/[0-9]{4}", "%m/%d/%Y"),
    "DD/MM/YYYY": (r"[0-9]{2}/[0-9]{2}/[0-9]{4}", "%d/%m/%Y"),
}
FINDINGS_PAGE_SIZE = 20
NUMBER_FORMATS = ("Stored numbers only", "Plain decimal text")
PLAIN_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)")


@dataclass(frozen=True)
class ColumnRules:
    expected_type: str
    required: bool = True
    date_format: str = "Excel dates only"
    min_year: int | None = None
    max_year: int | None = None
    flag_before_reference: bool = False
    number_format: str = "Stored numbers only"

    def __post_init__(self) -> None:
        if self.number_format not in NUMBER_FORMATS:
            raise InspectionError("Choose a supported number format.")
        if self.expected_type != "Number" and self.number_format != "Stored numbers only":
            raise InspectionError("Number settings apply only to a Number column.")
        if self.expected_type not in EXPECTED_TYPES:
            raise InspectionError("Choose Identifier, Text, Number, or Date.")
        if self.date_format not in DATE_FORMATS:
            raise InspectionError("Choose a supported text date format.")
        for year in (self.min_year, self.max_year):
            if year is not None and (type(year) is not int or not 1 <= year <= 9999):
                raise InspectionError("Year limits must be whole numbers from 1 to 9999.")
        if self.min_year is not None and self.max_year is not None:
            if self.min_year > self.max_year:
                raise InspectionError("The earliest year must not exceed the latest year.")
        if self.expected_type != "Date" and (
            self.date_format != "Excel dates only"
            or self.min_year is not None
            or self.max_year is not None
            or self.flag_before_reference
        ):
            raise InspectionError("Date settings apply only to a Date column.")

    @property
    def description(self) -> str:
        parts = [self.expected_type, "Blanks flagged" if self.required else "Blanks allowed"]
        if self.expected_type == "Number":
            parts.append(self.number_format)
        if self.expected_type == "Date":
            parts.append(self.date_format)
            if self.min_year is not None:
                parts.append(f"Earliest year: {self.min_year}")
            if self.max_year is not None:
                parts.append(f"Latest year: {self.max_year}")
            if self.flag_before_reference:
                parts.append("Flag dates before the session reference date")
        return " · ".join(parts)


def _date_value(cell: ColumnExample, rules: ColumnRules) -> date | None:
    if cell.kind == "Date/time":
        # Stored calendar dates are ISO text; times/durations have no calendar day.
        try:
            return datetime.fromisoformat(cell.text).date()
        except ValueError:
            return None
    format_spec = DATE_FORMATS[rules.date_format]
    if cell.kind != "Text" or format_spec is None:
        return None
    pattern, format_string = format_spec
    if not re.fullmatch(pattern, cell.text):
        return None
    try:
        return datetime.strptime(cell.text, format_string).date()
    except ValueError:
        return None


def _is_blank(cell: ColumnExample) -> bool:
    return cell.kind in MISSING_KINDS or (cell.kind == "Text" and cell.text.isspace())


def check_value(cell: ColumnExample, rules: ColumnRules, reference: date) -> tuple[str, ...]:
    """Describe findings without converting, repairing, or evaluating source data."""
    if _is_blank(cell):
        if not rules.required:
            return ()
        label = "Whitespace-only text" if cell.kind == "Text" else cell.kind
        return (f"{label}: a value is required.",)
    if cell.kind == "Formula":
        return ("Formula not checked against the expected type; it was not evaluated.",)
    if cell.kind == "Excel error":
        return ("Stored Excel error: review the source cell.",)
    reasons: list[str] = []
    if cell.kind == "Text" and cell.text != cell.text.strip():
        reasons.append("Leading or trailing whitespace; original text retained.")
    if rules.expected_type in {"Identifier", "Text"}:
        if cell.kind != "Text":
            reasons.append(
                "Identifier stored as a non-text value; verify digits and formatting."
                if rules.expected_type == "Identifier"
                else f"Expected text; stored type is {cell.kind}."
            )
    elif rules.expected_type == "Number":
        if rules.number_format == "Plain decimal text":
            if cell.kind != "Text" or not PLAIN_DECIMAL.fullmatch(cell.text):
                reasons.append(
                    "Expected plain decimal text: optional sign and decimal point; no grouping, currency, percent, exponent, or inferred missing token."
                )
        elif cell.kind != "Number":
            reasons.append(f"Expected a stored number; found {cell.kind}. No conversion attempted.")
        elif not Decimal(cell.text).is_finite():
            reasons.append("Number is not finite.")
    else:
        parsed = _date_value(cell, rules)
        if parsed is None:
            reasons.append(
                "Expected a stored calendar date. Choose a text date format to check text dates."
                if rules.date_format == "Excel dates only"
                else f"Expected a calendar date or text matching {rules.date_format}; no date inferred."
            )
        else:
            if rules.min_year is not None and parsed.year < rules.min_year:
                reasons.append(f"Year {parsed.year} is before the earliest year {rules.min_year}.")
            if rules.max_year is not None and parsed.year > rules.max_year:
                reasons.append(f"Year {parsed.year} is after the latest year {rules.max_year}.")
            if rules.flag_before_reference and parsed < reference:
                reasons.append(
                    f"Date {parsed.isoformat()} is before reference date {reference.isoformat()}."
                )
    return tuple(reasons)


@dataclass(frozen=True)
class ColumnFinding:
    cell: ColumnExample
    reason: str


@dataclass
class ColumnCheck:
    profile: ColumnProfile
    rules: ColumnRules
    finding_count: int
    allowed_blanks: int
    _temporary: tempfile.TemporaryDirectory[str]
    _closed: bool = False

    def page(self, offset: int = 0) -> tuple[ColumnFinding, ...]:
        if self._closed:
            raise InspectionError("Column check results are closed. Run the check again.")
        if type(offset) is not int or offset < 0:
            raise InspectionError("Finding offset must be a non-negative whole number.")
        db = sqlite3.connect(Path(self._temporary.name) / "findings.sqlite")
        try:
            return tuple(
                ColumnFinding(
                    ColumnExample(row, kind, text, fmt, source_path=source, presence=presence),
                    reason,
                )
                for row, kind, text, fmt, reason, source, presence in db.execute(
                    "SELECT row, kind, text, format, reason, source_path, presence FROM findings "
                    "WHERE id > ? ORDER BY id LIMIT ?",
                    (offset, FINDINGS_PAGE_SIZE),
                )
            )
        finally:
            db.close()

    def close(self) -> None:
        self._temporary.cleanup()
        self._closed = True


def check_column(
    path: Path,
    table: ColumnTable,
    column: int,
    session: AnalysisSession,
    rules: ColumnRules,
    *,
    cancelled: Event | None = None,
    progress: Callable[[str], None] = lambda message: None,
) -> ColumnCheck:
    """Retain every flagged row on temporary disk; caller closes completed results."""
    if isinstance(table, SavedXmlTable):
        if rules.expected_type == "Number" and rules.number_format != "Plain decimal text":
            raise InspectionError("Choose Plain decimal text to check XML numbers.")
        if rules.expected_type == "Date" and rules.date_format == "Excel dates only":
            raise InspectionError("Choose an explicit text date format to check XML dates.")
    work = Path.cwd() / ".artifacts" / "column-checks"
    work.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix="check-", dir=work)
    try:
        db = sqlite3.connect(Path(temporary.name) / "findings.sqlite")
        try:
            if isinstance(table, SavedXmlTable):
                limit_xml_storage(db)
            db.execute("PRAGMA cache_size = -2048")
            db.execute(
                "CREATE TABLE findings (id INTEGER PRIMARY KEY, row INTEGER, "
                "kind TEXT, text TEXT, format TEXT, reason TEXT, source_path TEXT, presence TEXT)"
            )
            findings = allowed_blanks = 0

            def visit(cell: ColumnExample) -> None:
                nonlocal findings, allowed_blanks
                if not rules.required and _is_blank(cell):
                    allowed_blanks += 1
                reasons = check_value(cell, rules, session.reference_date)
                if reasons:
                    findings += 1
                    db.execute(
                        "INSERT INTO findings VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            findings,
                            cell.row,
                            cell.kind,
                            cell.text,
                            cell.number_format,
                            "\n".join(reasons),
                            cell.source_path,
                            cell.presence,
                        ),
                    )

            profile = inspect_column(
                path, table, column, session, cancelled=cancelled, progress=progress, on_cell=visit
            )
            db.commit()
        finally:
            db.close()
        return ColumnCheck(profile, rules, findings, allowed_blanks, temporary)
    except sqlite3.Error as error:
        temporary.cleanup()
        if isinstance(table, SavedXmlTable):
            raise InspectionError(
                f"XML check storage failed; no complete result (512 MiB limit per database). {error}"
            ) from error
        raise
    except BaseException:
        temporary.cleanup()
        raise
