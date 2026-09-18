# Loan Tape

Loan Tape helps analysts preserve and inspect loan-portfolio data supplied as CSV,
XML, or Excel, with traceability back to the original source. It runs locally,
keeps source values intact, and makes incomplete or ambiguous results visible for
review.

**Public alpha 0.1.0 · Python 3.12 · Windows desktop · MIT License.** This is the
first usable release, not a finished underwriting or production platform. The bounded
date workflow includes explicit standardization, red-flag review, and a separate
full-data-set export. Broader financial normalization and agreement-specific validation
remain later milestones. The application does not establish that a portfolio is
financially correct or approved for production use.

[Operating guide](docs/OPERATIONS.md) · [Security policy](SECURITY.md) ·
[Release checklist](docs/RELEASING.md) · [Development](CONTRIBUTING.md)

**Current input scope: CSV, XML, and Excel.** PDF extraction and conversion functionality already exists separately and will be integrated in a later, separate phase. PDF/OCR processing is not part of the current implementation scope.

## What is in 0.1.0

| Available now | Not implemented yet |
| --- | --- |
| Source-preserving local intake for CSV, XML, and supported Excel files | General financial normalization or automatic correction |
| Workbook navigation, bounded previews, saved data sets, complete-column inspection/checks, and read-only ordering | Execution of saved column definitions across a complete pool |
| XML paging, saved groups, complete-column checks, and optional local XSD validation | XML export or agreement-specific XML interpretation |
| Explicit date standardization, red-flag review, SIFMA screening, saved runs, and a full saved-data-set Excel export | Full-pool rate analysis, reconciliation, credit decisions, or production approval |
| Versioned dictionary packs and a backend scalar rate parser | PDF/OCR integration, hosted services, or telemetry |

Drag and drop a file and wait for its unchanged local copy. Files shows whether the
selected format supports full workbook review, XML review, preview only, or preservation
only before **Open file** is available.
Unsupported or incomplete work fails visibly; it is not presented as a successful
analysis.

**Calendar source:** Loan Tape uses SIFMA as its sole built-in provider for U.S. fixed-income holiday screening. The bundled calendar uses published 2019–2027 schedules only; weekends remain deterministic at any horizon and uncovered weekdays stay unknown. Calendar applicability comes from the governing agreement, and source dates are never changed. The [complete SIFMA calendar guidance](src/loan_tape/guidance/SIFMA_CALENDAR.md) and normalized facts ship with the repository and distributions.

The project has two intended outcomes:

1. Reviewable position data with documented mappings, exceptions, changes, and reconciliation.
2. Measured evidence about which loan-tape errors a versioned taxonomy detects or misses.

## Start here

Use an existing **Python 3.12** installation with Tcl/Tk. Then, from the project
folder on Windows:

1. Prepare the project-local environment (network access is needed the first time).

```powershell
.\setup.bat
```

2. Start the desktop application.

```powershell
.\start-ui.bat
```

3. Add a synthetic CSV, XML, `.xlsx`, or `.xlsm` file first. Review the saved-copy
   location and open the file from the Files page.

4. Use **Inspect**, **Check**, **Order**, or **Date workflow** only after reviewing
   the detected data-set boundaries. Keep real portfolios in an approved local
   location and out of Git.

5. For CLI help or a development checkout check, run:

```powershell
.\run.bat --help
.\run.bat --version
.\check.bat
```

If Python 3.12 is not registered with the Windows launcher, provide its path:

```powershell
.\setup.bat "C:\path\to\Python312\python.exe"
```

Setup installs pinned `uv` in `.tools/` and dependencies from `uv.lock` in `.venv/`. Setup/check temporary files and tool caches remain in `.cache/`. Use `dev.bat pytest` or `dev.bat ruff check .` for targeted development commands with the same local storage. Direct pytest runs also use account-specific local temp/cache folders. Setup needs network access on first installation and does not install Python, change PATH, or require environment activation. An incompatible or missing interpreter fails with an explicit error.

The scripts also support Python 3.12 on Linux:

```sh
python3.12 scripts/setup.py
.venv/bin/python -m loan_tape --help
.venv/bin/python scripts/check.py
```

## File intake interface

Double-click the **Loan Tape** shortcut on your Windows desktop. It opens the program without a terminal window. To create or recreate that shortcut, double-click **create-launcher.bat** in this project folder. The shortcut uses the project environment and does not install an application or change system settings. Recreate it if the project is moved.

You can also double-click **start-ui.bat**, or run:

```powershell
.\start-ui.bat
```

