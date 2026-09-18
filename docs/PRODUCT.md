# Product definition

## Purpose

Build a local, reviewable workflow for analysts working with CLO collateral, broadly syndicated loans, middle-market/private-credit portfolios, and BDC schedules of investments.

The intended outputs are normalized position data with full source traceability and empirical evidence about the coverage of a versioned data-quality taxonomy.

## Input scope

The application starts with supplied CSV files, XML data files, or Excel workbooks. PDF extraction and conversion functionality already exists separately and will be integrated in a later, separate phase. PDF/OCR processing and scanned-document handling remain outside the current implementation scope. Incoming spreadsheets may still contain structural, semantic, or upstream conversion errors; their values and layouts require inspection.

File intake currently accepts .csv, .xml, .xlsx, .xls, .xlsm, and .xlsb by filename extension and preserves their bytes. Intake itself does not inspect content or establish workbook validity. Files labels the selected format's capability before opening: full workbook review for .xlsx/.xlsm, XML review and XSD validation for .xml, preview-only behavior for CSV, and preservation only for .xls/.xlsb. The .xls and .xlsb preview action stays disabled because those readers remain unimplemented.

## Current file intake

A native desktop window supports drag and drop or Add file, one file at a time (100 MiB maximum). It saves an unchanged session working copy with a source manifest, lists copies added during the current session, and lets the user copy either the original absolute path or the saved path. Duplicate filenames remain separate. Earlier browser records remain readable until normal Exit resets them. A Loan Tape desktop shortcut launches without a terminal and keeps runtime files in the project. Exit or closing the main window cancels readers, closes child dialogs, lets an active copy finish, and removes intake copies plus source-linked session state after owned workers stop. The main window stays open with an actionable error if a working copy is locked. Original sources, explicit exports, dictionary packs, unrelated artifacts, and existing user Excel sessions are not removed or terminated.

Each desktop launch records a fixed local reference date and startup timestamp from the computer, preserving its UTC offset and equivalent UTC time. The main window and all file previews share that session. Reopening a preview does not reset its date; a new application launch creates a new record. Check column uses this date for optional past-date flags and accepts explicit year limits. It does not change workbook dates, treat the current date as the portfolio reporting date, or infer maturity meaning.

The Open file action scans every worksheet's physical cells to discover stored data anywhere in .xlsx/.xlsm workbooks, including hidden sheets/rows/columns and locations beyond incorrect used-range metadata. An overview lists sheets, visibility, bounds, dimensions, counts, and suggested areas separated by blank row/column bands. Alongside that complete inventory, the app suggests data set ranges and likely header rows from structure, using explicit Excel table definitions when present. These are editable layout suggestions; they do not establish what the loan fields mean. Unsupported or failed tabs remain visible and make coverage explicitly incomplete.

Users can preview all data on a sheet or an arbitrary cell range, navigate row/column pages, and jump to source cells. The 20-row/10-column page size never limits workbook discovery or the saved selection. Users can save multiple named data sets, each with a complete worksheet range and optional original header row, bound to the workbook's content hash and restored when the working copy is reopened during the same application session. Data sets may sit beside or below one another on a sheet. Select a preview row and use it as headers, or enter its source row number; save and revise each data set independently. The preview shows these labels alongside Excel column letters even when the header row is off-page. Duplicate/blank headers and the source header row remain intact. Removing a data set removes only its local definition; normal application exit removes all file-session definitions. Earlier single-range settings remain compatible until that reset. The first view previews the largest suggested data set on the first populated readable sheet, falling back to all stored data bounds when no data set is identified. Suggestions remain unsaved drafts; existing saved definitions retain priority. No analysis runs automatically.

