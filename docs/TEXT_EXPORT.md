# Export reviewed text results

Phase 6 adds **Clean text → Export reviewed result...** for saved Excel data sets.
It writes a separate `.xlsx` containing the complete selection, approved text
changes and their evidence. It requires Windows and desktop Microsoft Excel.
Inspection, text review and recipe creation still work without desktop Excel.

## Export a completed result

1. Save the full data set and define the relevant columns. In **Clean text**, preview,
   choose and apply the intended changes, or complete every step of a recipe run.
2. Close the recipe library if open, then choose **Export reviewed result...**.
   Review the approved revision and output
   representation. Pending preview choices, rule drafts and intermediate recipe
   approvals are not included.
3. For text-only output, leave date inclusion unchecked. To compose dates, choose
   **Choose saved date run...**, select a completed run from `.artifacts/date-runs/`,
   review its identity and data-set description, then explicitly select **Include**.
   Loading a date run never selects inclusion automatically.
4. Choose **Export workbook...** and a new filename. Existing files and sources
   cannot be overwritten. Wait for the validated-export confirmation.
5. Optionally use **Open output in Excel**. Explicit exports remain after Exit;
   session working copies, mappings and transformation/date runs are cleared.

The writer opens a new workbook in a hidden, job-owned Excel process. It never opens
the original or intake workbook in Excel. Calculation, events and source macros are
disabled for writing. Cancellation, timeout or failure stops owned processes and
removes incomplete output. The application waits for worker cleanup during Exit.

## Output workbook

| Sheet | Meaning |
| --- | --- |
| Loan Tape | Entire selected range, including title/header rows, hidden source rows, unmapped columns and trailing blanks. Only approved text values and explicitly included valid date interpretations replace source tokens. |
| Summary | Source/revision identities, selection dimensions, mapped-cell count, approved step decisions, final text differences, included date count and writer/version evidence. |
| Steps | Ordered operations, engine versions, approval counts, reviewer, reason, readable UTC decision time and recipe attribution. |
| Cell Decisions | Every mapped-cell outcome in every step, including rejected proposals and intermediate approved values. |
| Source Evidence | Every selected source cell, storage kind/presence, exact raw/token/formula/format evidence, output address/value and applied origin. |
| Audit | Complete transformation history, original mapped evidence, rule/configuration snapshots, approvals and recipe bindings. An included date run retains its full analysis, dictionary, profile, calendar, finding and pair evidence. |
| Date Results / Date Findings | Included only when composing a date run; valid, unresolved and flagged dates remain visible. |

Long JSON evidence is split into numbered chunks without truncation. Join the final
column for each record in part order to reconstruct its exact JSON. Raw canonical
timestamps remain in JSON for replay; Steps displays readable UTC. Recipe attribution
retains executed operations and binding evidence, so the saved recipe library need
not remain available to inspect the exported history.

## Representation and preservation

This is a new values-only workbook. Source tokens, including numeric tokens and long
identifiers, are written as literal text. Included standardized dates are ISO
`YYYY-MM-DD` text. This avoids implicit Excel date guessing, lost leading zeros and
incidental numeric rounding. Numeric normalization and numeric Excel output types
are outside this phase; consumers must choose conversions explicitly.

Source formulas are literal expressions; their attributes and cached tokens remain
in Source Evidence. Formula-like replacements, leading apostrophes and error strings
remain literal. Blank and empty cells can look identical in Loan Tape; original
presence, raw values, kinds and mapped missingness remain in Source Evidence/Audit.

All selected rows are included regardless of source visibility. Original styles,
hidden-row settings, macros, connections and links are not copied. No rows are
merged or deleted, and identities are not inferred. Originals and intake bytes stay
unchanged. Existing standalone date exports retain their prior behavior and do not
automatically include text revisions.

## Composition and failure boundaries

A date run must use the same source hash, saved data-set ID/name, sheet, range and
header convention. Every date evidence cell must equal newly read original evidence.
Its dictionary snapshots must still be active. Overlapping column definitions must
agree on field identity, date formats, short-year window and missing tokens. A date
workflow's explicit mapping can supply a previously unmapped date column, but cannot
override a conflicting text/identifier/category definition.

Only valid date interpretations are applied. Unresolved dates remain literal, with
findings retained. Text and date changes to the same cell are rejected; unrelated
sources, altered runs, stale mappings and changed dictionaries are not composed by
guessing. Original-source date analyses have no text parent, so composition is limited
to compatible independent columns over the same original evidence.

The service replays approved history, checks complete recipe chains and rereads
source evidence before writing. It validates every saved cell and literal type,
dimensions and sheet order, and rejects formulas, error cells, macros and external
links. Source/mapping/date-run guards and saved-file checks run around publication.
A target created by another process after preflight is preserved. Cancellation cannot
undo a successfully completed export after its worker has finished.

## Limits and validation

- At most 200,000 cells in the complete range, including unmapped cells.
- At most 256 MiB of serialized payload or output workbook.
- At most 1,048,576 rows per output sheet. Long histories can reach the decision-sheet
  or evidence limit before the input limit.
- Literal values must fit 32,766 UTF-16 code units and 253 line feeds. Unsupported
  values fail before writing; nothing is truncated.
- Source formulas without literal expressions, unsupported cells, merged evidence
  or malformed source structures fail clearly.

These are safety bounds, not measured capacity promises. Exports contain original
selected data and audit history; retain them according to the data owner's requirements.
Generated exports stay outside Git and packages.

`check.bat` covers payloads, composition, stale inputs, malformed outputs, limits,
publication races, cancellation, native controls and installed-wheel payload replay.
For actual Excel writing, cancellation/timeout and owned process shutdown:

```powershell
.\check.bat --excel-smoke
```

That option runs the writer from the isolated installed wheel. To retain a synthetic
example separately:

```powershell
.\dev.bat python scripts/smoke_text_export.py --output .artifacts/reviewed-text-example.xlsx
```

Local checks do not publish a release or establish hosted CI/Linux success.

Validation on 19 October 2026 UTC: Windows `check.bat --excel-smoke` passed **830
tests**, formatting, lint, strict types, dependency/lock checks, source/wheel builds
and all installed-wheel smoke tests using Python 3.12.14. The installed wheel used
xlwings 0.37.4 with desktop Excel for a composed recipe/date export, exact saved-cell
verification, cancellation after Excel startup, timeout and owned process shutdown.
No Excel processes remained afterward. A separate synthetic sample is retained at
`.artifacts/phase6-reviewed-text.xlsx`. Hosted CI, Linux, real portfolios and capacity
benchmarks remain unverified. No host configuration was changed.