On **Files**, select **Add file** or drop one file anywhere in the window. Saving starts automatically. Selecting a file shows its available review level beside the action. Open a supported file with **Open file**, Enter, or a double-click. For preserved-only `.xls`/`.xlsb` files, the preview action is disabled and keyboard or double-click attempts explain that a separate `.xlsx` copy is needed. Select **Details** to reveal its **Original location**, **Saved copy**, and save folder; **Copy original** and **Copy saved** copy the corresponding path. Details can be collapsed without changing the selection. The file list has a saved-file count, names, added times, and sizes. Dictionary packs, Exit, and the fixed session date remain available below the list.

- Accepts filenames ending in **.csv, .xml, .xlsx, .xls, .xlsm, or .xlsb**, up to **100 MiB** (shown as 100 MB) per file.
- Saves unchanged working bytes into `inputs/<unique-id>/<original-filename>` for the current application session. Originals are never modified; same-name files get separate copies.
- Writes `manifest.json` beside each copy with its original absolute path, filename, saved name, size, SHA-256 hash, UTC save time, and record ID.
- Resets file history on normal **Exit** or main-window **X**: intake working copies, source-bound selections/definitions, saved date runs, and session metadata are removed after background work stops. Explicit exports and dictionary-pack state remain. Forced termination can leave files for manual review.
- Rejects explicit network/UNC and Windows device source paths. Use a regular file on this computer.
- Checks file identity, size, and modification metadata before publishing a copy. A source that changes while being copied produces an error instead of a completed entry.
- Intake accepts files by extension only. The selected-file capability label distinguishes full `.xlsx/.xlsm` review, XML review and XSD validation, CSV preview-only behavior, and preserved-only `.xls/.xlsb` files. Open file reads supported formats separately; formulas, macros, and links are not executed.
- Runs as a desktop application with no browser or local web server. Use **Exit** or the main window's **X** to close the program. It cancels readers and closes child windows, finishes an active file copy, waits for background cleanup, and then resets session files. If a working copy is still open in Excel, close it and choose Exit again.
- Sources and manifests in the default `inputs` folder are ignored by Git and excluded from builds. Working copies are ordinary temporary local files, not a backup, durable evidence store, secure-erasure mechanism, or tamper-proof archive.

The desktop requires Python 3.12 with **Tcl/Tk** and the locked **tkinterdnd2** dependency installed by `setup.bat`. It uses the same Tkinter/ttk approach as FinExtract. No global packages or system settings are changed.

Other launch options:

```powershell
.\run.bat --ui
.\run.bat --ui --storage-dir .\inputs
```

The desktop shortcut and `start-ui.bat` always start in the project folder, with this project's `inputs` and `.artifacts`, regardless of the caller's current directory. Direct CLI launches default to `inputs` in the current directory. On Linux, `.venv/bin/python -m loan_tape --ui` additionally needs Tcl/Tk and a graphical display. Windows is the verified desktop target.

## Dictionary packs

Select **Dictionary packs** on the Files tab to browse and search definitions, expected types, allowed values, and sources. Use **Activate pack**, **Update active version**, or **Deactivate** to change a catalog profile. The command-line interface remains available through `run.bat packs`. All packs start inactive. Activation selects a versioned snapshot for a separate catalog profile. Intake, inspection, and ad-hoc column checks remain independent; the explicit Excel **Define column** action uses the active `default` profile.

The project includes an editable synthetic example and a small, source-referenced ESMA reporting pack. Adding folders or editing definitions never silently changes active snapshots. See [Dictionary packs](docs/PACKS.md) for the format, activation commands, authoring workflow, and limitations. The manager separates **Editable files** from the saved **Active version**. Use **New pack**, **Make a copy**, or **Edit pack** to author pack details and field definitions in the app. Saving keeps earlier files for recovery and leaves activation unchanged. The **Sources** and **Allowed values** tabs also edit source records, citations, and exact code meanings. Linked entries cannot be removed until their references are updated. Broader pack-driven analysis remains future work.

## Saved Excel column definitions

For a saved `.xlsx` or `.xlsm` data set, select a column and choose **Define column**. Select its business meaning from an active dictionary field, then record the source currency and units, accepted text date format (with an explicit century window for two-digit years), required/blank/duplicate choices, optional numeric bounds, missing tokens, and rule notes. The synthetic `example.loans` pack contains Loan identifier, Loan principal balance, Maturity date, and Loan status examples; activate it explicitly before using those meanings.

Definitions are stored for the current application session under `.artifacts/column-definitions/`, bound to the saved source hash, data-set identity, exact range/header scope, and source column. Each definition freezes the selected pack version, content fingerprint, field meaning, expected type, canonical unit, and exact category values. Editing a data-set range creates a different scope rather than silently applying earlier mappings. Normal application exit removes these definitions; the workbook and intake copy are never changed.

Excel does not enforce one type for a whole column. Each cell has a stored kind, while Currency, Date, Percentage, and similar choices are commonly number formats. Loan Tape therefore treats those cell types/formats as source evidence, not as the column's financial meaning. A saved definition is the explicit intended interpretation; checking it against every source value is a later analysis step. CSV/XML column definitions and execution of these saved rules remain future work.