CSV retains its bounded initial preview and separator/encoding controls. Excel shows stored values and saved formula results (formula text when no cached value exists); formatting is not reproduced and formulas are never recalculated. Saved data sets support an Inspect column action over every selected data row, with counts by stored type, blanks/empty text, zeroes, repetition counts, and source-linked examples. Headers and earlier title rows are excluded only when explicitly designated; without a header all range rows are included. The explicit date workflow is the only implemented complete-data-set financial-field interpretation, red-flag, and export path. Its Excel output contains the complete saved data-set range in source column order, replaces only successfully interpreted mapped dates, retains unresolved values literally, and adds review/audit sheets. A separate Phase 1 rate backend defines fields and parses individual values but does not yet map or analyze a pool. Broader normalization, validation, and export remain future work. Location discovery does not establish correctness of every source value or satisfy the later raw-evidence processing milestones.

On Windows with installed desktop Excel, inspection also runs xlwings alongside openpyxl and offers a reader selector and preview-only value comparison. Differences are for review, never automatic correction. Only plain data workbooks qualify for Excel comparison: formulas, named definitions, macros, links, connections, tables, and unrecognized package features are explicitly skipped before Excel starts. The openpyxl preview remains available. This workflow runs locally in Python without an LLM or add-in.

The preview also has an Open in Excel button that launches the saved file directly in installed desktop Excel. This explicit manual action uses normal Excel behavior and is separate from the read-only inspection engines. Close that workbook before exiting Loan Tape; a lock that prevents session reset keeps Loan Tape open with a visible error. Loan Tape does not terminate the user's Excel window.

XML uses this same preview window and grid. A single repeated record group opens automatically; if several groups are found, choose **Record group** above the grid. With no repetitions, the document root is one record. Element paths and attributes become column labels, and Cell details shows the source path and whether a value is present, absent, empty, or explicitly nil. Namespaces remain distinct, with aliases explained below the grid. Values are decoded XML text, without numeric/date conversion; original XML bytes remain preserved.

XML stage 2 reaches every record and field in a supported group through pages of up to 20 records and 10 fields. Use the **Records** and **Fields** arrows, **Start**, **End**, or **Go to record / field**. Record numbers count occurrences in the selected group, and field numbers follow the displayed column order; they are not XML line numbers. Full group dimensions and the current page remain visible. Fields first appearing late in the document are included, with absent values kept distinct on earlier rows.

Give the group a name and select **Save data set** to save the complete group, including records and fields outside the current page. Use **Data set** to switch, **Edit setup** to rename and save, **New** to start another setup, or **Remove** to delete only its local definition. Each saved group remembers its last successfully viewed page during the application session. Reopening the working copy in that session restores the last active data set against the exact file content hash. Edited names are protected on close or group changes. Setup metadata lives separately under `.artifacts/xml-selections/` until normal application exit; source XML and workbook settings remain unchanged. Changed files cannot reuse old selections, and corrupt or unwritable settings are reported visibly.

The complete file is streamed on each page request before publishing a result, so malformed trailing content fails clearly and later fields/repetitions are detected. Repeated child groups and mixed text/element content are explicitly unsupported within a selected record; choose a narrower group where available. Limits on size, depth, nodes, paths, attributes, values, and preview memory still apply and fail clearly. DTDs/entities are blocked; schema hints and stylesheets are not fetched or executed. XML data sets select whole record groups and support full-column Inspect and Check. **Validate XSD…** explicitly validates the complete document against a user-selected local XSD; XML export and Open in Excel remain outside the implemented XML stages.

## Files presentation

Files uses a warm white surface, a near-black hunter-green Add file button, quiet workspace tabs, and a spacious document list. A concise selected-file label identifies the available review level before the action. Open file, Enter, or double-click opens a supported saved copy; .xls/.xlsb keep their bytes and details available while preview remains disabled, and keyboard/double-click attempts show conversion guidance without replacing an existing preview. Duplicate filenames retain their independent identities. Details reveals the selected original/saved paths and copy controls in place. Refresh, Dictionary packs, Exit, and the session reference date remain available. Empty, saving, error, disabled, and keyboard-focus states stay explicit. The shared style layer retains native controls and adds no runtime dependencies. Preview now shares this restrained visual style and retains the same readers and data definitions.

## XML Schema validation

