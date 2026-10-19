# Architecture

## Current implementation

Canonicalization Phase 8 adds `source_records.py` for bounded complete CSV reads
and protected XML group reads; `source_adapters.py` for saved native scopes,
explicit dictionary definitions and guarded use of the shared transformation
engine; and `source_adapter_ui.py` for native setup, mapping and manual review.
CSV metadata never masquerades as an Excel sheet/range. XML retains expanded group
paths and namespace evidence. `ColumnDefinitionWindow` accepts an explicit
adapter persistence context while preserving its existing Excel callers.
`workspace_reset.py` removes source-adapter settings after worker shutdown.
`smoke_source_adapters.py` exercises both formats from the installed wheel.
See [CSV/XML text review](SOURCE_ADAPTERS.md) for contracts and supported boundaries.

Canonicalization Phase 7 adds `entities.py` for immutable borrower populations,
explicit pair labels and group decisions; `entity_matching.py` for current-source
guards, bounded owned-worker execution and atomic JSON/model publication;
`entity_worker.py` for the isolated Dedupe runtime; and `entity_ui.py` for native
feature/pair/group review. The engine worker is invoked by file path from the
installed application and imports Dedupe only in `.tools/entity-matching/`.
Normal app imports do not require Dedupe. The worker verifies the validated package
inventory, trains a fresh model and records its full provenance. No user-supplied
model is deserialized. Matching never mutates transformation or loan rows.
Shutdown now waits for the owned job's active-process count to reach zero, including
Windows Python launcher descendants, before temporary files are removed. This uses
Microsoft's [job accounting](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_accounting_information)
after job termination; it does not terminate processes by image name.
Temporary-directory cleanup retries Windows sharing/lock violations for at most
five seconds without changing permissions. Persistent locks and other permission
errors fail visibly and retain the affected directory for diagnosis.
`workspace_reset.py` removes source-bound model/run files after owned workers stop.
`scripts/setup_entity_matching.py` prepares the optional runtime with an explicit
checksum-pinned portable compiler; `check.py --entity-smoke` exercises the actual
path from an installed wheel. See [ENTITY_MATCHING.md](ENTITY_MATCHING.md).

The user interface calls saved analysis selections **data sets**. Existing `SavedTable`/`TableSelections` types and persisted schema keys remain compatible; user-saved names are preserved. This terminology does not create or modify Excel table objects. New default names use Data set N.

An installable Python package exposes the CLI and a native Tkinter/ttk window for file intake.

- `session.py` captures one timezone-aware local startup timestamp per desktop application instance, exposes an immutable `AnalysisSession.reference_date` using its local calendar date, and atomically saves a unique JSON record under `.artifacts/sessions/` in the working directory. It records local and UTC timestamps, the local timezone label/offset, clock source, and reference date; write failures abort startup explicitly. `ui.py` passes the same session object to every preview. Dates do not advance during the session or reset on file/sheet changes. Normal application exit removes the session record through `workspace_reset.py`. Column date checks use this context for optional past-date flags and accept user-supplied year limits; they do not infer financial maturity meaning. The complete date workflow uses explicit field mappings, same-row pairs, and separately selected calendar policies.
- `intake.py` preserves opaque source bytes using staging, SHA-256 hashing, a versioned manifest, and an atomic directory rename. `save_path` records the original absolute path and checks source identity/size/modification metadata before publishing. Failures clean up staging. Stream-based preservation remains available independently of the UI.
- `ui.py` provides the Files document list, Add file/native file picker, window-wide drops, session file count/history, Open file action (also Enter/double-click), and an in-page Details disclosure for original/saved paths and clipboard controls. Empty history has an inline empty state; refresh preserves working-copy identity and selection during the session. Dictionary packs, Exit, and the session reference date remain available. After workers stop, Exit invokes `workspace_reset.py`, which removes validated intake records and named file-session artifact directories while preserving originals, explicit exports, pack state, and unrelated artifact folders. Reset failure keeps the app open with an actionable error. `tkinterdnd2` supplies native file drops. Tcl file lists are parsed without stripping meaningful braces or spaces from filenames.
- `theme_ui.py` centralizes native colors, fonts, button states, list styles, and tab padding. Files uses a borderless Treeview and near-black hunter-green Add file button. Its rounded image surface decorates a native ttk button, retaining native focus, keyboard activation, and disabled behavior; the app holds the images for its interpreter lifetime. Preview uses the shared palette; processing remains separate from presentation. Notebook selected/unselected padding is explicit so theme defaults cannot displace the close target.
- `flow_ui.py` lays out native control groups into available rows, preserving keyboard controls at narrow widths and larger text scales. Preview keeps workbook context above the grid and uses a navigator callback to fold/reveal setup after save/edit. The compact saved-set selector delegates to the existing navigator, retaining persisted definitions. Loading/error/empty overlays and retry reuse the existing tracked readers. XML name-editor disclosure and page-control wrapping retain its existing saved-group model.
- `tabs_ui.py` provides a native ttk Notebook with a permanent Files tab, a closable analysis/file tab, a related Order tab, standard Ctrl+Tab traversal, and a trailing × close target on the analysis tab. Long file-tab names are shortened only for display; saved-copy identity uses the preserved path. `ui.py` owns activation, paired replacement/close, Ctrl+W, root sizing/title, dynamically registered drop targets, and the unsaved-setup confirmation. `PreviewPanel` in `preview_ui.py` and `OrderPanel` in `order_ui.py` own Frames rather than Toplevels. Switching only changes visibility and hides/restores the optional workbook-details dialog. Source jumps select the analysis tab. Sidebar wheel binding is scoped to descendants and unbound when the panel closes; dialog transient ownership resolves to the root window.
- `navigation_ui.py` compares current setup fields against their last saved or freshly suggested values to protect edited drafts at the file-tab boundary. Saving establishes a new clean baseline. Selecting tabs never mutates this state. Closing a tab cancels its own event/column tools and removes its panel, without calling the shared WorkerGroup's application-wide cancellation. The shared WorkerGroup continues to track retired readers and pending file copies. Source readers, persisted-selection schemas, and Excel job/process ownership remain unchanged.

