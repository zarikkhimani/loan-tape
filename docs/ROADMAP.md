# Roadmap

Current input scope is CSV, XML data files, and Excel workbooks. PDF extraction and conversion functionality already exists separately and will be integrated in a later, separate phase. The current milestones do not depend on that integration.

## 0. Repository foundation

Deliver project instructions, product and architecture documentation, a package/CLI skeleton, a dependency lockfile, local setup/check commands, and CI configuration.

Acceptance: clean setup succeeds; help/version work; unsupported processing fails explicitly; format, lint, types, tests, build, and installed-wheel checks pass locally. Hosted CI is verified after an authorized push.

## 0.1. Local file intake (implemented)

Provide a native desktop intake window ahead of the analyst-review UI. Save unchanged CSV/Excel session copies with hashes and manifests, retain duplicate names separately, show current-session history, and copy either original or saved locations. Keep earlier records with unknown original paths readable until the next normal session reset.

Acceptance: byte preservation, safe filenames, independent duplicate uploads, explicit errors, cleanup after interrupted uploads, original path lineage, source-change detection, native drop/file-picker/clipboard checks, and safe window shutdown. Analysis and content validation remain in later milestones.

## 0.2. Simple file preview (implemented)

Select Inspect file to read the saved CSV/.xlsx/.xlsm copy into a read-only grid, up to 20 rows and 10 columns. Include sheet selection, explicit CSV reading controls, cell details, and clear errors for unsupported or unreadable files. Keep row 1 and source positions; do not infer header meanings or clean data.

Acceptance: synthetic CSV quoting/encoding/leading-zero cases, genuine XLSX/XLSM workbooks, formula/cached-result behavior, sheet switching, preview limits, source preservation, native UI behavior, and installed-wheel preview pass. This does not complete milestones 1 or 2; complete raw evidence, mappings, financial rules, and reconciliation remain later work.

### Parallel Excel comparison (implemented)

Run openpyxl and xlwings concurrently for eligible plain-data .xlsx/.xlsm workbooks on Windows with desktop Excel. Switch readers and show preview-value differences without correcting data. Reject source formulas, macros, external features, and unsupported package content before Excel opens the disposable copy. Expose unavailable/skipped comparisons while retaining the primary preview. No LLM or add-in is required.

Acceptance: concurrent-reader and difference cases, full-package inspection gates, timeout/cancellation cleanup, native reader selector, and a separate opt-in real Excel smoke test using synthetic workbooks. This comparison remains limited to the bounded preview.

## 0.3. Whole-workbook navigation (implemented)

Scan physical cells across all worksheets without a fixed top-left window. List visibility, actual stored-content bounds, cell counts, suggested areas, and explicit coverage errors. Allow all-data or arbitrary range selection, optional header-row designation, paging, and jumps while preserving original coordinates. Save complete table ranges against the source content hash independently of the visible page.

Acceptance: distant and maximum Excel coordinates, hidden tabs/rows/columns, blank gaps and multiple areas, incorrect dimensions, formatting-only sheets, malformed/unsupported tabs, cancellation, preserved source bytes, native navigation/selection restoration, and installed-wheel navigation. A separate desktop Excel check compares distant pages through both readers. Complete discovery concerns cell locations; basic full-column inspection is available below; financial analysis, combined datasets, and complete raw evidence remain later work.

## 0.4. Independent table headers (implemented)

Save multiple named tables per workbook, including tables beside or below one another on a single sheet. Each has an editable full range and optional source header row. Promote a selected preview row into column labels, retaining Excel letters and raw header cells. Switch, revise, or remove definitions without rewriting source data or changing other tables. Preserve earlier single-range settings.

Acceptance: native multi-table creation, independent header changes, off-page headers in both row and column navigation, blank/duplicate headers, reopening, removal, invalid-header rejection, unchanged source bytes, atomic persistence, and legacy migration. This feature defines table structure only; financial column analysis and data cleaning remain later work.