**Validate XSD…** is available after an XML preview finishes. The user selects the main .xsd; validation covers the entire XML document and reports a clean match or every schema finding in pages of 50 with XML path, category, reason, and line when available. Results identify XSD 1.0/1.1 plus source and main-schema hashes. This action does not require a saved record group because XSD scope is the document.

The chosen schema is authoritative for that run. Schema hints in the XML remain ignored. Only local imports/includes inside the chosen XSD's folder tree are allowed; network and outside-folder access fail visibly. Source and all loaded local schemas are checked for changes before publishing. Work is cancellable, temporary findings are bounded and removed, and neither XML nor XSD is changed. XSD conformance is structural/type evidence, not MISMO-specific interpretation or financial validity.

## XML column review

For a **saved XML data set**, select a field heading or a cell, then use **Inspect column** or **Check column** beside the group controls. Save any edited name first. Both actions use every record in that saved group, including records and fields beyond the current preview page; choosing a nested group reviews that group only.

**Inspect column** uses the same summary dialog as Excel. It counts absent fields, empty elements, explicit `xsi:nil`, empty attribute text, ordinary text, whitespace-only text, and the exact text `0` separately. All nonempty XML values retain their text representation; `0.00`, identifiers, date strings, missing-value tokens, and formula-looking text are not converted. Distinct/repeated values use exact text and state without trimming or case folding. Missing/empty states are excluded from repetition counts; whitespace remains text. Examples show up to three per state and the ten most repeated values, with complete group counts and source paths.

**Check column** uses the existing four explicit expectations. Identifier and Text preserve leading zeros and flag surrounding whitespace. Number checks **plain decimal text**: ASCII digits with an optional sign and decimal point, including `.5`; grouping separators, currency symbols, percent signs, exponents, non-finite words, and a trailing decimal point are not inferred or accepted. No numeric conversion or rounding occurs. Date offers exact `YYYY-MM-DD`, `MM/DD/YYYY`, or `DD/MM/YYYY` text conventions, optional inclusive year limits, and the existing session-reference-date flag. The XML dialog starts with the visible ISO text convention; select the convention you intend before running. Dates are parsed only for checking, not rewritten or given financial meaning. These checks do not use XSD or dictionary packs.

Required-value findings distinguish absence, empty elements/text, nil, and whitespace. Allowing missing values counts those records separately; tokens such as `N/A` still remain literal text. Every flagged record is available in findings pages of 20, with its original text, presence state, and namespace-qualified source path. **Jump to record** returns to that record and field in the existing preview, even beyond the first page. Findings are valid for their original saved group and source hash; a changed setup or source cannot silently redirect them.

Reads are cancellable background operations and verify the complete document, full group coverage, and source identity before publishing a result. Temporary frequency and findings databases stay under `.artifacts/column-inspection/` and `.artifacts/column-checks/`, with a 512 MiB limit for each XML database; limit/storage failures are explicit. Temporary data is removed after profiling, on result close/rerun, cancellation, failure, or normal app shutdown. Rules/results are not yet persisted or exported. CSV full-column review remains future work.

## Desktop preview layout

The native main window contains a permanent Files tab plus an analysis/preview tab and a simpler Order tab for the open file. Open file selects the preview; clicking tabs or Ctrl+Tab/Ctrl+Shift+Tab switches without reloading, cancelling readers, or losing selection, paging, scrolling, zoom, reading settings, ordered results, or unfinished setup. The file tab's × and Ctrl+W from either file-related tab close both views and return to Files. Opening the same saved copy selects its analysis tab; a different saved copy replaces both file views. Edited, unsaved data set setup requires confirmation before close/replacement/application exit. Untouched detected suggestions do not prompt. Tab state is session-local; saved definitions still restore through the existing persistence.

Drop feedback is shown on Files even when a file was dropped over the preview. The optional workbook-details dialog hides/restores with its owning tab. Column tools remain dialogs. Tab close cancels only that preview's owned work, preserving active intake copies and leaving the app able to open another preview. Main-window shutdown retains full worker cleanup.