- `inspection.py` reads bounded CSV previews and .xlsx/.xlsm pages at arbitrary source-coordinate ranges independently of the UI. `FilePreview` carries its original starting row/column; a caller-supplied range is capped only for that preview read and retains blank cells through its requested page boundary so column examples remain navigable. CSV uses the standard-library reader without type coercion. Excel uses two read-only openpyxl readers for source formulas and cached results, with defusedxml enabled and links excluded. Files are closed without saving; .xls/.xlsb inspection fails explicitly.
- `excel_compare.py` runs openpyxl and xlwings concurrently for the same .xlsx/.xlsm page and compares displayed cell text by source position, checking matching sheet and page origins. Integral numeric floats display without a redundant `.0`; identifiers and other strings are not coerced. Agreement is limited to the displayed preview, not semantic validity, exact numeric precision, or whole-file equivalence. A complete-package preflight rejects formulas/named definitions, external relationships, and any package parts outside a conservative plain-data allowlist before Excel starts. This is an inspection-policy gate, not a general malware scanner.
- `excel_process.py` locates installed Excel through read-only App Paths registry queries. Its manual `open_in_excel` action uses Windows ShellExecute through `os.startfile` with the explicit Excel executable and a quoted absolute saved-file argument, so CSV associations cannot select a different app. It creates no reader job and performs no workbook writes; the user owns that normal visible Excel window. Launch failures surface in a native error dialog. Background comparison remains separate: It creates Excel and the Python reader suspended, assigns both to a named Windows job, then resumes them. Child interpreters inherit the job. `excel_compare.py` owns all handles, applies kill-on-job-close, and terminates/waits for its job on completion, cancellation, or reader timeout before removing temporary files. There is no process-name sweep. This uses Microsoft's documented [separate-instance Excel switch](https://support.microsoft.com/en-us/office/lifecycle/command-line-switches-for-microsoft-office-products) and [Windows job ownership](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).
- `excel_worker.py` connects xlwings only to the supplied owned Excel PID, disables VBA/events/alerts and automatic calculation, and opens the preflighted temporary copy read-only without link updates or saving. It returns JSON through its temporary result file. It unregisters the pinned xlwings backend's global at-exit zombie sweep and avoids App.quit()/App's context manager because those also sweep unrelated Excel processes. It requests shutdown through the owned COM instance; the parent job enforces cleanup if COM stalls. Source hashes verify that Excel did not change the temporary source.