## 0.5. Session date reference (implemented)

Capture the computer's local startup date/time once per desktop launch, preserve the UTC offset and equivalent UTC timestamp in a separate local record, and share that fixed reference date with every file preview. Show the reference date and startup time in the main window. A new launch creates a new record; opening files never resets the current session.

Acceptance: local versus UTC calendar-day boundaries, daylight-saving offsets, distinct repeat launches, visible shared context, session records, exit reset, and explicit recording failures. Explicit text-date checks, user-chosen year limits, and optional past-date flags are available in milestone 0.7. Complete multi-column date mapping, same-row pairs, and calendar review are implemented in date workflow steps 3-8. Loan economics and agreement-specific contractual interpretation remain future work.

## 0.6. Inspect one complete table column (implemented)

Choose a saved Excel table and a column. Count every data row below its designated header (or all range rows with no header), including hidden cells, gaps, and blank tails. Show filled/blank/empty-text counts, stored types, numeric zeroes, whitespace-only text, and exact repetition counts. Supply bounded examples and common repeated values with source-cell jumps. Preserve the session reference date and prevent unsaved scope edits from silently using an old range.

Acceptance: full ranges beyond preview limits, distant and maximum worksheet coordinates, hidden cells, separate stacked/side-by-side tables, empty/header-only ranges, literal identifiers, distinct source types, formulas without evaluation, large distinct-value counts, source hashes/unchanged bytes, cancellation/read failures, native button/navigation flows, and installed-wheel inspection. Cleaning, financial interpretation, and CSV column inspection remain later work; explicit date checks are available in milestone 0.7.

## 0.7. Check one complete table column (implemented)

Choose a saved Excel table column and explicitly select Identifier, Text, Number, or Date. Review incompatible stored types, optional required-value findings, surrounding text whitespace, source errors, and formulas without evaluation or source changes. Date options include exact text conventions, optional inclusive year limits, and an optional comparison with the fixed session reference date. Keep all findings accessible in pages of 20 with source-cell jumps; changing settings invalidates prior results.

Acceptance: every selected row including distant/hidden cells and blank tails, complete finding pagination beyond preview limits, zero versus text/boolean distinctions, preserved identifiers and missing-value tokens, explicit ambiguous-date conventions and calendar validity, date/reference boundaries, independent table scopes, source hashes, unchanged files, cancellations/read failures, temporary cleanup including shutdown races, native controls/navigation, and installed-wheel checks. Settings are local to the dialog. Financial meaning, persistent rule profiles, cleaning, CSV column checks, and exports remain future work.

## 0.8. Desktop launcher and complete shutdown (implemented)

Provide a per-user Loan Tape desktop shortcut, recreate command, project-root working directory, and windowless startup. Main-window Exit/close cancels reads, closes child dialogs, finishes any active intake copy, waits visibly for owned workers, and removes file-session working copies and source-linked state. Track workers from retired windows. Own Excel and Python helper processes from startup and stop only those process trees.

Acceptance: launcher works from another directory, real GUI close exits all its interpreter processes, unrelated shortcuts are preserved, file copies finish, readers cancel during load, old-window workers are accounted for, file-session state resets without removing originals/exports/packs, reset failures remain visible, and cancellation/timeout releases owned job processes. Opt-in real Excel tests verify startup cancellation, completed reads, source preservation, session cleanup, and pre-existing Excel process survival. No host installation or persistent system configuration change is required.

## 0.9. Ordered desktop inspection workflow (implemented)

Put the worksheet first, with a left-side sequence for sheet selection, table setup, and column review. Collapse setup after saving, explain Inspect versus Check, and keep diagnostics and full cell metadata available on request. Preserve arbitrary ranges, multiple independent tables, and the 20-row/10-column display page.

Acceptance: native minimum-size grid visibility, setup/save/edit/action gating, details reveal and reader switching, full-sheet reset for another table, distant paging, multiple-table restoration, column checks, and existing shutdown tests. Synthetic window captures verify the layout without using portfolio data.