## Warehouse Model mapping profile

The app includes a reviewed, versioned profile for the 94-column Warehouse Model layout. After the complete Excel data-set range and its header row are saved, the preview compares every raw header exactly and displays the profile name only on a complete match. Header spelling, whitespace, order, and duplicate occurrences are part of the identity, so the repeated `Aaa` through `B2` groups bind by position and occurrence rather than by label alone.

The profile records stable column keys, expected data types, source/calculated/mixed roles, required/optional/conditional presence, and known units. It does not create source-bound column definitions, execute checks, normalize values, or accept a similar layout heuristically. A mismatch remains unmatched for explicit review, and the source workbook stays unchanged.

## Rate definitions and parsing (backend)

The inactive `loan.rates` pack separates contractual spread, reference-rate identity
and observation, stated/cash/PIK/total coupon, base and coupon floors/caps, and supplied
yield measures. A pure scalar parser preserves source evidence and exact precision,
normalizes confirmed spreads to decimal basis points, and normalizes other confirmed
rate measures to decimal rates. Unitless values stay ambiguous unless an explicit,
versioned profile supplies their source unit. Composite text such as `SOFR + 6.25%`
requires a source-specific benchmark alias; `Prime`, agreement-defined Base Rate, and
ABR are never silently treated as equivalent.

This Phase 1 backend does not yet read a complete pool, map columns, infer units from
labels or distributions, retrieve market observations, calculate coupon/yield, run
cross-field checks, change source values, drive a desktop workflow, or export results.
See [Rate fields and parsing](docs/RATES.md) for the exact contracts and outcomes.

## Date definitions and parsing (backend)

The `loan.dates` dictionary pack defines closing, original maturity, current maturity,
and reporting dates with explicit context. It starts inactive and never maps columns
automatically; a user may select one of its active meanings in an explicit mapping workflow.
A separate date backend preserves raw source evidence and interprets dates under a
versioned profile, including explicit short-year windows, ambiguous day/month order,
missing tokens, timestamp policy, and Excel 1900/1904 serials. The raw `.xlsx`/`.xlsm`
reader retains source tokens, formats, formula evidence and original cell positions.

See [Date fields](docs/DATE_FIELDS.md) and [Date parsing](docs/DATES.md) for the API,
limits and synthetic example. The existing one-column Date check remains available.
For a saved Excel data set, **Date workflow** separates two phases. **Import &
standardize** maps columns and interprets every source date without running red flags.
If the local `loan.dates` definitions are not active, the same window offers an
explicit **Enable loan date definitions** action. That click pins the displayed local
version in the default profile and continues in place without changing the workbook.
The separate **Red flags** phase consumes that completed snapshot for required-value,
range, pair, reference-date, and SIFMA calendar checks. Review runs remain reproducible,
support source-cell jumps, and export the complete saved data set to a separate xlwings
workbook. Successfully interpreted dates replace their mapped source values in the exported
**Loan Tape** sheet; unresolved cells retain their original literal values. See
[Date analysis](docs/DATE_ANALYSIS.md).

## Session reference date

Each desktop launch captures the computer's local date and time once. The main window shows **Reference date** and the startup time with its UTC offset; every Inspect file tab uses the same session reference date. It stays fixed if the session crosses midnight or the computer clock changes. Starting the app again captures a new reference date and time.

A separate record is saved under `.artifacts/sessions/<session-id>.json` in the working directory, containing the local timestamp, equivalent UTC timestamp, local time-zone name/offset, and reference date. Records are excluded from Git and builds. A recording failure produces a startup error instead of silently continuing without a record. The clock comes from this computer; no internet or AI is used.

Check column can optionally flag dates before this reference date and outside year limits you supply. A past-date flag is for review; it does not establish that a loan has matured. The session date is separate from any reporting date supplied in a workbook; no source dates are changed.

## Inspect file

The main window has a permanent **Files** tab plus an analysis/preview tab and a simpler **Order** tab for the open file. Select a previewable saved file and click **Open file**, or double-click its row, to open and select the preview tab. The selected-file capability label and button state identify preserved-only formats before opening. Switch tabs by clicking their names or using **Ctrl+Tab** / **Ctrl+Shift+Tab**. Switching preserves the loaded page, selection, scrolling, zoom, reading controls, ordered page, and any unsaved data set setup; readers keep running.

Use the file tab's **×** or **Ctrl+W** from either file-related tab to close the preview and Order view and return to Files. Reopening the same saved copy selects its existing analysis tab. Opening another saved copy replaces both file-related tabs, even when its filename is the same. Closing/replacing a preview or exiting asks before discarding edited, unsaved data set setup; choose Cancel to return and **Save data set**. Untouched automatic suggestions do not prompt. Closing a preview cancels only its own readers and column tools; an intake copy continues.