Order uses the explicit saved Excel/XML data set and column selected on the analysis tab. It reads and retains the complete saved row-and-column population in bounded temporary SQLite storage; the selected column is only the order key. The display pages through 50 ordered source rows and 10 source columns independently, keeping every cell attached to its original row. A–Z/Z–A apply case-insensitive textual order with exact text as a tie-breaker. Ascending/Descending put stored Excel numbers first in numeric order; they do not parse XML text or text-formatted identifiers as numbers. Other filled order values remain visible and missing order states stay last. Jump to source returns to the original row and selected column. Ordering never writes or rearranges the source, and CSV ordering remains unavailable until CSV has a saved complete-data-set scope.

A data set is an application selection of existing source cells, not a newly created Excel table. Saving setup only stores local coordinates and header choices.

The worksheet is the main working area. A compact, 240-pixel left panel uses smaller labels and controls and can be hidden/restored with a green arrow button in a narrow strip along the panel's right edge; the strip and toggle stay visible when the panel is collapsed. Collapsing preserves setup, selection, and the loaded preview while giving the grid the freed space. Sheet, saved Data set, Setup, and Zoom remain above the worksheet. Saving or restoring a saved workbook data set folds the setup rail away; Setup or its edge arrow restores it. The rail contains suggestions, boundaries, headers, and data-set management. Column actions remain visible above the grid while unavailable, and a next-step prompt explains whether to save the data set, select a column, or choose a review action; the applicable buttons enable only after the required saved scope and selection are ready. XML similarly folds its name editor away after saving and exposes Edit setup. The selected sheet has a visible, scrollable data set list with a total count and a separate entry for every detected data set. It remains available by reopening Setup after saving. Clicking a group reopens its saved boundaries when the correspondence is unambiguous; custom saved definitions remain available in the saved data set selector. Discovery does not cap the number of detected data sets and separates declared Excel tables from surrounding plain ranges. Saving collapses the range/header form into a summary; Edit setup reopens it and Add another offers the next suggestion not overlapping an already-saved data set, with a whole-sheet option for manual selection. Clicking a column header selects the complete data set column and highlights its visible cells and heading. The source range is shown below the grid, selection follows row paging/zoom, and cell clicks return to individual cell selection. Column actions require a saved, unchanged data set and an explicit column selection. Inspect describes counts and values; Check tests an explicit rule. The grid defaults to 80% zoom with options down to 15% (15, 20, 25, 35, 50, 65, 80, 100, and 125 percent), scaling the data font, row height, and column width while keeping original row numbers pinned. Zoom retains the 20-row/10-column display page and complete saved data set scope. Full start/end addresses remain visible; Start and End jump to both corners. Users can edit start/end cells or right-click a cell to set a boundary. Thin scrollbars support native dragging and direct jumps when clicking their track. Mouse-wheel motion scrolls rows, Shift-wheel moves sideways, and small deltas accumulate instead of causing oversized jumps. This movement stays inside the current preview. Compact page arrows stay beside the worksheet, and full cell details expand on request. Scan inventory and reader settings live in a separate details window, with comparison status and the session date visible in the main preview. Smaller windows retain at least 420 pixels of unselected grid height at the tested 980x740 main-window size; the setup rail can scroll independently. Native control groups wrap at narrow sizes or larger Windows text scales. Long filenames shorten for display while retaining their extension and source identity. Hidden edited setup is marked Unsaved setup, and the persistent selectors guard edits before switching. Loading, empty, and recoverable read-error states are explicit, with Try again available after failures.

## Explicit column checks

Check column applies a user-selected expectation (Identifier, Text, Number, or Date) to every data row of one saved Excel data set column or every record of one saved XML field. XML uses the text rules and presence distinctions described above; the following stored-cell behavior applies to Excel. It flags blank/empty values when requested, incompatible stored types, surrounding text whitespace, stored Excel errors, and unevaluated formulas. Date checks require an explicit format for text dates and allow user-supplied year limits and an optional comparison to the session reference date. No automatic typing, digit repair, missing-token interpretation, formula execution, or source editing occurs.