## 0.10. Suggested tables and visible boundaries (implemented)

Suggest complete table ranges and likely headers from the full sparse worksheet scan; prefer explicit Excel table definitions. Preview a suggestion as an unsaved draft, allow start/end/header edits, preserve saved user choices, and offer all-data navigation. List every detected table separately on the selected sheet, with independently editable boundaries and saved-group navigation. Compact the grid with adjustable zoom down to 15%, pin row numbers, and make both table endpoints visible and directly reachable.

Acceptance: titles versus dense headers, distant/hidden tables, stacked tables beside taller neighbours, independent ending rows, blank cells, explicit tables with blank tails, numeric rows without invented headers, more than 200 separate tables, touching declared/plain tables, the last worksheet row/column, native edits/save/restore, next-unused suggestions, source preservation, zoom without changing the 20-row/10-column page, and visible ending row/column coordinates. Suggestions are structural guesses, not automatic financial analysis.

## 0.11. Compact data set controls (implemented)

Call application selections data sets, preserving saved settings and the distinction from actual Excel tables. Compact the left-side controls and page arrows, add a green collapse/restore button, and make current-preview scrolling faster with thinner bars, direct track jumps, Shift-wheel movement, and accumulated high-resolution wheel deltas.

Acceptance: native collapse/restore geometry and retained state, row-strip synchronization, wheel and track movement without page/scope changes, low zoom compatibility, existing saved-selection restoration, and normal shutdown. This does not add whole-data-set scrolling or write Excel objects.

## 0.12. Clear column selection (implemented)

Keep the sidebar toggle on a persistent strip at the panel edge. Clicking a heading selects the complete data set column and highlights its visible cells, with its full source range stated below the grid. Preserve selection through row paging, reader switches, zoom, and layout changes; selecting a cell restores cell-level interaction.

Acceptance: native heading gestures, correctly clipped highlight geometry, forwarded cell/wheel interactions, synchronized row numbers, low zoom, row paging, visible collapse/restore control, existing full-column inspections/checks, and cleanup of scheduled redraws. Source values and analysis scope remain unchanged.

## XML stage 1. Existing-window preview (implemented)

Accept XML through existing intake and preserve its original bytes/manifest. Read XML into the existing CSV-style preview grid, including text values, attributes, uniquely nested fields, namespace-qualified labels, and source details. Automatically select a sole repeated group (or the root for a non-repeating document); multiple groups require a record-group choice. Preserve absent, empty, nil, whitespace, and zero distinctions. Do not flatten repeated child groups or mixed content silently.

Acceptance: synthetic source preservation/reopening, encodings, namespace aliases, ambiguous and nested groups, malformed trailing content, late fields, parser/resource limits, cancellation, native Browse/drop/group switching/error/close flows, unchanged CSV/Excel regression checks, and installed-wheel XML preview. Parsing covers the complete file; the display remains bounded to 20 records and 10 fields. No schema or financial validity is claimed.

## XML stage 2. Complete navigation and saved groups (implemented)

Page through every record and field of a supported XML group in the same preview tab, retaining full counts, source paths, stable field ordering, and explicit missingness. Add record/field arrows, Start/End, and direct position jumps. Save multiple named whole-group data sets independently of the visible page, restore each saved view position, rename/remove definitions, and restore the active saved group when reopening identical source content.

Acceptance: every position across row/field page boundaries, fields first appearing late, namespace-qualified identities, invalid/out-of-range jumps, complete-file checks outside the current page, source changes between requests, atomic metadata failures/corruption, independent sets, unchanged XML and workbook settings, native switching/restoration/close guards, minimum-width controls, and installed-wheel paging/save/reopen checks. Complete parsing remains bounded by the XML reader limits and cancellable. No whole-document value cache or dependency change is introduced.

## XML stage 3. Shared full-column inspection and checks (implemented)