Dropping a file over either tab selects Files so its saving/error message is visible. Workbook details hide while Files is selected and return with the preview. Column inspection/check tools remain dialogs, and **Open in Excel** remains a separate manual Excel window.

The preview reads the **saved copy**, so it still works if the original file is moved.

The **Open in Excel** button at the top right opens the saved working file directly in desktop Microsoft Excel, including CSV files. It works independently of preview reading or data set setup and reports an error if Excel or the file is unavailable. This is a normal manual Excel window. Close that workbook before exiting Loan Tape; Windows may otherwise prevent the session reset, in which case Loan Tape stays open and asks you to close the copy and try Exit again. Loan Tape does not edit or save the file through this action. Excel uses its normal opening behavior and settings.

A data set is a named selection of existing cells for analysis. Saving its setup only records its location and headers locally; it does not create an Excel table or change the workbook.

XML uses this same preview window and grid. A single repeated record group opens automatically; if several groups are found, choose **Record group** above the grid. With no repetitions, the document root is one record. Element paths and attributes become column labels, and Cell details shows the source path and whether a value is present, absent, empty, or explicitly nil. Namespaces remain distinct, with aliases explained below the grid. Values are decoded XML text, without numeric/date conversion; original XML bytes remain preserved.

XML stage 2 reaches every record and field in a supported group through pages of up to 20 records and 10 fields. Use the **Records** and **Fields** arrows, **Start**, **End**, or **Go to record / field**. Record numbers count occurrences in the selected group, and field numbers follow the displayed column order; they are not XML line numbers. Full group dimensions and the current page remain visible. Fields first appearing late in the document are included, with absent values kept distinct on earlier rows.

Give the group a name and select **Save data set** to save the complete group, including records and fields outside the current page. Use **Data set** to switch, **Edit setup** to rename and save, **New** to start another setup, or **Remove** to delete only its local definition. Each saved group remembers its last successfully viewed page during the current application session. Edited names are protected on close or group changes. Setup metadata lives separately under `.artifacts/xml-selections/` until normal application exit; source XML and workbook settings remain unchanged. Changed files cannot reuse old selections, and corrupt or unwritable settings are reported visibly.

The complete file is streamed on each page request before publishing a result, so malformed trailing content fails clearly and later fields/repetitions are detected. Repeated child groups and mixed text/element content are explicitly unsupported within a selected record; choose a narrower group where available. Limits on size, depth, nodes, paths, attributes, values, and preview memory still apply and fail clearly. DTDs/entities are blocked; schema hints and stylesheets are not fetched or executed. XML data sets select whole record groups and support full-column Inspect and Check. Optional XSD validation is an explicit action described below; XML export and Open in Excel remain outside the implemented XML stages.

The worksheet occupies the main area, with **Sheet**, saved **Data set**, **Setup**, and **Zoom** above it:

1. **Choose a sheet.** Use the persistent Sheet selector, or open Setup and use **Find data areas...** for shortcuts to blocks anywhere in the workbook.
2. **Choose a data set.** A visible list shows every detected data set on the selected sheet, each with its own cell range. Click a data set to review its suggested start/end cells and header row. Edit **Start cell**, **End cell**, or **Header row number**, then **Show these boundaries**; you can also right-click a grid cell to set an edge. **Save data set** accepts your reviewed definition and folds the setup panel away. Sheet and saved-data-set switching stay visible. **Setup** or the edge arrow restores the panel. Headers remain optional.
3. **Review columns or dates.** Follow the visible **Next** prompt: it identifies whether the data set still needs to be saved, a column needs to be selected, or the review actions are ready. The action buttons remain visible but disabled until their required saved scope and selection are available. Click a column heading to select the whole data set column: the visible column turns green and its complete source range appears below the grid. **Inspect column** describes its contents; **Check column** tests one explicit rule. After saving the data set, **Date workflow** first imports and standardizes explicitly mapped date columns. It does not run red flags. A separate second phase configures and runs required-value, bound, pair, reference-date, and calendar flags against that completed snapshot, then saves the review run, pages findings, jumps to source cells, and exports the complete refined data set plus supporting review sheets through xlwings. **Edit setup** revises the data set; **Add another** offers the next unused suggestion; **Whole sheet** remains available for a custom range.

Long filenames are shortened visually while retaining their extension and full saved-file identity. Edited hidden setup is marked **Unsaved setup**; switching through Sheet or Data set asks before discarding edits. CSV reading controls and workbook/XML navigation wrap onto another line when needed at small sizes or larger Windows text settings. Loading and empty states appear in the grid; a failed read offers **Try again**. XML also folds its name editor away after saving; **Edit setup** reveals it for renaming.

