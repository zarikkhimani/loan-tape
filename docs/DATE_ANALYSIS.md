# Date analysis, calendar screening and saved runs

The complete eight-step date workflow is implemented. The import/standardization
service, red-flag analysis, calendar and saved-run services build on the definitions
and parser in [DATES.md](DATES.md). The desktop keeps mapping and interpretation in a
first phase and review policies in a separate downstream phase. Excel export publishes
the complete saved data set with successful date interpretations applied, plus the
verified saved review result, through an isolated xlwings process.

## Analysis inputs and scope

`standardize_excel_dates` reads every mapped date column in one complete worksheet
scan of a saved `.xlsx`/`.xlsm` selection, including hidden rows, gaps and blank tails.
Package metadata, shared strings, styles and the worksheet are not reopened per
mapping. The header and preceding title rows are excluded only when explicitly
designated. It returns a `DateStandardization` handoff containing the complete source
evidence and parser outcomes. This phase has no
required-value, range, pair, reference-date, calendar, severity, or finding settings.
`standardize_dates` accepts the same evidence without accessing a workbook.

Original source hashes, worksheet names, row and column positions stay attached to
every cell. Read failures, changed sources, cancellation, incomplete or reordered
evidence fail without returning a completed handoff. No Excel process or source
calculation runs. `analyze_standardized_dates` validates the handoff version and exact
mapping identity, then recomputes the analysis from its retained evidence while
applying the separately supplied red-flag policy. It does not reread the workbook.
Changing a mapping or interpretation profile requires a new standardization. There is
no combined import-and-review entry point.

Each `DateMapping` explicitly selects an original column, a fully qualified date field
from the supplied catalog, and a parsing profile. Aliases never map columns
automatically. The dictionary field must have type `date`. A later `DateBinding`
must retain that exact column, field, and profile while adding only review policy.
Only the used packs are embedded in the saved review result, with their exact four
source files and fingerprints.

Optional binding settings are value requirements, earliest/latest review bounds,
an explicit comparison against a fixed reference date, and a calendar policy.
An unspecified value requirement uses the field's `blank_allowed=False` metadata;
field presence (`required`) is a separate concept. A supplied `require_value`
overrides blank metadata and is retained beside the effective requirement.
No missing-value tokens, maturity interpretation, loan tenor, or default term
length are inferred from a dictionary label.

The reference date is mandatory and fixed for the run. A reporting date may be
recorded separately; it does not silently replace the reference date. Text dates
and Excel serials still require the explicit profiles described in DATES.md.

## Results and findings

Each column retains every parser result, including unresolved cells, candidates,
missingness kinds and interpretation notes. Its summary contains:

- Counts for all six parser outcomes, valid/unresolved totals and missing kinds.
- First/last interpreted dates, original storage kinds, number formats and
  matched formats. These are observed representations, not Excel display text.
- Year, month, day-of-month and weekday frequencies, plus month-end counts.
- Repeated raw values and repeated interpreted dates, with all source rows.
- Exact rational median and inclusive, linearly interpolated quartiles on date
  ordinals. With at least four interpreted dates, 1.5-IQR fences identify review
  candidates. These heuristics can flag legitimate dates, especially when IQR is zero.

Raw duplicate keys contain kind, raw value and workbook date system. Different
number formats are reported separately. A shared date does not identify a
duplicate loan. Mixed representations and repeated dates/pairs are informational.
Frequency tables support concentration review; there is no automatic claim that
a concentrated or unsorted date population is defective.

An explicit `DatePair(start_column, end_column)` compares dates only on the same
original row. It records elapsed **calendar days**, negative/zero/positive counts,
optional minimum/maximum review bounds, distribution statistics and repeated
pairs. Reversed dates violate the selected ordering rule; equal dates are allowed
unless `allow_equal=False`. Uninterpreted pairs are individually retained as
`not_evaluable` and excluded from duration statistics with reconciled counts.
Elapsed days are not contractual tenor, an accrual day count, or a repayment schedule.

Findings have a rule ID/version, severity, original columns/rows, reason and
details. `error` identifies invalid source representations, stored source errors,
explicit missing-value/order violations, or confirmed business-day violations.
`review` identifies ambiguity, unsupported representations, distribution/bound
flags and uncertain calendar evidence. `info` records non-error observations.
Finding counts are distinct from affected-row counts; one row may have several
findings. A valid parse is not a loan-compliance conclusion. No dates are adjusted.

## SIFMA U.S. fixed-income calendar