Use saved XML groups with the existing Inspect column and Check column dialogs. Stream every record of the selected field independently of preview pages. Preserve absent, empty-element, nil, empty-attribute-text, whitespace, literal zero, and exact text distinctions; count repetitions with complete coverage and source-linked examples. Check explicit Identifier/Text, plain-decimal Number text, and exact Date conventions with optional existing year/reference rules. Keep every finding available in pages, and jump to its record and field in the same preview.

Acceptance: distant fields/records and late fields, namespace collisions/attributes, nested group isolation and source occurrences, exact zero/identifier/precision/token distinctions, all finding pages, explicit invalid number/date cases, source/scope changes, staged complete-result publication, storage limits, cancellation/shutdown cleanup, native action gating/settings/jumps, unchanged Excel regressions, and installed-wheel XML review. Shared counts, rules, result storage, dialogs, and workers remain independent of schema validation and financial interpretation.

## XML stage 4. Optional local XSD validation (implemented)

Add **Validate XSD…** to the existing XML preview. Require an explicitly selected local main schema, detect XSD 1.0/1.1, compile its local package in a directory sandbox, and validate the complete XML independently of record-group paging or saved data sets. Ignore XML schema hints and block network/outside-folder imports. Show a clean match or every schema finding in pages with paths, optional lines, categories, and reasons. Bind results to hashes of the XML, main XSD, and loaded local schema files without changing any source.

Acceptance: valid and invalid complete documents, more findings than one page, local includes, XSD 1.1 selection, ignored remote instance hints, blocked schema escapes, malformed/unsafe schemas, source/schema changes, file/result limits, cancellation/shutdown cleanup, explicit native selection and result states, unchanged stage 1–3 behavior, generic MISMO-package compilation, and installed-wheel validation. Mapping, normalization, reconciliation, and exports remain shared application work; no MISMO model logic is introduced.

## 0.13. Independent dictionary pack backend (implemented)

Provide a strict JSON pack format, editable local pack folders, an immutable source-referenced catalog, and explicit activation/deactivation by named profile. All packs start inactive. Active content is snapshot-pinned, so editing/removing a source pack does not change prior selections. Keep the backend disconnected from existing desktop inspection and checks.

Acceptance: valid starter packs, visible malformed-pack and duplicate-ID errors, no automatic activation, independent profiles, exact-content fingerprints, saved-state reopening, snapshot tamper/missing-file errors, safe deactivation, atomic publication failures, and installed-wheel lifecycle checks. Pack-driven analysis, inheritance/overrides, and data-set bindings remain later work.

## Desktop workspace tabs (implemented)

Keep intake and the current file preview in one native window, with Files, one closable analysis/file tab, and a simpler Order tab tied to that file. Preserve in-memory preview and ordered-page state plus running readers when switching. Select the existing analysis tab for the same saved copy, replace both file-related tabs for another, and guard edited unsaved setup on close/replacement/exit. Route drop feedback and source jumps to their corresponding tabs; retain column dialogs and separate manual Excel opening. Carry the complete saved Excel/XML row-and-column data set into Order and use an explicitly selected column as the key for A–Z, Z–A, ascending, or descending views without modifying or rearranging source rows.

Acceptance: native mouse/keyboard navigation and paired close, CSV/Excel/XML preview regression coverage, preserved draft/page/selection/scroll/zoom/order state, complete source-linked Excel/XML data-set rows with the selected column's textual and stored-number ordering semantics, independent bounded row/column pages, missing order states last, paged jumps, bounded temporary storage and cleanup, explicit CSV limitation, duplicate-filename saved-copy identity, draft cancellation/confirmation, details ownership, scoped wheel binding cleanup, independent copy completion, retired-reader accounting, main shutdown, unchanged source bytes, and installed-wheel smoke checks.

## 0.14. Desktop dictionary pack manager (implemented)

Provide a native Dictionary packs dialog from Files, with field search, expected types/codes/context, source references, explicit editable/active version views, and named profile loading. Activate, update, or deactivate packs without changing file analysis. Keep mutations explicit and saved definitions reproducible.