The grid starts at **80% zoom**; use **Zoom** to choose **15%, 20%, 25%, 35%, 50%, 65%, 80%, 100%, or 125%**. It changes text, row height, and column width without changing the data or the 20-row/10-column page. Its original row numbers stay pinned while scrolling horizontally. **Start** and **End** jump to the first or last corner of the complete selected data set, and its full start/end addresses and dimensions stay visible above the grid. Compact Rows/Columns arrow buttons sit below the grid; **Go to cell** is above it. A selected cell's value appears below the grid; **Cell details** expands its full value and metadata. **Reading details** contains the reader comparison and technical information. A compact comparison status and the reference date remain visible. The compact left panel has smaller controls and scrolls independently. Its green arrow button sits on a narrow strip at the panel's right edge. It stays visible when the panel collapses, so you can restore the panel without losing your selection or edits. Thin scrollbars keep more space for data; the mouse wheel scrolls rows, **Shift + mouse wheel** scrolls sideways, and clicking the scrollbar track jumps directly within the current preview. High-resolution wheel movement is accumulated for consistent small steps. These controls do not change the loaded page; use the Rows/Columns arrows to change pages.

- Supports preview for **CSV, XML, .xlsx, and .xlsm**. Older **.xls/.xlsb** files can still be saved unchanged, but Files labels them **Preserved only**, disables preview, and explains how to proceed if Enter or double-click is used; add a separately saved `.xlsx` copy to review those.
- **Excel discovery scans every worksheet across all source rows and columns**, including hidden/very-hidden sheets and hidden rows/columns. It follows actual stored cells instead of trusting Excel's reported used range. **Find data areas...** shows visibility, data bounds, dimensions, and stored-cell counts. Empty or unsupported tabs and failed scans are explicit; incomplete coverage is never reported as complete.
- **Data set suggestions** come from stored row/column structure across the full sheet, including hidden and distant cells. Separate blocks get independent endpoints, and dense text rows followed by data may be proposed as headers. Explicit Excel table definitions take precedence and retain their declared blank rows/columns. Suggestions are editable guesses, not confirmed financial data sets: plain ranges with blank separators, all-text records, or unusual layouts can need adjustment. Every detected data set gets its own list entry, with no cutoff at 200 data sets. Data sets above, below, beside one another, and at distant coordinates remain separate. Cells inside declared Excel tables are excluded from other data set detection, so touching plain ranges can still be found. Clicking a group reopens its independently saved edits when the match is unambiguous; saved definitions also remain available in the saved data set selector.
- Expand a sheet in **Find data areas...** to see **suggested areas** separated by blank row/column bands. Choose one and click **View selected area** (or double-click it). These are location shortcuts, not inferred financial data sets. More than 200 suggestions are explicitly combined into the full data bounds without limiting the scan. Formulas and explicitly stored empty text count as content; formatting-only cells do not enlarge data bounds.
- Choose a sheet/area, use **View entire sheet** in Find data areas, or enter start/end cells, such as **G450** and **AZ18400**, then **Show these boundaries**. View entire sheet includes every populated block and intervening gaps in its bounding rectangle. On the first populated readable sheet, the largest suggested data set is previewed as an unsaved draft. With no usable suggestion, all stored data bounds are shown. Saved data set definitions take priority when reopening. No column analysis runs until you save a data set and choose an action.
- Excel previews show **pages of up to 20 rows and 10 columns** at their original addresses. Use the Rows/Columns arrows or **Go to cell** within the current range; edit the range to go elsewhere. Click a cell for its full value; arrow keys move between cells. CSV retains its first-20-row/10-column preview and explicit separator/encoding controls.
- Define **multiple named data sets** on the same worksheet or across worksheets. Review each suggested data set or choose its boundaries, click a preview row and **Use row ... as headers** (or enter its original **Header row number**), give it a **Data set name**, then **Save data set**. Headers appear beside the original Excel column letters and remain visible when paging. The source header row stays in the grid and is highlighted; duplicate and blank headers remain distinct by their column positions.
- Use **Add another** for another data set, including one below or beside the first. Choose a saved data set and **Edit setup** to change its range, name, or header row and save it again. Clear the Header row field and save to remove its header designation. **Remove data set setup** removes only its local definition. Choosing a sheet/suggested area starts a new draft; paging stays within the current data set. Save changes before switching data sets or areas.
- Each saved data set retains its complete sheet/range/header coordinates under `.artifacts/selections/`, bound to the workbook content hash. Reopening the working copy during the same application session restores all definitions and opens the most recently saved data set. Normal application exit removes them. Earlier single-range settings remain readable until that reset. The 20-row/10-column display does not reduce a data set's saved range, and sources are never rewritten. Header selection does not map financial fields, remove rows, clean values, or run financial checks.
- CSV values stay text, including leading zeros, zero, blank fields, and missing-value tokens. Automatic separator detection supports comma, semicolon, tab, and pipe; separator and encoding selectors let you correct the reading settings. UTF-8 and BOM-marked UTF-16 are recognized automatically; Windows-1252 requires explicit selection. CSV row numbers count logical records, which may span physical lines.
- Excel has a worksheet selector, including hidden worksheets. Cells show stored values rather than Excel's rendered formatting; dates use ISO text and percentages may appear as fractions. Click a cell to inspect its number format and formula. Formula cells show the saved result when present, or formula text when no result is saved. Cached results may be stale; nothing is recalculated or refreshed.
- On Windows with desktop Excel installed, **openpyxl and xlwings read the same requested page in parallel**. The **Preview reader** selector under **Reading details** switches between their results; a comparison message reports agreement or highlights rows with different displayed values. Select a differing cell to see both values. The check covers the preview only and never chooses or corrects a value automatically.
- The xlwings reader opens a disposable temporary copy in a separate, hidden Excel instance. Loan Tape owns that Excel process and its Python reader from startup; completion, cancellation, and exit terminate only those owned processes. Existing Excel sessions stay open. No Excel add-in, LLM, API key, or cloud service is required. If Excel is unavailable, the openpyxl preview remains available with an explicit comparison error.
- To respect the rule against executing source formulas or macros, Excel comparison currently admits only plain data workbooks after inspecting their complete package. Formulas (including outside the preview), named definitions, macros, external links, connections, data sets, embedded objects, and other unrecognized package features produce a **comparison skipped** message. Those files still use the supported openpyxl preview. CSV continues to use its text-preserving reader.
- Reads run in the background. The preview is read-only and does not modify the original or saved copy. Temporary Excel comparison files are removed afterward. Discovery establishes stored-cell locations and scan coverage, not correctness of every value or financial meaning. Only the displayed page and its designated header cells are decoded for preview. Independent data set definitions and full-column inspection are supported. Financial analysis, combining data sets, and the later raw-evidence audit layer remain future work.