The governing policy ships as [SIFMA_CALENDAR.md](../src/loan_tape/guidance/SIFMA_CALENDAR.md).
The package also contains `loan_tape/calendar_data/sifma_us_fixed_income.json`, a
versioned normalized schedule and source metadata verified on 2026-09-17. It contains
project-authored structure and links to SIFMA's public pages, not proprietary forms.

| Calendar ID | Complete published annual coverage | Purpose |
| --- | --- | --- |
| `us.sifma_fixed_income` | 2019–2027 | SIFMA U.S. recommendations for the fixed-income products in its stated scope |

`build_calendar(id)` defaults to a 1900–2126 review horizon. Weekdays and weekends
are calculated directly for the entire horizon. Published holiday coverage exists only
for 2019–2027; every other weekday has `business_day=None` and `holiday_coverage=unknown`.
No recurring holiday formula is used to backcast history or project future schedules.
A later year becomes known only when a credible SIFMA schedule is added to the bundled
resource. Callers can select a different bounded range or supply a validated custom
snapshot. The limits are 1,000 coverage years and 30,000 events per snapshot.

Actual and observed holiday dates, full closes, early closes, source references,
publication/verification dates, and assumptions remain distinct. A published full close
is non-business for this screen. An early close remains a business day and is recorded
as an event; SIFMA states that its early closes do not affect settlement closing time.
Published exceptions such as early-close-only Good Fridays are stored exactly instead
of being reconstructed from a general rule.

`CalendarBinding` records an activity and defaults to `reference_screening`. Weekend
and published full-close matches are review flags. Setting `require_business_day=True`
requires an explicit activity and agreement reference; only then can a certain match
produce an error. The engine records this assertion but cannot verify the agreement
text. Other financial-centre calendars, rate-reset/payment rules, date rolling,
business-day counting, and cash-flow schedules are not implemented.

## Saving and reproducing a run

`save_date_run(analysis, directory)` first replays and verifies the result, then
writes a new UUID-named JSON file. The envelope includes its creation time in UTC
and a SHA-256 content digest. Analysis content includes:

- Saved data-set identity, selection, source hash and all original date evidence.
- Explicit field mappings, complete profiles, thresholds and reference/reporting dates.
- Exact dictionary files, calendar snapshots and their fingerprints.
- Schema, parser, analysis and calendar engine versions, results and findings.

The temporary file is flushed before publication. An atomic hard link creates
the final name without replacing an existing file, then the temporary link is
removed. A filesystem without hard-link support fails explicitly. Cancellation
before publication and write/publication failures produce no completed run.
The size limit is 128 MiB. Saved evidence may contain private portfolio information.
The desktop uses `.artifacts/date-runs/` for current-session replay and removes that
folder on normal application exit. A Python API caller may choose another authorized
directory when deliberate retention is required; this is outside desktop reset scope.

`load_date_run(path)` checks strict JSON structure and the digest, reconstructs
and validates the retained policies/dictionaries/calendars, and recomputes the
analysis from retained evidence. It verifies the complete result, not just
self-reported totals. Current dictionary folders, calendar resources and the
original workbook are not required for replay. Editing them cannot rewrite the
saved run. `check_run_source(run, path)` separately reports `unchanged`, `changed`
or `missing`; filesystem read errors remain errors.

Replay requires compatible recorded engine/parser versions; unsupported versions
fail clearly and require the matching implementation or an explicit future
migration. A digest detects corruption and inconsistent edits, not authenticity:
someone able to rewrite an entire coherent artifact can recompute its checksum.

## Python example

```python
from datetime import date
from pathlib import Path

from loan_tape.date_analysis import (
    CalendarBinding,
    DateBinding,
    DatePair,
    analyze_standardized_dates,
)
from loan_tape.date_calendar import build_calendar
from loan_tape.date_parser import DateProfile
from loan_tape.date_standardization import DateMapping, standardize_excel_dates
from loan_tape.date_runs import load_date_run, save_date_run

# saved_table and catalog come from the existing saved-selection and pack services.
# Confirm column meanings and source date convention before constructing these bindings.
profile = DateProfile(
    text_formats=("M/D/YY",), two_digit_year_start=2000, numeric_dates="excel_serial"
)
calendar = build_calendar("us.sifma_fixed_income")
mappings = (
    DateMapping(1, "loan.dates:closing_date", profile),
    DateMapping(2, "loan.dates:current_maturity_date", profile),
)
standardized = standardize_excel_dates(
    Path("preserved-input.xlsx"),
    saved_table,
    mappings,
    catalog,
)
analysis = analyze_standardized_dates(
    standardized,
    (
        DateBinding(
            1,
            "loan.dates:closing_date",
            profile,
            calendar=CalendarBinding(calendar.id, "closing"),
        ),
        DateBinding(2, "loan.dates:current_maturity_date", profile),
    ),
    reference_date=date(2026, 9, 17),
    pairs=(DatePair(1, 2),),
    calendars=(calendar,),
)
saved = save_date_run(analysis, Path(".artifacts/date-runs"))
assert load_date_run(saved.path).analysis.fingerprint == analysis.fingerprint
```