Acceptance: button-driven lifecycle, independent profiles and reopening, same-version content edits, rejection of post-review edits, missing/invalid sources and snapshots, malformed profile errors, deactivation for repair, responsive background operations, minimum-window layout, coordinated shutdown, unchanged file previews/source bytes, and installed-wheel native controls. Document importing and pack-driven analysis remain later work.

## Date workflow steps 1–2. Definitions and parsing (implemented backend)

Provide four project-authored field definitions in the inactive `loan.dates` pack,
separate versioned parsing profiles, pure scalar interpretation, and a read-only
Excel date-column evidence reader that batches mapped columns into one worksheet
scan. Preserve raw tokens and location before serial conversion; expose ambiguous,
invalid, missing, unsupported and source-error outcomes.

Acceptance: explicit day/month order and short-year windows; Gregorian century
boundaries; 1900/1904 serials and fictitious day 60; timestamp policy; missing states;
formula/cache preservation without evaluation; shared text, hidden/gap/tail rows;
malformed evidence, source changes and cancellation; immutable policies/results;
profile round-tripping; source preservation; and installed-wheel execution.

Steps 3-8 extend this foundation as described below. The complete-data-set desktop
workflow is separate from the simpler existing one-column Date check.
See [DATES.md](DATES.md).

## Date workflow steps 3-5. Analysis, calendars and saved runs (implemented backend)

Provide explicit field/profile bindings, complete-row date and paired-date checks,
reconciled findings and distributions, a source-bound SIFMA calendar snapshot, and
self-contained saved runs with deterministic replay. Preserve raw evidence and never
adjust source dates. Full published calendar coverage is bounded; unverified history and future
weekdays remain unknown. Weekends remain deterministic across the review horizon.

Acceptance: all parser outcomes and missing kinds, same-row pairing, source identity,
raw/normalized repeats, configured bounds and IQR heuristics, activity/agreement
severity, published special/observed/early closures, unknown uncovered weekdays,
century weekend calculation, snapshot integrity, replay independent of current external
state, cancellation/atomic save failure, unchanged source bytes, and installed-wheel
execution. Exact SIFMA guidance and factual calendar data ship in both distributions.
See [DATE_ANALYSIS.md](DATE_ANALYSIS.md).

## Date workflow steps 6-8. Excel export, desktop review and validation (implemented)

Publish the complete saved data-set range plus supporting review sheets to a separate
values-only `.xlsx` through an owned xlwings/Excel process. Apply successfully
standardized mapped dates in the exported loan tape while retaining every unresolved
or unmapped source value literally. Provide explicit desktop mapping, parsing, pair, range and
field-specific calendar choices; page every finding and jump back to source cells.
Validate staged and published workbook identities, formulas, sheet order and row
reconciliation without changing the preserved source.

Acceptance: inactive/missing dictionaries fail clearly; mappings and conventions are
never inferred; two-digit years and agreement requirements are explicit; SIFMA coverage and
unknown years stay visible; completed runs replay;
exports retain the full selected loan tape, raw evidence and provenance; formula-looking source text stays literal;
existing targets are not replaced; cancellation, timeouts and Excel failures publish
nothing; source bytes remain unchanged; unit, desktop and opt-in real-Excel checks cover
the full workflow. See [DATE_ANALYSIS.md](DATE_ANALYSIS.md).

## Files visual refresh, stages 1–3 (implemented)

Preserve a local source baseline, establish a shared native style layer, and refresh Files with a warm white document list, a darker hunter-green Add file button, quiet tabs, on-demand path/copy details, and retained Dictionary packs/session/Exit controls. Keep source readers, preview layout, persisted definitions, and worker ownership intact.

Acceptance: isolated native file details/copy/refresh, duplicate-name opening, keyboard and mouse tabs, empty/loading/error states, minimum-size and larger-text layouts, existing CSV/Excel/XML and shutdown checks, and synthetic native screenshots. Preview composition and context actions follow in stages 4–6 below.