## Order data

For a saved Excel or XML data set, select a column or field on the analysis tab and open **Order**. The app carries over the complete saved data set—all of its data rows and columns—and uses the selected column only as the order key. It shows 50 source-linked rows and up to 10 source columns per page, with separate row and column navigation. **A–Z** and **Z–A** order the selected source text case-insensitively with exact text as a tie-breaker. **Ascending** and **Descending** put stored Excel numbers first in numeric order; other filled source kinds remain visible after them, while blank, empty, absent, and nil order values remain last. XML values stay text and are never inferred to be numbers.

Ordering is a read-only view. Each displayed row stays intact while its position in the view changes; the original row is never rearranged. The view does not write a workbook, convert identifiers, trim text, parse missing-value tokens, or detach cells from their source row. Select a result and use **Jump to source** to return to its original row at the ordering column. A changed/unsaved data-set scope is rejected. Complete results use bounded temporary SQLite storage under `.artifacts/column-order/` and are removed on scope change, file close, cancellation, failure, or application shutdown. CSV remains limited to its current preview because saved CSV data-set scope is not implemented yet.

## XML Schema validation

For an open XML preview, choose **Validate XSD…** at the top right and select the main local .xsd file. This validates the complete XML document independently of the current record group, page, or saved data set. The result states whether the document matches, identifies XSD 1.0 or 1.1, records the XML and main-schema hashes, and lists every finding in pages of 50. Each finding retains the validator's XML path, category, full reason, and a source line when the parser provides one.

Validation is opt-in. The application never follows xsi:schemaLocation, xsi:noNamespaceSchemaLocation, processing instructions, or a network URL automatically. Includes and imports may load only local files inside the selected XSD's folder and its subfolders; remote and outside-folder resources fail visibly. Put a schema package's companion XSD files together in that folder structure, then choose its main XSD. This is generic XSD validation and has no MISMO-specific rules.

The complete source is validated lazily in a background worker with entity protection and library processing limits. XML is capped by the existing 100 MiB intake limit; each local schema file is capped at 25 MiB and selected-package schema files at 100 MiB total. Source and schema files are hashed again before a result is published, so a mid-run change discards the result. Findings use bounded temporary storage under .artifacts/xsd-validation/ and are removed on close, cancellation, failure, or shutdown. Validation never edits XML or XSD files. A schema match establishes structural/type conformance to that chosen XSD only; it does not establish financial correctness, mapping, normalization, or reconciliation.

## XML column review

For a **saved XML data set**, select a field heading or a cell, then use **Inspect column** or **Check column** beside the group controls. Save any edited name first. Both actions use every record in that saved group, including records and fields beyond the current preview page; choosing a nested group reviews that group only.