All flagged rows are reviewable in pages of 20 findings, with original values, reasons, and source-cell navigation. Results preserve the selected data set and settings context; settings changes invalidate old results. Temporary results are removed on normal close or rerun. These checks support analyst review, not a claim of financial validity. CSV column checks, persistent check profiles, cleaning, and exports remain future work.

## Loan-market calendar screening (implemented)

Use SIFMA as the sole built-in provider for U.S. fixed-income holiday screening, following the packaged [SIFMA calendar guidance](../src/loan_tape/guidance/SIFMA_CALENDAR.md). Preserve the distinction between original closing, funding, trade settlement, rate determination, payment, and maturity. Only published 2019–2027 holiday schedules are known; other weekdays remain unknown while weekends can be calculated across the review horizon. An agreement-specific requirement is needed to establish a date error. Source dates remain unchanged.

The separate red-flag phase of the date-analysis API and complete-data-set **Date workflow** implements bounded calendar screening only after mapped dates have been imported and standardized. If the local date dictionary is inactive, that workflow offers an explicit in-context activation action, pins the selected local version in the default profile, and continues in the same window without changing the workbook. The simpler Check column action remains independent. Complete guidance and the verified schedule resource ship in the repository and distribution packages; local portfolio audits do not.

## Dictionary pack foundation

An independent backend now supports editable dictionary packs with field definitions, types, code lists, context, missing-data metadata, and source references. Packs start inactive and are explicitly activated/deactivated in named local catalog profiles. Activation snapshots exact pack content; subsequent file edits require reactivation to change that profile. Definitions remain separate across sources and are never matched by label alone.

This is a reference catalog, not an analysis engine. The desktop's existing inspection and checking behavior is unchanged. A desktop Dictionary packs manager now provides field search, source review, profile loading, and explicit activation/deactivation. It distinguishes editable and active versions and shows unavailable definitions without substituting another version. The in-app editor now creates packs and custom copies and edits pack details, field definitions, source records, allowed-value lists, and citations. Exact code text is preserved, and deletion cannot leave broken references. Saving validates a complete draft, preserves prior files, and leaves active snapshots unchanged. Locally edited definitions are identified separately from earlier source references. The saved Excel column-definition editor and date-standardization workflow consume explicitly selected active fields; broader pack-driven checks, overrides, and normalization remain future work. The initial ESMA pack is a reviewed subset of the supplied reporting documents, not a full corporate-loan dictionary. See [Dictionary packs](PACKS.md).

## Saved Excel column definitions

For a saved `.xlsx` or `.xlsm` data set, the user selects one source column and explicitly maps it to a field in the active `default` dictionary profile. The editor records the source header, field meaning and expected type, canonical and source units, currency, accepted literal text date formats, required/blank/unique choices, optional numeric bounds, missing tokens, and notes. Monetary fields whose definition requires currency cannot be saved without a three-letter code. Date definitions require an accepted text format and two-digit formats require an explicit 100-year window; Excel numeric dates remain governed by the workbook's date system.

Settings are local, atomic JSON under `.artifacts/column-definitions/`. They are bound to the source SHA-256, stable data-set identity, exact sheet/range/header scope, and source column. The exact dictionary pack version/fingerprint and field/code meanings are embedded, so later pack edits or deactivation cannot rewrite the saved meaning. A changed data-set scope does not silently inherit definitions from the earlier scope. Source files and intake copies remain unchanged.

Excel cell storage kinds and number formats are retained as evidence but never establish whether a column is a loan identifier, balance, maturity date, or another business concept. Saving a definition does not inspect every value, execute the recorded rules, normalize values, or establish financial validity. Those checks remain a downstream analysis milestone. CSV/XML definitions are not included in this slice.

## Warehouse Model mapping profile

A bundled, versioned profile recognizes the reviewed 94-column Warehouse Model layout after the user saves an Excel data-set range and header row. Matching requires the complete raw header sequence, including the source typo, trailing whitespace, order, and each occurrence of duplicate rating headers. An exact match is shown in the preview and binds stable profile keys to the original Excel columns without modifying the workbook.