- `workbook_index.py` streams every worksheet XML row using defusedxml and ZIP package relationships, avoiding dense expansion across blank gaps. It includes hidden rows/columns/sheets, formulas and explicit empty text, ignores style-only cells for bounds, and checks the source SHA-256 before/after scanning. Incorrect dimension hints do not limit discovery. Failures discard that sheet's partial results, retain an explicit per-sheet error, and make the overall index incomplete; cancellation raises rather than returning partial success. Non-worksheet tabs and unsupported XML formats fail explicitly.
- Geometric area suggestions partition contiguous populated row bands by occupied column bands. They do not infer table semantics or headers. After 200 suggestions, the UI uses explicitly combined full bounds while still scanning/counting all cells. Only per-row data, bounded column sets, and the limited area inventory are retained during discovery. Workbook/shared-string value decoding remains in the preview readers.
- `table_structure.py` consumes every stored row during discovery, maintaining separate active column intervals and first/last positions per column. A row gap local to one block closes that block even if a neighbouring table continues. Candidate header masks are retained when columns first appear or the first dense text row appears, rather than retaining the worksheet. Dense text candidates with continuing data across at least 60% of columns suggest a header; single-column/one-row fragments are not inferred as tables. Ambiguous all-text or irregular layouts remain editable guesses. All detected table descriptors are retained; neither finished-table count nor active-block count has a 200-item cutoff. Working profiles retain only coordinates and masks, while the resulting inventory grows with the number of tables.
- `workbook_index.py` reads explicit [SpreadsheetML table definitions](https://learn.microsoft.com/en-us/office/open-xml/spreadsheet/working-with-tables) through sheet relationships, preserving declared ranges and optional header rows. A preliminary streaming metadata pass is used for sheets with table relationships. Declared ranges, including blank rows/columns, are excluded from geometric detection before grouping the remaining cells; this prevents touching plain ranges from being swallowed by an overlapping suggestion. The main scan still counts every stored cell, and verifies table references even when relationships are missing or unsupported. Unsupported/broken definitions fail visibly as incomplete sheet coverage. No source values, formulas, macros, or links are executed to discover structure.
- `ranges.py` defines source-coordinate ranges separately from display pages. `selection.py` records multiple named tables with stable identities, full ranges, and optional header rows per workbook SHA-256 under `.artifacts/selections/`, using an atomic replace. Version 2 settings retain every table and the most recently saved table identity; version 1 single-range settings load as Table 1 without rewriting on read. Page navigation does not overwrite definitions. These local settings contain coordinates, table names, and sheet names, not rewritten source data; they are not the future audit store.
- `navigation_ui.py` owns workbook data-set setup and separate workbook-details window, with coverage, visibility, and expandable suggested areas. A visible per-sheet table list shows all detected ranges and a count, plus Whole sheet. Selecting a group reopens a saved definition only for an unambiguous one-to-one overlap; other saved definitions remain in the saved-table selector. Groups are never automatically accepted or analyzed. Paging and jump controls are mounted beside the grid. The range/header form collapses after saving and reopens through Edit setup; Add another offers the next suggestion not overlapping a saved definition, otherwise full sheet bounds. Blank bands remain in full-sheet or explicit ranges. The default preview uses the largest table suggestion on the first populated readable sheet; no suggestion falls back to full bounds. Restored saved definitions take priority. Editable start/end fields synchronize with the existing source-range state, and accepting a suggestion still requires Save data set. Its saved-table selector, Add another, and Remove table setup actions manage independent definitions, including tables on the same sheet; editing and saving one preserves the others.
- `preview_ui.py` gives the read-only grid the main resizable workspace and keeps setup in an independently scrollable, compact 240-pixel rail with smaller control styles. A green toggle in a persistent narrow strip at the rail's right edge hides/restores the content via the existing grid layout without destroying controls, reloading data, or losing edits. Thin scrollbar styles and smaller paging arrows reduce chrome. Mouse-wheel handling accumulates high-resolution deltas, synchronizes the pinned row strip, and supports Shift-wheel horizontal movement; scrollbar-track clicks center the current preview on the click while native thumb dragging remains intact. Scroll gestures never expand or change the loaded page. Column actions appear after saving and enable on explicit column selection; field edits invalidate action readiness. Full cell details expand on request. The reader selector and technical notes live in the workbook-details window, with concise comparison status and the session reference date remaining visible. The grid uses per-panel zoom styles (80% default, nine choices from 15% to 125%), a separate synchronized row-number strip, explicit full-range endpoints, and Start/End page jumps. Right-clicking a data cell can update either boundary without saving it automatically. CSV retains its reading controls. Reader differences still highlight grid rows. Header promotion reads stored openpyxl values for the chosen row and visible source columns, including off-page headers, in the same background preview worker. Labels retain original column letters, duplicate and empty cells, and the raw header row; this does not infer field meanings or alter records. Its background reader sends results through a queue; closing a preview discards pending results and requests cancellation of discovery and its Excel worker. Discovery progress is reported on the main thread. The 20-row/10-column page remains separate from saved scope and the full-column inspection reader.
- `grid_selection.py` supplies the selected-column visual layer for the native row-based Treeview. It clips to the selected column, reproduces visible cell text with the grid's fonts, marks comparison differences, and forwards pointer/wheel/resize gestures to the original grid. Idle redraws track scrolling, column widths, zoom, and layout; close cancels queued redraws. `preview_ui.py` tracks the source column and worksheet/range context separately from a selected row. Header selection clears row selection, survives row paging and reader changes, and resets on source-scope changes or a cell selection. Analysis still uses the saved complete range; the highlight does not load additional data or change sources.
- `column_profile.py` independently streams one complete saved Excel table column using read-only openpyxl with formulas retained and external links excluded. It verifies the saved content hash before/after reading, includes hidden/gap/tail rows, excludes an explicitly designated header and earlier title rows, and uses the existing `AnalysisSession`. Blank, explicit empty text, numeric zero, text, number, date/time, boolean, source error, and formula remain distinguishable. Unsupported values and unrepresentable-date conversion warnings fail clearly. Temporary SQLite frequency counts keep distinct values off the Python heap; counts are exact across the full selected population, while examples (three/type) and repeated-value display (ten) are bounded. Temporary files are removed after reads and failures. No source values are changed or formula results calculated.
- `column_ui.py` runs that reader in a cancellable background worker and displays its immutable table/session context, complete totals, type counts, repetitions, and source-cell examples. Jump to cell returns to the original range/column. `preview_ui.py` requires an explicit column choice and rejects unsaved table edits before starting; the column dialog holds the table context until it closes. Normal interpreter shutdown lets the cancelled column worker finish temporary-file cleanup without blocking the Tk window-close handler. CSV does not yet have this action. These summaries describe reader values, not financial meaning, missing-token policy, or maturity validation.
- `column_order.py` streams every row and column of the saved Excel/XML data set into a bounded temporary SQLite result while storing the selected column's exact source evidence as the order key. Plain implicit Excel blanks are represented without per-cell records; XML absence is reconstructed from each record path and stable field catalog. Four validated modes provide case-insensitive textual A–Z/Z–A ordering or stored-number-first ascending/descending ordering; missing order states stay last and XML/text identifiers are never numerically inferred. Pages are bounded to 50 rows × 10 columns, source rows remain stable tie-breakers, and source identity checks bracket the read. `order_ui.py` owns background delivery, independent row/column paging, details, source jumps, cancellation, and result cleanup. The Order tab requires an explicit saved Excel/XML scope and order column selected in the analysis tab; it never rearranges or writes the source. CSV remains unsupported because it has no saved complete-data-set scope.
- `column_check.py` applies immutable, explicit type/date settings through the full-column reader's optional per-cell visitor, including implicit blank tails. It returns complete, source-bound counts and every flagged cell with reasons. Stored types, literal identifiers, source errors, and formulas remain distinct; text dates use exact chosen formats only. No value is normalized or written. Temporary SQLite findings support indexed 20-item pages without retaining all findings in Python memory. The caller closes a completed report; failures clean it up before returning.
- `column_check_ui.py` captures a saved table/column/session, requires an explicit expected type, and presents settings, applied-rule context, complete totals, all finding pages, and source-cell jumps. Changing settings invalidates results. A non-daemon worker and coordinated result delivery/close handle cancellation, completed-but-uncollected results, and normal shutdown cleanup. Temporary files under `.artifacts/column-checks/` are not persistent audit outputs. The existing preview reader comparison and xlwings writing policy are unchanged.
- `column_definitions.py` stores explicit Excel column meanings independently of source values and workbook formatting. Immutable definitions contain a snapshot of the selected active dictionary field and code meanings plus source currency/units, accepted text date formats, and mapping-specific rule metadata. Versioned JSON under `.artifacts/column-definitions/<source-sha256>.json` is atomically replaced, size/count bounded, and keyed by the exact saved data-set identity/sheet/range/header plus source column. Historical scopes remain separate, so editing a data-set boundary never silently redirects a mapping. `column_definition_ui.py` supplies the selected-column editor through `preview_ui.py`; it requires an active field in the `default` profile, never infers meaning from a header or Excel format, does not execute rules, and never writes the workbook.
- `mapping_profiles.py` loads bounded, strict, data-only resources from `profile_data/` and exposes an immutable exact-header binding. The initial `warehouse_model.json` profile represents all 94 reviewed source columns, including duplicate-header occurrence numbers, stable keys, expected types, source/calculated/mixed roles, presence, and units. Matching is available only for an unchanged saved `.xlsx`/`.xlsm` data set with a designated header row. The reader hashes before and after, performs OOXML preflight, retains formulas as text, and reads the full saved width rather than the preview page. `preview_ui.py` shows a match through `navigation_ui.py`; no near-match normalization, persistent column-definition creation, rule execution, or workbook write occurs.
- `workers.py` tracks all application-owned tasks, including workers from already-closed/replaced preview tabs. Main-window Exit/close signals read cancellation immediately, closes dialogs, allows an active copy to finish, and polls for zero live workers before destroying Tk. Workers are non-daemon, so resources can close normally. `CancellableReader` checks reads during workbook loading, including before the first cell is decoded. Preview futures, Excel preflight, column checks, and discovery participate in this lifecycle. No unrelated threads/processes are terminated.
- `inputs/<id>/` contains each unmodified session working copy and `manifest.json`. Schema 2 includes `original_path`; schema 1 records from the earlier browser UI remain readable with that field null. Listing checks record structure and saved-source existence/size, not a fresh content hash. `IntakeStore.clear` removes only validated application record directories and leaves unrelated files in a caller-supplied storage folder untouched.
- `scripts/launch_desktop.py` runs in the project-local `pythonw.exe` and sets the working directory to the project before calling the CLI. `scripts/create_launcher.py` creates the per-user Loan Tape desktop shortcut with an explicit runtime/launcher path and working directory; it refuses to overwrite an unrelated shortcut. `create-launcher.bat` recreates it, and `start-ui.bat` uses the same windowless entry point. CLI `--ui` remains supported. No installer, Registry modification, PATH change, browser, or local server is introduced.

The intake boundary accepts extensions .csv/.xml/.xlsx/.xls/.xlsm/.xlsb and files up to 100 MiB, without interpreting their contents. Explicit UNC/network and Windows device source paths are rejected before filesystem access. Normal local changes during copying are detected; this is not an adversarial file-locking or tamper-proof archive guarantee. Downstream services provide workbook discovery, column checks, date interpretation and reviewed text transformations through explicit source adapters. General financial normalization and external service integrations remain future work.

## XML stages 1–4

`xml_preview.py` is a format reader behind `inspection.read_preview`, used by the existing `PreviewPanel`. XML bypasses Excel comparison and workbook navigation. The non-workbook options row offers record-group selection instead of CSV separator/encoding controls, while retaining the same grid, zoom, details, session, and workers. Excel launching is unavailable for XML.

A restricted `DefusedXMLParser` callback target streams the complete document without building a tree. Discovery counts expanded-name paths and identifies repeated siblings; multiple candidate groups require explicit selection, while a document with no repetitions uses its root. A second complete scan extracts the selected group and checks its full structural consistency. Both passes compare SHA-256 identities and check file metadata; cancellation never publishes partial success. The reader does not follow DTDs, entity definitions, schema hints, or stylesheets. Declared encodings are honored.

Each record's uniquely occurring descendants and attributes become columns. Repeated children, mixed content (including inherited `xml:space="preserve"` container whitespace), or nil-with-content produce a visible unsupported-group result, not multiplied rows or silently discarded values. XML names are compared by namespace URI/local name, with stable per-document display aliases. `PreviewCell` carries optional source-path/presence metadata and `FilePreview` carries optional XML group and column labels, preserving other reader defaults. Row numbers are selected-group occurrences, not physical XML lines. Source bytes remain authoritative; parser-decoded text is not a byte-for-byte lexical reconstruction.

Limits: 100 MiB file, depth 64, 1,000,000 elements, 2,048 distinct paths/fields/namespaces, 128 attributes per element, 2,048 characters per expanded name, 1,000,000 characters per direct text/attribute value, and 4,000,000 captured preview characters. Each page contains at most 20 records and 10 fields, with arbitrary positive record/field starts; display limits do not truncate parsing or the full field catalog. Discovery and selected-group extraction run for every page request, retaining only the requested rows/cells rather than a whole document tree or persistent value cache. Source SHA-256 is checked against the current view and across both passes. XML writing remains a separate milestone.

`xml_navigation_ui.py` adds compact group/data-set and paging controls inside the same preview tab. It offers record/field arrows, Start/End, direct jumps, and full group/page counts. Existing grid, zoom, pinned record numbers, literal values, details, tab lifecycle, and worker cancellation remain shared. All parsing runs in the existing worker; controls disable during reads and no failed/partial page is published. Named setups always cover the complete group, not the visible page. Edited names are protected on switching/closing, and settings errors remain visible without silently replacing the file.

`xml_selection.py` stores a versioned XML-only metadata document under `.artifacts/xml-selections/<sha256>.json` using atomic replacement. It records named data set IDs, expanded-name group paths (namespace URI and local name, never ambiguous display prefixes), per-set last-viewed record/field positions, and the active saved set. The source hash keys the entire document; original XML and existing workbook selection schemas are untouched. Settings permit at most 200 sets and 1 MiB; names, identities, coordinates, version, and structure are validated. Successful navigation updates a saved set's view position separately from its full-group scope. Observed settings changes in another window prevent overwriting; this is not a general concurrent-writer transaction store.

### Shared XML column review

`SavedXmlTable` is an immutable, source-bound analysis scope containing data-set identity/name, canonical group path, display group, and complete record/field dimensions. It excludes view positions so page changes do not change the analyzed population. `xml_navigation_ui.py` only supplies it for a saved group with no unsaved name edits; `preview_ui.py` enables the existing Inspect/Check buttons on explicit field selection and routes source jumps by record ordinal plus full field ordinal. XML examples/findings return to the same tab; stale group scopes are rejected.

`xml_column.py` dispatches behind the shared `column_profile.inspect_column` service. It runs the restricted XML callback parser twice: first for complete group/field discovery and source verification without capturing preview rows, then for streaming the selected field once per record. Only the requested field's text is held per record; absent fields produce explicit evidence, including when a field appears late. Full-file structural checks, parser limits, namespace aliases, source hashes, cancellation, and final row/field reconciliation prevent partial success. No per-page rescanning or whole-document value cache is used by column analysis.

`ColumnAccumulator` is shared with the existing Excel reader and keeps exact frequencies in temporary SQLite. `ColumnExample` gains optional source-path and presence metadata, and `ColumnProfile` accepts Excel or XML scopes without disguising XML records as worksheet ranges. Excel stored-type classification, formula handling, numeric zeroes, blank tails, headers, and identity checks remain unchanged. XML counts absent/empty/nil/empty-text/text states, literal text zero, and whitespace separately. Missing states are excluded from frequencies. Original decoded text and first source occurrence survive into examples and repetitions.

`column_check.py` shares required/text/date checking, staged finding storage, result paging, and cleanup. An explicit `Plain decimal text` number rule validates syntax without numeric conversion; the XML dialog selects that rule when Number is chosen. XML Date requires an explicit text convention and never claims a stored Excel date. Existing Excel defaults remain `Stored numbers only` and `Excel dates only`. Every finding retains XML path and presence through SQLite paging. Each XML analysis database is limited to 512 MiB; storage failures clean up and fail visibly. Shared worker, dialog-delivery, cancellation, and source-jump safeguards apply to both formats. No schema, dictionary-pack, financial, export, or normalization behavior is introduced.

### Optional XSD validation

xml_schema.py uses xmlschema and elementpath behind an explicit **Validate XSD…** action. It auto-selects XSD 1.0 or 1.1 from the chosen schema document, compiles in strict mode, and validates a lazy XMLResource with default insertion disabled. The instance resource uses entity protection, no location hints, and no URL/file resolution. Schema compilation uses entity protection, disables fallback locations, and permits imports/includes only in the selected schema directory sandbox. XML-provided schema hints are never consulted.

The service hashes the exact preview source before and after validation. It fingerprints the main XSD and every loaded user schema inside the selected folder, enforces 25 MiB per schema file and 100 MiB across that local package, and checks the same resource set again before publication. Library meta-schemas are excluded from the user package identity. Source/schema changes, compilation failures, blocked resources, malformed data, cancellation, and storage failures publish no complete result.

All validation findings stream into temporary SQLite under .artifacts/xsd-validation/, capped at 512 MiB, and remain available in pages of 50. A finding stores its XML path, optional source line, validator category, and reason. xml_schema_ui.py owns worker/result-delivery cleanup and removes temporary data on close, cancellation, failure, preview replacement, or app shutdown. The selected XSD path is session-local; XML, schemas, saved record groups, dictionary packs, and column-check behavior are unchanged. The service is format-generic and contains no MISMO model logic.

## Independent dictionary packs

`pack_format.py` validates a versioned four-file JSON contract and returns immutable packs, fields, code lists, and source references. It rejects unsupported metadata, duplicate keys/IDs, dangling references, and unsupported types. Packs are data only: source documents and scripts are not loaded or executed.

`packs.py` discovers editable pack folders, reports per-pack errors and duplicate identities, maintains named activation profiles, and exposes searchable catalogs with fully qualified field IDs. All packs default to inactive. Activation atomically saves exact-content snapshot references under `.artifacts/packs/`; a store-wide exclusive writer lock prevents lost concurrent updates. Content fingerprints are verified on snapshot reads. Source edits require explicit reactivation; deactivation retains earlier snapshots. No reference-file hashes are re-verified by the loader.

`pack_cli.py` provides list/validate/show/activate/deactivate/catalog/search commands. `cli.py` dispatches only an explicit `packs` command to it. Existing intake, preview readers, selection, session, and ad-hoc column-checking services remain independent of the pack backend. The column-definition and date workflows explicitly request active fields. No runtime dependency was added.

`pack_manager.py` creates read-only management views with independent editable/snapshot errors; missing or invalid source folders do not prevent deactivation. `pack_ui.py` presents a separate native dialog, field search, type/code/source details, and explicit profile controls. It performs reads and writes through the shared `WorkerGroup`, waits for an in-progress operation on close, and never passes pack state to a file preview. UI activation supplies the displayed content fingerprint; changed files require refresh and review. A failed profile load clears the view and disables mutations until refreshed.

`pack_authoring.py` constructs independent drafts, records copied-pack identity and local field authorship, and validates field edits without requiring completed pack metadata. Whole-pack saves validate the existing four-file contract and check the editor's original fingerprint before replacing a folder. Editing and activation share the store writer lock; activation rechecks the source fingerprint under that lock to reject reads spanning a publication. These locks coordinate application operations using the same state directory, not arbitrary external editors.

Publication stages four validated regular files in the same packs root, renames the previous folder into `.history/`, then publishes the staged folder. A normal rename failure restores the previous folder. Failed restoration reports and retains both the backup and staged content. The two directory renames are not a crash-atomic transaction; a crash between them may leave the ordinary source folder missing until restored from `.history/`. Active snapshots are separate and remain unchanged. Linked folders/files, extra folder contents, path escapes, duplicate pack IDs, and stale edits fail without overwriting the source; custom copies can be used instead. History and `.draft-*` staging folders are excluded from Git and builds and rejected by archive validation.

`pack_editor_ui.py` presents pack metadata and field forms with explicit tri-state presence/blank metadata, aliases/context, and selections from existing code lists. Pending field edits apply before switching fields or saving; invalid drafts stay open. Save runs in the shared worker group and refreshes the manager after successful publication. Unsaved drafts guard dialog/manager/application close. A close request during an editor save is deferred to the user until the save finishes, so a failed save cannot silently lose the draft. `pack_content_ui.py` adds source and allowed-value management tabs and isolated content dialogs. Pending value/citation rows apply before switching or accepting; incomplete or invalid rows remain open. These dialogs participate in unsaved-close protection and apply only to the parent draft. Field list selectors refresh after content changes without discarding pending field edits.

`pack_content.py` validates independent source, code-list, and citation edits against the existing four-file format. Source/list IDs remain stable within an edit. In-use sources/lists and explicitly selected missing codes cannot be removed without first updating their references. Source locations and optional hashes remain unverified metadata; no source file is opened. Application authorship/copy records are protected in the editor. New or changed code definitions receive a local authorship citation, retain earlier citations as background, and bind to the earlier pack fingerprint when applicable. Empty intermediate drafts are allowed without persisting placeholder content; whole-pack save still requires a field or code list.

See [PACKS.md](PACKS.md) for the format and current scope. General pack-driven check execution and normalization remain future work. The current Excel editor saves only explicit source-bound column definitions and rule metadata; the separate Warehouse Model profile performs read-only exact-layout recognition and does not create those definitions. Starter pack source folders are project reference files; an installed wheel accepts external folders through `--packs-dir`.

## Planned data flow

```text
Supplied CSV / XML / Excel workbook + immutable copy and manifest
    -> CSV structure / XML record discovery / workbook inspection and raw evidence
    -> reconstructed records + explicit field mappings
    -> normalized positions + field lineage
    -> applicable validation rules + findings
    -> review decisions + recorded changes
    -> reconciliation + CSV / Excel exports
    -> independently reviewed taxonomy evaluation
```

The CSV, XML, and Excel adapters should emit common evidence and lineage structures. XML needs namespace-aware node/attribute paths and occurrence identities alongside the source hash. Preserve CSV record/column locations and workbook sheet/cell addresses explicitly. A source record may contribute to several positions, and several source records may contribute to one position; preserve those relationships explicitly.

PDF extraction and conversion functionality already exists separately. A later integration phase will connect that existing work to this pipeline after reviewing its capabilities and output contracts. PDF/OCR processing is outside the current implementation scope; the current intake boundary is the supplied CSV, XML, or workbook. Record known upstream provenance when available, but do not claim verification against an earlier document that this application has not inspected.

Keep extraction, interpretation, normalization, validation, review, reconciliation, and export separately testable. The eventual CLI and UI call the same application services. Start with a single package and introduce modules when their features are implemented.

## Date foundation

`date_parser.py` owns immutable `DateSource`, `DateEvidence`, `DateProfile` and
`DateResult` contracts. Profiles serialize independently of dictionary definitions
and have deterministic content fingerprints. Parsing is a pure operation with
explicit formats and policies; it uses Gregorian dates and exact decimal serial
arithmetic, never a system date pivot, locale guess, timezone shift or calendar rule.
`packs/loan-dates/` uses the existing pack format and remains inactive by default.

`date_reader.py` reads complete selected Excel date columns directly from OOXML before
any date conversion. One batch opens package metadata, shared strings and styles once
and streams the selected worksheet once for every requested column; the single-column
API is a compatibility wrapper over that path. It reuses source selections, coordinate
validation, hashing, cancellation and package-path handling. It preserves numeric
serial tokens (including fictitious day 60), shared/inline text, number formats,
formula metadata and source locations. Bounded package/row sizes and whole-sheet
validation precede atomic publication; source hashes are checked before/after. No
Excel process or source calculation runs. This API is separate from current column
checks and the preview reader.

See [DATES.md](DATES.md) for supported representations, limits and outcome semantics.
`date_standardization.py` is the boundary between source import/interpretation and
red-flag review. It binds explicit definitions/profiles to complete saved-table
columns, retains every parser outcome in an immutable in-memory handoff, verifies
source lineage and catalog snapshots, and emits no findings. `date_analysis.py`
consumes that versioned handoff through `analyze_standardized_dates`, validates exact
mapping identity, recomputes from retained evidence, applies separate required-value,
bound, reference, pair and calendar policies, and emits versioned findings. No
combined import-and-review entry point remains.
`date_calendar.py` supplies a sourced SIFMA snapshot with exact published coverage
and unknown uncovered weekdays; `calendar_data/sifma_us_fixed_income.json` is the bundled factual resource.
`date_runs.py` atomically saves new self-contained JSON runs, validates fingerprints,
and verifies full deterministic replay without consulting current source folders.
The service limits are 200,000 mapped cells and 128 MiB per saved run. No source
value is adjusted. `date_workflow.py` uses distinct mapping/interpretation and
red-flag setting builders. `date_workflow_ui.py` coordinates a parser-only Import &
standardize action, then a separate Red flags action, run saving, finding review,
source jumps and export. A changed mapping/profile invalidates the handoff for
downstream review. See [DATE_ANALYSIS.md](DATE_ANALYSIS.md).

## Rate foundation

`rate_parser.py` owns immutable `RateSource`, `RateEvidence`, `RateProfile`,
`RateCandidate` and `RateResult` contracts. Parsing is pure and uses `Decimal` for all
values, unit conversions and source/canonical resolution. Spreads use decimal basis
points as their canonical unit. Coupons, reference-rate observations, floors, caps and
yields use decimal rates. No accepted value is quantized or rounded.

Profiles version explicit unit policies, missing tokens, syntax controls and
source-specific benchmark aliases independently of the dictionary. Unitless values
produce all applicable candidates when no policy establishes a unit. Formula, stored
error, missing and unsupported source states remain distinguishable. Composite
benchmark-plus-spread parsing preserves both the source token and stable configured
benchmark identity; it does not supply method, tenor, observation date or agreement
meaning. `packs/loan-rates/` uses the existing pack format and remains inactive by
default.

This Phase 1 module has no complete-column reader, mapping service, distribution-based
inference, cross-field rule engine, market-data integration, UI, persistence or export.
Those boundaries keep later pool analysis separate from deterministic scalar
interpretation. See [RATES.md](RATES.md).

## Excel writing policy

Use xlwings as the primary writer for creating, editing, formatting, and exporting Excel workbooks. Keep data transformations independent of the writer; the writer publishes the explicitly prepared result into a separate working copy or output file, preserving both the original source and the intake copy.

An operation may use openpyxl when xlwings does not support it or fails, provided the fallback preserves the required values and workbook features. Record the selected engine and the specific fallback reason, expose fallback use in the result, and validate the saved output. Unsupported preservation requirements must produce an explicit error. Do not treat fallback as permission to silently omit features or lose data.

`date_export.py` now applies this policy to saved date runs. It reads the complete, hash-matched saved data-set range without calculation, applies only successful standardized dates, and retains unresolved and unmapped source values literally. It then launches a hidden, job-owned Excel process and `date_export_worker.py` writes a new values-only workbook whose first sheet is the complete refined loan tape, followed by the review and audit sheets. The source is never opened by the writer; there is no openpyxl writing fallback. Openpyxl validates the staged and published output for identities, sheet order, complete selected-range cells, applied-date reconciliation, literal source text, and absence of formulas, links, macros, or connections. Existing inspection readers and preview comparison remain unchanged. Source formula/macro execution and link refresh remain prohibited.

## FinExtract foundations

Reference repository: `zarikkhimani/Financial-Statement-Extract`.
Reviewed revision: `26985d12fd257a70931af3d017785ce49c9f610f`.

Carry forward local processing, a thin interface, source/normalized separation, structured audit findings, literal spreadsheet text, non-overwriting exports, packaging, and automated checks. Consider its workbook presentation patterns when implementing review exports.

Review each code reuse against the new requirements. Its statement mapping, numeric parsing heuristics, currency assumptions, and statement-specific checks do not establish loan-tape semantics. Financial amounts and rates need explicit precision/rounding policies. Supported unit conversions here must preserve original representations and record the transformation.

The desktop follows FinExtract's Tkinter/ttk, native-drop, and main-thread/worker separation patterns. Its implementation is written for Loan Tape; no FinExtract application code is copied or imported. Record origin and any applicable license notices if code is later copied.

## Runtime and dependencies

### Canonicalization Phase 1

`scripts/probe_canonicalization.py` orchestrates optional compatibility checks in
separate `.tools/canonicalization-probe/` and
`.tools/canonicalization-dedupe-probe/` environments, using the root `uv.lock` and
explicit dependency groups. Normal setup installs neither group. The probes
co-install the application runtime requirements without installing the application,
run synthetic cases through `_canonicalization_cases.py`, record package/license
metadata, and compare the ordinary `.venv/` package inventory before and after.
Failures remain nonzero with per-profile evidence; Dedupe source builds require an
explicit probe flag and do not install host tools.

The reviewed future contract keeps engine-neutral processing separate from native
UI, original evidence, dictionary meanings, staged derived results and exports.
ftfy supplies Phase 3 proposals; RapidFuzz supplies Phase 4 suggestions. Exact approved rules belong to
Loan Tape because the evaluated DataPatch API strips whitespace. No Node/Java
service or sibling workspace becomes a runtime requirement. See
[Canonicalization integration](CANONICALIZATION.md) for decisions and boundaries.

### Canonicalization Phase 2

`transformations.py` supplies immutable canonical JSON snapshots, full-population
cell decisions, operation metadata, explicit approvals and derived revision history.
It verifies parent histories and previews by deterministic replay, retains every
mapped cell and checks actual serialized payload sizes. Engine proposals are literal
data; cleanup engines and UI remain separate. Eligible changes affect only mapped
free-text cells and cannot reinterpret missingness or identifiers. Phase 4 adds
category eligibility only under its versioned exact-rule policy and frozen code list.

`transformation_excel.py` adapts the existing raw OOXML evidence reader, checking
the saved selection, active dictionary snapshots and duplicate/blank header evidence.
Publication re-reads current inputs, stages a full revision, checks the source hash
again and uses no-replace atomic hard-link publication. Session records live under
`.artifacts/transformations/`; `workspace_reset.py` removes only validated filenames
belonging to preserved intake sources after workers stop. Loading requires the source
and current mappings, then verifies the complete revision by replay. The Phase 3
desktop adapter calls these APIs. The foundation's installed-wheel smoke test executes the synthetic
read/preview/approve/publish/reload/reset path without the optional probe engines.

### Canonicalization Phase 3

`text_cleanup.py` pins ftfy 6.3.1 and every effective setting, proposes repairs for
one explicitly mapped text column and records engine/configuration evidence.
Application regenerates the exact preview with current inputs and rejects stale
approval. A final guard checks the saved data set, mappings and active catalog
after staging and before publication. The source hash is independently rechecked.
The inactive `loan.text` pack supplies project-authored name definitions without
altering pack schema or identifier semantics.

`text_cleanup_ui.py` owns settings, full-population counts, paged decision review,
explicit per-cell choices, reviewer/reason and source jumps. It uses the application's
WorkerGroup for cancellable preview/application and orderly shutdown. Scope, mapping,
dictionary or setting changes invalidate review. `preview_ui.py` keeps one current
revision per data set while that preview panel remains open; **Start from source**
clears that selection while retaining earlier session evidence. Source grid values
remain original. Phases 5 and 6 supply persistent recipes and text-result export;
a saved-run browser remains future work. Tests exercise the real engine, native controls and worker shutdown; a
second installed-wheel smoke test executes actual ftfy and exact-rule application/replay.
See [TEXT_CLEANUP.md](TEXT_CLEANUP.md).

### Canonicalization Phase 4

`text_rule_types.py` defines immutable literal rules and policy validation without
importing a UI or similarity engine. `transformations.py` recognizes only the
versioned `exact-text-rules` operation for category replacements, validates every
target against frozen allowed values and requires complete, matching proposals on
both initial preview and replay. Rules are simultaneous in a step. Duplicate keys,
no-op/blank/over-limit rules and mapped missing tokens fail explicitly.

`text_rules.py` executes these maps and calls pinned RapidFuzz's compiled ratio
scorer for suggestion-only comparisons. It counts the complete current free-text
column, caps distinct values at 10,000, compares one explicit source spelling, and
orders candidates by score descending then literal text ascending. Optional NFC
plus casefold affects comparison only. Every selected suggestion retains its score,
settings, Unicode/scorer versions and snapshot/parent/corpus identities in the rule.

`text_rules_ui.py` edits session drafts in the existing cleanup dialog. It has an
owned cancellable search worker, 200-candidate pages, no preselection, exact literal
inputs, a category allowed-value view and stale-context guards. Accepting rules
invalidates the prior cell preview/choices; it does not run or approve a preview.
Closing the editor discards unaccepted edits. Closing Clean text discards its rule
draft; applied rule evidence remains in the session revision until normal Exit.
Rules, repairs and later previews share the same source-preserving adapter and
atomic publication guards. No persistence or export feature is added here.

### Canonicalization Phase 5

`recipes.py` captures reviewed operation histories as immutable, strictly validated
JSON recipes. Portable steps retain pinned settings and literal rules but remove
old source/approval/similarity evidence. The schema records relative mapped columns,
literal headers and duplicate occurrences, frozen definitions and selected width.
The source/template profile and applicability are explicit. Save publishes one
ID/version file without replacement under `.artifacts/recipes/`; normal Exit retains
these files. Library reading and serialized recipes have independent resource bounds.

`recipe_execution.py` requires a fresh source/profile/schema binding and explicit
context/reviewer confirmation. It adapts relative columns, starts from original
source evidence and stages each approved step in memory. Final application re-reads
the current source/mappings, runs every configured engine again and checks all
approved previews before publishing one complete revision. A failed or cancelled
step publishes no partial history. `recipe_context.py` validates per-operation
recipe/binding attribution and complete ordered recipe histories without importing
engines, UI or Excel export code. Persistence, export and borrower matching share
the completion check; partial histories remain in memory during review. Later
ordinary cleanup retains that evidence. Completed recipe archives retain the full recipe
and binding, validated during both publication and loading.

`recipe_ui.py` provides explicit capture/save/load, metadata editing, step ordering
and compatibility confirmation. `recipe_run_ui.py` reuses the existing native cell
review controls for each step, with fresh choices and an explicit reject-all path.
Only a completed run replaces the owner's working result. Owned workers, source
invalidation, cancellation and shutdown clear staged runs. Service tests, native
workflow tests and the installed-wheel text smoke cover reuse on a new synthetic
source, retention, complete-run publication and failure handling. See
[Reusable cleanup recipes](RECIPES.md). Phase 6 supplies text-result export.

### Canonicalization Phase 6

`text_export_payload.py` replays the current approved revision, checks complete recipe
chains and reads the entire selected range through the raw OOXML evidence reader.
It applies only the final approved text overlay. Optional date composition requires
the same source/selection, current dictionary snapshots, compatible shared mappings,
matching original evidence and nonconflicting changes. The resulting workbook retains
all selected cells, full original evidence and complete replayable text/date audit
histories. Canonical JSON audit records use numbered chunks; payload and row bounds
are enforced while assembling evidence and checked again before writing.

`text_export.py` captures current scope/catalog, checks the selected date-run file,
stages the output, then validates and publishes without replacing a target. Failure
cleanup removes only the output linked by this attempt, preserving competing files.
`text_export_excel.py` uses existing process/job launch helpers, cancellation and
bounded shutdown. It validates every saved value/type, complete dimensions, sheet
order, and absence of formulas, macros or external relationships. The new
`text_export_worker.py` reuses the date writer's literal bulk-writing and formatting
helpers in a separate owned process. Source tokens and ISO dates are literal text;
it does not convert financial numbers or copy source workbook features.

`text_export_ui.py` exposes an explicit export action for the current working result,
an unchecked optional date-run inclusion, cancellation and manual output opening.
Owned workers and stale context guards follow the existing desktop lifecycle.
`check.bat --excel-smoke` adds actual text/recipe/date export, cancellation and timeout
through the isolated installed wheel. Ordinary checks need no desktop Excel. See
[Reviewed text export](TEXT_EXPORT.md).

### Application baseline

Python 3.12 with Tcl/Tk is the desktop baseline. `uv.lock` records tkinterdnd2, openpyxl, defusedxml, xmlschema, ftfy/wcwidth, RapidFuzz, Windows-only xlwings/pywin32, their transitive dependencies, and development tooling. Windows is the initial local development target. CI is configured for Windows and Linux; successful execution on each system must be established separately.

The optional comparison requires locally installed desktop Excel; it does not require an add-in, xlwings PRO reader, or an LLM. `scripts/smoke_excel.py` exercises that integration explicitly; standard checks do not require Office.

Add further CSV and workbook tools only as their processing features are implemented. PDF parsers, OCR engines, and conversion/model dependencies are outside the current dependency scope. No cloud provider or model service is selected.

## Evidence and operations

Implemented date-analysis calendar screening follows the packaged [SIFMA calendar guidance](../src/loan_tape/guidance/SIFMA_CALENDAR.md). SIFMA is the sole built-in U.S. fixed-income calendar provider. Keep deterministic weekday calculation separate from versioned published holiday evidence and activity/agreement applicability. Results bind source dates to calendar versions; uncovered weekdays remain unknown and are never projected. The policy and verified schedule data are distributed as package resources. Screening is available through the date-analysis API and complete-data-set desktop workflow; the simpler one-column checks keep their prior behavior.

Keep real sources and generated run data outside version control. Date runs record source hashes, schema and engine versions, dictionary/mapping/calendar snapshots, parameters, and result identities. Transformation revisions retain original evidence, proposals, approvals and parent histories under the Phase 2 contract. A matching total alone does not prove correct row or column association. Failed or quarantined records must remain visible in reconciliation.