**Inspect column** uses the same summary dialog as Excel. It counts absent fields, empty elements, explicit `xsi:nil`, empty attribute text, ordinary text, whitespace-only text, and the exact text `0` separately. All nonempty XML values retain their text representation; `0.00`, identifiers, date strings, missing-value tokens, and formula-looking text are not converted. Distinct/repeated values use exact text and state without trimming or case folding. Missing/empty states are excluded from repetition counts; whitespace remains text. Examples show up to three per state and the ten most repeated values, with complete group counts and source paths.

**Check column** uses the existing four explicit expectations. Identifier and Text preserve leading zeros and flag surrounding whitespace. Number checks **plain decimal text**: ASCII digits with an optional sign and decimal point, including `.5`; grouping separators, currency symbols, percent signs, exponents, non-finite words, and a trailing decimal point are not inferred or accepted. No numeric conversion or rounding occurs. Date offers exact `YYYY-MM-DD`, `MM/DD/YYYY`, or `DD/MM/YYYY` text conventions, optional inclusive year limits, and the existing session-reference-date flag. The XML dialog starts with the visible ISO text convention; select the convention you intend before running. Dates are parsed only for checking, not rewritten or given financial meaning. These checks do not use XSD or dictionary packs.

Required-value findings distinguish absence, empty elements/text, nil, and whitespace. Allowing missing values counts those records separately; tokens such as `N/A` still remain literal text. Every flagged record is available in findings pages of 20, with its original text, presence state, and namespace-qualified source path. **Jump to record** returns to that record and field in the existing preview, even beyond the first page. Findings are valid for their original saved group and source hash; a changed setup or source cannot silently redirect them.

Reads are cancellable background operations and verify the complete document, full group coverage, and source identity before publishing a result. Temporary frequency and findings databases stay under `.artifacts/column-inspection/` and `.artifacts/column-checks/`, with a 512 MiB limit for each XML database; limit/storage failures are explicit. Temporary data is removed after profiling, on result close/rerun, cancellation, failure, or normal app shutdown. Rules/results are not yet persisted or exported. CSV full-column review remains future work.

## Inspect column

For a **saved .xlsx/.xlsm data set**, click a cell or its column heading, then **Inspect column**. Save any range or header changes first. The summary covers every data row in that column's saved data set range, including hidden rows and blank gaps. If a header is set, data starts on the next row; the header and any earlier title rows are excluded. With no header, all rows in the range are included. The 20-row/10-column preview limit never restricts these counts.

- Shows the data set, source column/range, session reference date, total rows, filled cells, blanks, explicitly empty text, numeric zeroes, and whitespace-only text.
- Separately counts text, numbers, dates/times, booleans, stored Excel errors, and formulas. Text dates, identifiers, and missing-value tokens remain text. Formulas are counted by their expressions rather than cached results; nothing is calculated or refreshed. These are stored reader types, not inferred business meanings.
- Counts distinct filled values, values appearing more than once, and extra occurrences beyond the first. Matching uses the reader's value and type without trimming, case folding, numeric conversion, or date parsing; formatting differences do not split otherwise matching values. Blank and empty-text cells are excluded from repetition counts. Repetition alone is not classified as an error.
- **Examples** displays up to three source cells per type. **Repeated values** shows the ten most repeated values with full-population counts and their first source cell. These display limits never limit the scan. Select an entry for its complete value, then **Jump to cell** to return to that location in the preview.
- Reading runs in the background; Cancel or closing the preview requests cancellation. Failures and source changes produce an explicit incomplete/error message instead of partial totals. Hash checks bind the result to the saved workbook. Temporary frequency-count files under `.artifacts/column-inspection/` are removed afterward; no summary or source values are permanently exported.

Inspect column describes the data without cleaning it or inferring financial fields. Use Check column below to review values against explicit expectations. Both actions support saved Excel and XML data set definitions; XML text/state behavior is described above, and CSV retains its preview controls.

## Check column

For a **saved .xlsx/.xlsm data set**, select a cell or column heading, then **Check column**. Choose **Identifier**, **Text**, **Number**, or **Date**, set the available options, and click **Run check**. This reads every data row in that saved data set column, including hidden rows and blank tails, using the same header and range boundaries as Inspect column. Save data set edits first.