## 0.15. In-app pack and field editing (implemented)

Create new packs, make custom copies of either displayed version, and edit pack details and field definitions through native forms. Support types, entities, units, tri-state presence/blank metadata, aliases, context, notes, and existing code-list selections. Keep drafts separate from saved files and activation. Record local field authorship and copied-pack identity, preserve earlier files, and reject stale edits.

Acceptance: new/copy/edit/remove/save/reopen flows, complete validation with errors retaining drafts, unchanged original copies and active snapshots, local source attribution, duplicate/unsafe destinations, shared writer locks, failed publication and restoration, saved backups, private backup/staging build exclusions, unsaved-close protection, minimum-window layout, and installed-wheel editing. Source/code-list content editors follow in milestone 0.16; document importers and broader pack-driven analysis remain future work.

## 0.16. Source and allowed-value editing (implemented)

Add native source records, allowed-value lists and per-value meanings, and field/list citations to pack authoring. Preserve literal code text and stable source/list IDs. Keep automatic authorship/copy records, validate all references before applying, and block removal of entries still used elsewhere. Changes remain drafts until Save pack; active versions remain unchanged.

Acceptance: source add/edit/remove, optional hash validation, code add/edit/remove and duplicate rejection, field/list citations, unchanged literal whitespace/leading zeros/multiline content after save/reopen, missing-code and in-use deletion protection, local authorship, independent canceled/invalid drafts, pending field preservation, application close, minimum/scaled native layout, and installed-wheel content editing. Document import/export conveniences and broader pack-driven analysis remain later work.

## Preview visual refresh, stages 4–6 (implemented)

Give the worksheet a quieter grid and persistent sheet/saved-data-set context. Fold workbook setup and XML name editing away after successful saves, keep a direct route back, and show Inspect/Check beside the worksheet only when the selected saved column is ready. Preserve paging, zoom, source identities, readers, dictionary packs, and worker ownership.

Polish native loading, empty, retry, long-filename, edited-draft, keyboard, and narrow/scaled states. Wrap related control groups rather than clipping actions. Protect hidden workbook edits when switching through the compact selectors.

Acceptance: native Excel/CSV/XML workflows, multi-sheet/saved-set switching and restoration, contextual actions, source preservation, hidden-draft cancellation, background reads across tabs, error recovery, minimum-size and larger-text controls, existing shutdown and column-tool regressions, quality checks, and isolated installed-wheel smoke checks. Hosted CI and other operating systems require separate verification.

## 0.17. Saved Excel column definitions (implemented)

Add an explicit **Define column** action for selected columns in saved `.xlsx`/`.xlsm` data sets. Map one source column to an active dictionary field and record its source header, expected type, currency, source/canonical units, accepted text date formats, and basic required/blank/unique/bound/missing-token rule choices. Freeze the exact dictionary version, fingerprint, field meaning, and code meanings. Keep Excel storage kinds and number formats as evidence rather than business meaning, and never write the source workbook.

Acceptance: active-field selection without label inference, loan-ID/balance/date/category snapshots, required monetary currency, date-format applicability, atomic save/edit/remove/reopen, corrupt and bounded settings failures, changed data-set scope isolation, source preservation, inactive/superseded dictionary visibility, native editor behavior, quality checks, and isolated native coverage. Rule execution, CSV/XML mappings, normalization, and general user-authored cross-source profiles remain later work.

## 0.18. Warehouse Model mapping profile (implemented)

Recognize the reviewed 94-column Warehouse Model layout through a bundled, versioned, data-only profile. Match only the complete raw header sequence of an unchanged saved Excel data set and bind stable keys by source position plus duplicate occurrence. Record expected types, source/calculated/mixed roles, presence, and known units while retaining the template's exact spelling and whitespace.

