# Date definitions and parsing foundation

Steps 1 and 2 of the date workflow are a standalone Python backend. They add the
`loan.dates` field dictionary, explicit parsing profiles, immutable results, and a
read-only `.xlsx`/`.xlsm` date-evidence reader. Existing desktop column checks keep
their current behavior. Steps 3-8 add the date-analysis engine, SIFMA calendar screening, self-contained reproducible session runs, explicit desktop mappings, xlwings review
exports, and end-to-end validation described in [DATE_ANALYSIS.md](DATE_ANALYSIS.md).

## Separate meaning from representation

Choose a definition from [Date fields](DATE_FIELDS.md) only after confirming the
source meaning. A `DateProfile` describes how to interpret a representation; it
does not identify a field, activate a dictionary, impose required-value rules or
decide whether a loan date is valid. No pack contract extension is needed.

Profiles use format version 1, an ID, semantic version and deterministic content
fingerprint. `to_json()` / `from_json()` round-trip the complete policy, rejecting
unknown keys, duplicate keys, invalid types and unsupported versions. The caller
binds these profiles explicitly through `DateBinding`; the analysis engine retains
the complete policy in each saved run.

| Setting | Behavior |
| --- | --- |
| `text_formats` | Explicit allowlist: `YYYY-MM-DD`, `M/D/YYYY`, `D/M/YYYY`, `M/D/YY`, `D/M/YY`, `ISO_DATETIME`. Slash formats accept one or two month/day digits. ISO dates require padded month/day. An empty allowlist disables text-date interpretation. |
| `two_digit_year_start` | Optional first year of an explicit 100-year window. For example 2000 means 2000–2099; 1970 means 1970–2069. Without it, a plausible two-digit-year date remains ambiguous. No system pivot or today's year is used. |
| `missing_tokens` | Exact, case-sensitive textual tokens. No default `NA`, zero, sentinel date or numeric missing code is assumed. Presence and blank permissions belong to later validation. |
| `whitespace` | Default `reject`; explicit `strip` changes only the interpretation input and records a note. Raw text is retained. |
| `timestamps` | Default `reject`; `date_component` selects the calendar date as written, records a note, and retains the original timestamp/fraction. No timezone conversion or time rounding. |
| `numeric_dates` | Default `reject`; `excel_serial` explicitly permits numeric serial interpretation using the source workbook's date system. Textual numbers are never silently treated as serials. |

ISO timestamps require `YYYY-MM-DDTHH:MM:SS`, optional 1–6 fractional second
digits, and optional `Z` or `±HH:MM`. Week dates, compact dates, named months,
localized month names, timezone names and durations are unsupported. A timestamp
inside an OOXML date cell still requires the timestamp policy, even at midnight.
An explicit date-only OOXML value is parsed as ISO independent of text settings.

When multiple enabled formats yield distinct dates, return all candidate dates
with `ambiguous` and no selected date. If their results coincide, the date is
unambiguous under the profile. Invalid calendar dates are never rolled forward.

## Evidence and outcomes

`DateEvidence` retains source SHA-256, original row/column and optional worksheet,
source kind, raw representation, stored OOXML type/token, number format, workbook
date system, cell presence, and formula text/attributes when present. XML text is
decoded, not an Excel-rendered display string; preserved source bytes remain the
authority for exact file representation. A shared-string token remains its index,
while `raw` contains the resolved text. Rich-text runs concatenate in order;
phonetic annotations are excluded. Unknown built-in number formats remain `None`.

`parse_date(evidence, profile)` returns the original evidence and complete profile,
parser version, status, reason code, optional parsed date, candidate dates, matched
formats, missing kind and transformation notes. Statuses are `valid`, `ambiguous`,
`invalid`, `missing`, `unsupported`, and `source_error`. Valid means successfully
interpreted under the profile, not financially validated. Missing kinds distinguish
absent cells, stored blanks, empty text, whitespace-only text and declared tokens.
Zero and undeclared tokens remain values, not blanks.