- **Identifier** expects text and flags other stored types for review without guessing digits or converting numbers. **Text** expects stored text. Both flag leading/trailing whitespace. Tokens such as `N/A` remain text, not inferred blanks.
- **Number** expects a stored finite number. Numeric zero is valid; booleans, text numbers, dates, currencies stored as text, and other types are flagged without conversion. Currency, units, precision, and business limits are not inferred.
- **Flag blank / empty values** is initially enabled. Blank cells, explicit empty text, and whitespace-only text have distinct finding descriptions. Disable it to allow these rows; their total is reported separately.
- **Date** accepts stored calendar dates. For text dates choose one exact format: `YYYY-MM-DD`, `MM/DD/YYYY`, or `DD/MM/YYYY`; the default **Excel dates only** flags text dates for review. Invalid calendar dates, mismatched formats, time-only values, and unformatted numeric serials are flagged. Parsing is only for checking and never rewrites the source.
- Date **Earliest year** and **Latest year** are optional, inclusive limits you choose. The optional **Flag dates before ...** checkbox uses the fixed session reference date, with the same day allowed. No year threshold or date convention is inferred. These checks do not assign financial meaning or determine whether a maturity is an error.
- Source Excel errors and formulas are always flagged for review. Source formulas are never evaluated and cached results are not used to declare them valid.
- Results show the applied settings, total data rows, and number of rows for review. **Every flagged row is available**, 20 per findings page, with its original value, source address, and reason(s). Select a finding for the full value and **Jump to cell**. Finding pages and the 20-row/10-column preview do not restrict the check.
- Changing settings clears old results; Run check again. Checks run in the background, support cancellation, verify the source hash before/after reading, and never publish incomplete results. Temporary findings under `.artifacts/column-checks/` are removed on normal close, rerun, settings changes, cancellation, and failure. Settings and findings are not retained between dialogs or exported yet.

The action is read-only and uses the existing openpyxl column reader. The xlwings-first writing policy applies when workbook editing/export is added. No cleaning, source changes, automatic duplicate removal, or financial field mapping occurs.

## Project map

| Location | Purpose |
| --- | --- |
| `src/loan_tape/` | Application services, native desktop UI, and CLI |
| `tests/` | Synthetic regression tests |
| `scripts/` | Local setup and validation |
| `docs/PRODUCT.md` | Users, intended workflow, and first release scope |
| `docs/ARCHITECTURE.md` | Planned boundaries and FinExtract reuse policy |
| `docs/DATA_CONTRACTS.md` | Draft data meanings and preservation rules |
| `docs/ROADMAP.md` | Ordered milestones and acceptance criteria |
| `SECURITY.md` | Trust boundaries, supported versions, known limits, and private reporting |
| `docs/OPERATIONS.md` | Analyst workflow, local records, confidentiality, and failure handling |
| `docs/RELEASING.md` | Release evidence, artifact checks, and authorized handoff |
| `src/loan_tape/guidance/SIFMA_CALENDAR.md` | SIFMA calendar policy, sources, published coverage and acceptance criteria; ships with the package |

## Development standard

Run `check.bat` before considering a change complete. It checks the lockfile and installed dependencies, formatting, lint, types, tests, CLI startup, source/wheel builds, and installation of the wheel with locked runtime dependencies into an isolated environment. Native desktop tests run when a graphical display is available; headless Linux reports those checks as skipped. Use Xvfb to exercise the desktop on a headless Linux machine. GitHub Actions is configured to run the same checks on Windows and Linux after code is pushed.

To check the actual desktop Excel integration separately, run `.\.venv\Scripts\python.exe scripts/smoke_excel.py` from the project folder on Windows with Excel installed. It creates only synthetic workbooks, checks visible/hidden/empty sheets, distant range pages, original cell coordinates, and unchanged source bytes, and verifies that its Excel instances close. For actual app exit during Excel startup, also run `.\.venv\Scripts\python.exe scripts/smoke_shutdown.py`; it checks both Excel and Python reader startup, preserved sources, removed temporary files, and unchanged pre-existing Excel process IDs. The standard test suite exercises comparison logic and lifecycle failures without requiring Office; it does not establish real Excel behavior on CI.

Built archives are also checked for private runtime folders, reference research,
credential/log filenames, and misplaced source-data files. This is a path-based
guard, not a scan of arbitrary file contents for secrets. The source archive
includes the MIT License, security policy, and operating/release guides; both archive formats
retain the complete SIFMA calendar guidance and verified calendar data resource.

See [Contributing](CONTRIBUTING.md) for commands and [AGENTS.md](AGENTS.md) for project working instructions.

## Data and distribution

Keep real portfolios and generated outputs outside version control. Local audit notes under `.local/` are ignored by Git and excluded from distribution builds. Only deliberately authored synthetic fixtures belong in tests. Preserve originals, record supported transformations, and keep missing values distinct from invalid values and zero.

The source is released under the [MIT License](LICENSE). Version `0.1.0` is an alpha
GitHub source release; it is not currently published to PyPI. FinExtract is an
engineering and repository-organization reference; no application code from that
project has been copied into this foundation.

## Date workflow backend

The Python API supports explicit date definitions/profiles, preserved Excel raw
evidence, a parser-only standardization handoff, separate complete-row red-flag
analysis, SIFMA calendar screening, saved reproducible runs, and xlwings full-data-set
exports with supporting review sheets. See [DATE_ANALYSIS.md](docs/DATE_ANALYSIS.md) for usage, verified published
holiday coverage, unknown-year behavior, and limits. Calendar facts and findings do
not adjust source dates. The simpler one-column Date check keeps its prior behavior.