Acceptance: strict profile parsing and bounds; all 94 headers and duplicate occurrence groups; exact match from an arbitrary starting Excel column; near-match rejection; full saved-header reads outside preview limits; source hash checks before and after; unchanged workbook bytes; visible native match status; synthetic backend/native regression coverage; and exact profile content in wheel/source distributions. This slice does not create column definitions, execute checks, normalize values, or generalize to similar templates.

## Rate workflow phase 1. Definitions and scalar parsing (implemented backend)

Define distinct meanings for spreads, reference rates, coupons, floors, caps and yields
in an inactive project-authored pack. Preserve immutable source evidence and apply an
explicit versioned profile through a pure exact-decimal parser. Canonicalize confirmed
spreads to basis points and other confirmed rate measures to decimal rates while
retaining original units and resolution. Keep unitless values ambiguous, require
source-specific aliases for composite benchmark text, and never collapse Prime,
agreement Base Rate/ABR, SOFR method/tenor, coupon, yield and spread meanings.

Acceptance: exact equivalence across explicit bps/percent/decimal forms, preserved
precision, complete ambiguity candidates, source/formula/error/missing distinctions,
strict malformed/grouping/scientific-notation handling, profile round-trips and
fingerprints, inactive pack validation, and isolated installed-wheel smoke coverage.
Complete-column evidence reading, mappings, population diagnostics, cross-field red
flags, market-rate retrieval, UI, persistence and export remain later phases.

## 1. Source preservation and CSV workflow

Implement source hashing/manifest, raw text ingestion with original column positions, explicit mappings, a limited canonical schema, lineage, findings, and reconciliation. Use a documented synthetic tape.

Acceptance: source unchanged; leading zeros and duplicate headers preserved; ambiguous dates/units and malformed structure produce explicit outcomes; all records accounted for; expected outputs and exceptions verified end to end.

## 2. Workbook evidence

Inspect workbook structure, cells, formats, formulas/saved values, visibility, headers, and source addresses before reconstructing position blocks.

Acceptance: multi-sheet/merged-header/formula fixtures retain evidence; missing cached results remain unresolved; no macro execution, external refresh, or source rewrite occurs.

## 3. Rules and analyst review

Implement versioned rules, applicability, review decisions, justified changes, and a CSV/Excel review package. Establish the human review workflow before expanding the initial intake screen or selecting a richer UI toolkit.

Acceptance: clean and defective fixtures produce expected results, source-derived text stays literal, exports reconcile, and every applied change has lineage and justification. Excel writing uses xlwings first; any operation-specific openpyxl fallback has a recorded reason and visible writer choice. Validate saved outputs and required workbook features, preserving original sources and intake copies.

### 3.1. SIFMA calendar screening (implemented)

Implement the packaged [SIFMA calendar guidance](../src/loan_tape/guidance/SIFMA_CALENDAR.md) as part of date review. SIFMA is the sole built-in provider for U.S. fixed-income holiday screening, with applicability determined by the field, activity, and agreement. Generate weekdays directly across the bounded horizon, use only published 2019–2027 holidays, and keep every uncovered weekday unknown.

Acceptance: preserved source values; source/version-bound findings; historical published exceptions; observed holidays across year boundaries; full versus early closes; unknown uncovered weekdays; century weekend and leap-year boundaries; and explicit handling of unconfirmed applicability. Weekend or published full-close matches remain review flags without a governing requirement. Include the complete guidance in repository and distribution releases. The complete-data-set **Date workflow** applies this bounded screening contract only in its separate red-flag phase, after import and standardization; the simpler one-column Date check remains independent. Verified annual coverage and unknown-year behavior are documented in [DATE_ANALYSIS.md](DATE_ANALYSIS.md).

## 4. CSV and Excel corpus evaluation

Freeze the taxonomy and mapping/rule versions, establish development/holdout sets of supplied CSV files and Excel workbooks, review failures and sampled passes, and report missed/new/false-positive findings with origin attribution.

Acceptance: results reproducible from versioned run manifests and independent reviewed labels. Corpus access and labeling remain prerequisites; no current coverage claim is made.