The profile describes expected type, source/calculated/mixed role, presence, and units for the reviewed template. It is metadata for subsequent work, not a claim that the current values are valid. It neither creates persistent column definitions nor runs rules or normalization; near matches remain unmatched and require review.

## Rate definitions and interpretation (backend)

Phase 1 adds a project-authored `loan.rates` dictionary and immutable scalar parsing
contracts. Rate meaning is kept separate from representation: confirmed contractual
spreads normalize to exact decimal basis points; confirmed coupons, supplied benchmark
values, floors, caps, and yields normalize to exact decimal rates. Raw values, storage
tokens/types, display text, number formats, formula/error state, source coordinates,
source unit and source resolution remain evidence. No binary floating-point arithmetic
or incidental rounding is introduced.

Unitless values remain ambiguous unless a versioned profile supplies an applicable
source unit. Explicit source-specific aliases can decompose benchmark-plus-spread text,
but a generic SOFR label never establishes tenor/method and Prime is not substituted
for an agreement-defined Base Rate or ABR. Results distinguish valid, normalized,
ambiguous, invalid, missing, unsupported and source-error outcomes.

This foundation does not read or map complete data sets, infer units from population
distributions, retrieve market data, calculate yield/coupon, interpret agreements,
apply cross-field red flags, change source values, expose a desktop workflow, or export
results. See [RATES.md](RATES.md).

## Date definitions and interpretation (backend)

A project-authored `loan.dates` dictionary supplies four distinct date meanings and
required context, with no automatic column matching. Separate immutable parsing
profiles define permitted representations, short-year windows, missing tokens and
timestamp handling. The scalar parser exposes valid, ambiguous, invalid, missing,
unsupported and source-error outcomes while retaining original evidence. The raw
Excel date-column reader preserves XML tokens, date system, formats, formulas and
source coordinates and fails without partial results when extraction is incomplete.

This foundation is available through the Python API described in [DATES.md](DATES.md).
The simpler one-column desktop checks remain unchanged. Steps 3-8 add complete-row
date analysis, a source-bound SIFMA calendar, self-contained session runs, graphical
field mappings, finding review, and validated xlwings exports of the complete saved
data set with successfully standardized dates applied. Published, projected
and unknown calendar coverage remain distinct. See
[DATE_ANALYSIS.md](DATE_ANALYSIS.md) for capabilities, coverage and limits.

## User workflow

1. Select a local CSV file or Excel workbook and record its identity and reporting context.
2. Inspect source structure before interpreting its fields.
3. Review or supply field definitions and mappings.
4. Normalize supported values and surface ambiguity.
5. Review findings and record decisions or justified corrections.
6. Reconcile positions and exported results to the relevant source population.
7. Export positions and supporting audit information.

The taxonomy evaluation workflow additionally compares findings against independently reviewed ground truth, including sampled passing records.

## First processing milestone

Use one documented synthetic CSV format and an explicit mapping profile. Preserve raw records and column positions; do not infer field meaning from labels alone. Produce normalized positions, lineage, findings, transformations, and reconciliation for a limited, documented field set.

Acceptance requires unchanged source bytes, traceability for each normalized field, explicit parse/mapping failures, preservation of text identifiers, and accounting for every input record. Unsupported dates or units must produce review outcomes. No numeric correction may be inferred from a desired total.

## Later scope

Workbook inspection and reconstruction follow the first CSV workflow. Both input paths share mapping, normalization, validation, and reconciliation. A review workbook and UI should expose source evidence, open findings, and recorded decisions. Corpus evaluation covers supplied CSV and Excel files and does not depend on a PDF/OCR milestone.

Production hosting, automated credit decisions, and performance claims about the real research corpus are outside the foundation milestone. The corpus is maintained separately and was not supplied with the handoff.

## Definition of professional quality

- Installation and checks are repeatable.
- Implemented features, limitations, and output meanings are accurately documented.
- Data transformations have inspectable evidence and explicit policies.
- Automated tests cover known failures and valid cases.
- Research results are reproducible against a frozen taxonomy and a defined evaluation set.