Formulas are unsupported for interpretation, even if they have a cached value.
Their saved token and formula metadata remain evidence; nothing is calculated.
Stored Excel errors produce `source_error`. Unreadable/malformed workbook evidence
raises `InspectionError`; it cannot masquerade as a valid, empty or completed run.

## Excel date evidence

`read_excel_date_columns(path, selection, columns)` accepts an existing
`SourceSelection` and a nonempty tuple of distinct original Excel column numbers.
It opens the package metadata once and streams the selected worksheet once for the
complete requested set, rather than rescanning it per column. The compatibility
wrapper `read_excel_date_column(path, selection, column)` returns one column through
the same reader. Worksheet XML is read directly so invalid serials are not first
converted by a general workbook reader. The reader includes hidden cells, gaps and
blank tails, excludes an explicitly designated header and prior rows, and does not
trust stored worksheet dimensions. It publishes immutable `DateColumnEvidence`
objects only after the entire selected sheet parses and the file identity is verified
before and after. A malformed requested column, cancellation, or another failure
returns no results for the batch. No Excel process, macro, formula or external link
is executed.

Limits fail explicitly: 100,000 data rows by default (caller may set `max_rows` up
to Excel's row limit), 64 MiB per uncompressed package part, and 256 MiB per package.
Selected merged cells are rejected because their row meaning is not established.
Duplicate cells/rows, invalid style/string references, unsupported XML namespaces,
malformed date-system metadata and ambiguous sheet relationships fail clearly.
Legacy `.xls`/`.xlsb`, full CSV/XML extraction and formula interpretation are outside
this reader. A caller can already supply decoded CSV text to the shared scalar
parser with its source identity and record/field positions.

The 1900 date system accepts serials from 1, rejects fictitious serial day 60
(including its fractional values), and treats day 0 as lacking a calendar date.
The 1904 system starts at serial 0 = 1904-01-01. Negative serials are outside this
backend's supported serial range; historical dates remain supported as explicit
text. Serial fractions require a timestamp policy. Arithmetic uses the original
decimal token without conversion to floating point or rounding to a neighboring
day. Dates outside Python's years 1–9999 are rejected. Gregorian century leap-year
rules apply, including 2100.

These choices were checked against Microsoft's [date systems documentation](https://support.microsoft.com/en-US/Excel/date-systems-in-excel),
[two-digit-year documentation](https://support.microsoft.com/en-us/excel/change-the-date-system-format-or-two-digit-year-interpretation),
and [1900 leap-year explanation](https://learn.microsoft.com/en-us/troubleshoot/microsoft-365-apps/excel/wrongly-assumes-1900-is-leap-year)
on 2026-09-17. Window selection and rejection policies are explicit Loan Tape
choices; they do not inherit Excel's machine-dependent interpretation settings.

## Example

```python
from loan_tape.date_parser import DateEvidence, DateProfile, DateSource, parse_date

# A real caller supplies the preserved source's SHA-256, record and column.
source = DateSource("a" * 64, row=2, column=1, sheet="Dates")
profile = DateProfile(
    id="us-date-source",
    text_formats=("M/D/YY", "M/D/YYYY", "YYYY-MM-DD"),
    two_digit_year_start=2000,
    numeric_dates="excel_serial",
)
result = parse_date(DateEvidence(source, "text", "1/8/21"), profile)
assert result.parsed_date.isoformat() == "2021-01-08"
assert result.evidence.raw == "1/8/21"
assert DateProfile.from_json(profile.to_json()) == profile
```

The year window in this example is an explicit assumption, not a global default.
See `tests/test_dates.py` and `tests/test_date_reader.py` for synthetic regression
cases. `scripts/smoke_dates.py` exercises the built, installed package; run
`check.bat` for formatting, lint, types, tests, packaging and installed smoke checks.