Here the SIFMA calendar is a reference screen for closing dates, not an asserted
contractual requirement. Unpublished weekdays remain unknown, and applicability still
depends on the activity and governing agreement.

Analysis retains data in memory and permits at most 200,000 mapped cells; Excel
reading defaults to 100,000 rows. This workflow does not add full CSV/XML or legacy
XLS/XLSB extraction or source-value editing.

## Desktop review and Excel export

For a saved Excel data set, **Date workflow** opens a guided screen backed by the active
`loan.dates` snapshot. When that pack is inactive, the blocked screen identifies
the available local version and offers an explicit **Enable loan date definitions**
button. Activation pins the exact fingerprint in the default profile, preserves other
active packs, rebuilds the same window, and never changes the source workbook. Activation
or local-pack failures remain visible and retryable. In **1 Import & standardize**, the
user maps each source column to one of the four date meanings and selects accepted text
formats; header aliases never select a mapping. Missing tokens, whitespace/timestamp
handling, and a two-digit year window are interpretation settings. Completing this phase
reports interpreted and unresolved counts and explicitly states that no red flags ran.

**2 Red flags** is unavailable until standardization succeeds. It contains blank
requirements, bounds, the session reference date, reporting date, a same-row start/end
comparison, and separate calendar policies for each mapped field. It consumes the
prepared snapshot without reopening the workbook. If mapping or interpretation choices
change, the user must run Import & standardize again. **3 Findings** pages the saved
review output and supports source jumps and export.

The single calendar choice is **SIFMA U.S. fixed-income market**. It uses published
2019–2027 schedules; other weekdays remain unknown while weekends are still calculated.
A business-day error requires a named activity and agreement reference; otherwise a
weekend or published full close is a review item. The screen pages every finding, retains details, and can jump to the first affected
source cell. Each successful desktop run is saved under `.artifacts/date-runs/` and
replayed during the current session; normal application exit removes it. Use the
validated refined-loan-tape export when a durable desktop deliverable is required.

**Export refined loan tape** accepts only a new `.xlsx` path. The exporter first reads
every row and column in the exact saved data-set range from the unchanged source.
Successfully interpreted mapped dates become typed Excel dates; ambiguous, invalid,
missing, unsupported, source-error, and unmapped cells retain their original literal
values. `date_export.py` then starts a separate hidden Excel instance and a job-owned
Python worker; the xlwings writer creates `Loan Tape`, `Summary`, `Findings`,
`Date Results`, `Pair Results`, and `Audit`.
The workbook follows a restrained institutional model style: Arial 10 body text,
navy table headers, dark-green section bands, frozen headings, typed date columns,
and review-status highlighting. The source workbook is never opened by the writer.
The `Loan Tape` sheet preserves the saved range's row and column order and designated
header. Source text is literal, parsed dates
are typed dates, and the workbook contains no formulas, macros, links, or connections.
Raw storage/token/formula evidence, coordinates, policies, dictionaries, calendars,
source URLs, identities, fingerprints, and reconciliation remain reviewable.

The output is staged and validated before an atomic no-replacement publication, then
validated again. Source hashes are checked before and after. There is no silent writer
fallback: unavailable desktop Excel, timeout, cancellation, source change, invalid
output, or an existing target fails without a completed workbook. Export is Windows/
desktop-Excel only; analysis and replay remain portable.

Run `check.bat` for project validation. Synthetic regression tests cover source
lineage, every-row reconciliation, policy severity, calendar distinctions,
century boundaries, corruption and interrupted publication. The installed-wheel
smoke test executes workbook evidence -> analysis -> calendar -> save -> replay
and checks unchanged source bytes. Release checks require exact copies of both
the SIFMA guidance and factual calendar resource in the wheel and source archive.
The opt-in `scripts/smoke_date_export.py` runs source -> analysis -> saved run ->
xlwings workbook -> validation on Windows with desktop Excel.
