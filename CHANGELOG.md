# Changelog

## Unreleased

- Simplified the README around installation, a first review, supported files, and
  results. Added a task-based documentation index and a detailed user guide;
  source packages include the linked guides. Application behavior is unchanged.

## 0.1.0 - 2026-09-17

- Prepared the first public alpha under the MIT License with public-release metadata,
  a contributor workflow, private vulnerability-reporting guidance, and an exact
  step-by-step release checklist.
- Added shared OOXML expansion limits across automatic workbook readers, bounded XSD
  dependency graphs before schema compilation, and bounded/cancellable dictionary-pack
  loading following the first repository-wide security review.
- Bounded saved table-selection settings by file size and data-set count; saved settings
  now reject duplicate JSON keys before constructing local review state.
- Changed desktop file handling to session-only retention. Normal Exit or main-window
  close now waits for owned work and removes intake copies, source-linked selections,
  definitions, saved date runs, and session metadata while preserving the original
  source, explicit exports, dictionary packs, and unrelated local artifacts. Cleanup
  failures remain visible and keep the application open for retry.
- Added a bundled, versioned Warehouse Model mapping profile for the reviewed 94-column
  loan-tape layout. Saved Excel data sets show an exact profile match only when the
  complete raw header sequence—including whitespace, source spelling, and duplicate
  occurrences—matches. The profile records stable keys, expected types,
  source/calculated/mixed roles, presence, and units without creating column definitions,
  executing rules, normalizing values, or changing the workbook.
- Changed the date-workflow Excel export into a complete refined-loan-tape export. The
  first sheet contains every row and column in the saved data set, applies only
  successfully standardized mapped dates, retains unresolved/unmapped values literally,
  and keeps the existing findings, evidence, and audit sheets.
- Kept preview review actions visible while unavailable and added a concise next-step
  prompt for saving the data set, selecting a column, and choosing a review action.
- Added an explicit in-context action that activates the available local loan-date
  definitions and rebuilds the same date-workflow window, with retryable errors and
  unchanged source workbooks.
- Added format-aware Files guidance and disabled the unavailable `.xls`/`.xlsb` preview
  path while retaining source preservation, details, and safe keyboard/double-click
  feedback.

- Added a third top-level Order tab for the open file. The complete saved Excel/XML data set now carries over from Analysis: every displayed row retains all of its source columns while the explicitly selected column acts only as the A–Z, Z–A, ascending, or descending order key. Independent 50-row/10-column pages, source jumps, exact missing-state handling, bounded temporary SQLite storage, and cleanup preserve the read-only source-linked workflow. XML/text identifiers are not coerced into numbers; CSV ordering remains unavailable until saved CSV data-set scope exists.

- Date import now reads every mapped Excel date column in one validated worksheet scan instead of reopening and rescanning the package per mapping. The single-column API remains available through the same atomic bulk reader.

- Added the Phase 1 loan-rate foundation: an inactive project-authored field pack and an exact-decimal scalar parser with immutable source evidence, versioned profiles, preserved precision, explicit bps/percent/decimal conversion, ambiguous unitless outcomes, and source-specific benchmark aliases. Spreads canonicalize to basis points; coupons, benchmark observations, floors, caps, and yields canonicalize to decimal rates. Complete-pool mapping, diagnostics, red flags, market data, UI, and export remain later phases.

- Added source-bound saved definitions for selected columns in Excel data sets. Users explicitly choose an active dictionary meaning and record currency, source units, accepted text date formats, and basic rule metadata. Saved mappings freeze the exact field/code meanings and pack fingerprint, keep changed data-set scopes separate, never infer meaning from Excel formatting, and never modify source workbooks.

- Kept setup/check and targeted development temp/cache storage inside the project, including direct pytest runs. Pytest storage is separated by the executing account so sandbox commands do not reuse Windows temp folders owned by another user. Added `dev.bat` for targeted tools without manual environment overrides.

- Separated the complete date workflow into an import/standardization phase and a downstream red-flag phase. Mapping and parsing now publish an immutable in-memory handoff with no findings; blank, bound, pair, reference-date, and SIFMA policies are configured and run only afterward. The desktop exposes separate tabs and actions, and rejects red-flag execution after mapping or interpretation choices change.

- Completed the date workflow with explicit desktop mappings and policies, paged findings with source jumps, self-contained run saving, and a separate institutional review workbook produced only through an isolated xlwings/Excel worker. Exports retain raw evidence, SIFMA calendar provenance and reconciliation, contain no formulas or links, never overwrite a source or existing target, and are validated before and after atomic publication.

- Added in-app source records, exact allowed-value lists, per-value meanings, and field/list citations. Content dialogs validate draft edits, preserve automatic authorship, block broken references and in-use deletions, and leave active snapshots unchanged. Added backend/native regressions and installed-package checks.

- Added XML stage 4 with explicit, read-only XSD 1.0/1.1 validation from the existing preview. Users choose a local main XSD; the complete XML is checked in the background and all schema findings remain available in pages with paths, categories, reasons, and optional lines. Schema hints and network/outside-folder imports are blocked, local package files and source content are hash-bound, temporary results are bounded and cleaned up, and no MISMO-specific interpretation is added.

- Refined Preview with persistent sheet/data-set switching, automatically folded saved setup, contextual column actions, and quieter worksheet styling. Added explicit loading/empty/retry states, shortened long filename display, hidden-draft switching protection, and wrapping controls for smaller/scaled windows. XML name editing also folds after saving. Added native workflow, recovery, and scaled-layout regressions without changing readers or file formats.

- Added in-app pack creation, custom copies, and pack/field editing with validated drafts, explicit local authorship, saved prior files, stale-edit protection, and unchanged active snapshots. Added unsaved-close protection and installed-editor checks. Excluded dictionary history and temporary drafts from Git and builds.

- Added XML stage 3 through the existing Inspect column and Check column dialogs: complete saved-group field scans, distinct missing/empty/nil/text states, exact repetition counts, explicit identifier/text/decimal/date checks, all findings pages, and source-linked record jumps. Shared aggregation and check infrastructure retains Excel behavior, source identities, bounded temporary storage, cancellation, and cleanup. XML text is never normalized and no XSD or MISMO dependency is introduced.

- Added FinExtract-informed security, operations, and release guidance; private security-report routing; weekly uv/action update configuration; immutable CI action pins without persisted checkout credentials; and archive-content checks for local data, credentials, and required guidance. These are local project controls; hosted settings and production approval remain separate decisions.

- Refreshed Files with a shared native style, near-black hunter-green Add file button, spacious document list, quiet workspace tabs, and an expandable Details area for paths/copy controls. Retained Dictionary packs, the fixed session date, native keyboard opening, preview state, and worker shutdown. Added native details, duplicate-name opening, and scaled-layout regression coverage. Preview composition follows in the subsequent refresh above.

- Added the date-workflow foundation: a four-field inactive loan-date dictionary, versioned explicit parsing profiles, immutable source-bound results, and a raw OOXML date-column reader preserving original serials, text, formats and formula evidence. Added century, ambiguity, missingness, timestamp, 1900/1904, malformed-source and installed-wheel regression checks.

- Added XML stage 2 in the existing preview tab: full record/field paging, direct jumps and endpoints, complete group counts, and multiple named whole-group data sets with saved view positions. Setups use exact source hashes and namespace-aware paths, reopen independently, and support rename/removal without changing XML or workbook settings. Added explicit stale-source, corrupt-settings, and save-failure handling with native and installed-wheel coverage.

- Added a desktop Dictionary packs manager with field search, definitions/types/codes/sources, editable versus active version review, profile switching, and explicit activation/deactivation. Changed files require refresh before activation. Invalid sources/snapshots remain visible, workers participate in shutdown, and current file analysis remains independent.

- Recorded the initial calendar-screening policy with activity-specific applicability, source/version evidence, preserved dates, packaged guidance, and distribution-content verification. The implemented calendar now uses SIFMA as its sole provider, keeps only published 2019–2027 holidays, and leaves uncovered weekdays unknown. Excluded local audit notes from Git and builds.

- Moved file preview into a second tab in the main window beside Files. Tab switching preserves preview state and active readers; ×/Ctrl+W closes just the file tab. Added native keyboard traversal, unsaved setup protection, preview-area drops with visible intake feedback, and tab-aware source navigation/dialog ownership. Main shutdown, file-copy completion, and Excel process ownership are preserved.

- Added an independent JSON dictionary-pack backend with strict validation, source references, searchable catalogs, and explicit activation/deactivation in named profiles. Packs start inactive, edited content requires reactivation, and active definitions use fingerprinted snapshots. Included synthetic and selected ESMA reporting references. Current desktop inspection and checking behavior is unchanged.

- Added stage-one XML intake and preview in the existing CSV-style window. XML records, attributes, namespaces, source paths, and missing-value states remain explicit; ambiguous groups require selection and nested repetitions/mixed content are flagged. Complete-document parsing is bounded and cancellable, with no DTD/entity or schema/style loading. No MISMO dependency or XML schema validation is introduced.

- Added a windowless Loan Tape desktop shortcut, create-launcher.bat, and an Exit button. Desktop launchers consistently use the project working directory. Main-window shutdown now waits for all owned workers, including retired previews; workbook loads support cancellation. Excel and Python helpers enter an owned job before running and close together, with unrelated Excel sessions excluded from cleanup.

- Added read-only Check column for saved Excel tables with explicit Identifier/Text/Number/Date expectations, optional blank and date rules, complete source-linked findings in pages of 20, and source-cell jumps. Every selected data row is checked; settings changes, cancellation, source/read failures, and temporary-result cleanup are explicit.

- Added Inspect column for saved Excel tables: complete range counts, stored value types, blanks/empty text/zeroes, repeated values, and source-cell examples with jump navigation. Preview limits do not limit inspection; unsaved table edits, source changes, read failures, and cancellation are explicit.

- Added a recorded startup date/time and fixed local reference date shared by the main window and all file previews. Each launch preserves its UTC offset and equivalent UTC timestamp for future date checks.

- Added multiple named tables per workbook, independent ranges and repeatable header-row selection, visible column labels across preview pages, and saved-table editing/removal. Earlier single-range settings remain readable; source data is unchanged.

- Reduced CSV and Excel previews to 20 rows and 10 columns; workbook discovery and saved full-range selections are unchanged.

- Added whole-workbook location discovery, all-sheet coverage and visibility, editable suggested areas and arbitrary ranges, source-address paging/jumps, and full-range/header selection saved independently of preview pages. Hidden and distant data remain discoverable; partial scan failures are explicit.

- Added a parallel xlwings/desktop Excel reader alongside openpyxl, a preview reader selector and difference highlighting, conservative plain-data eligibility checks, explicit unavailable/skipped results, and isolated temporary-copy lifecycle checks. No LLM or add-in is required.

- Added Inspect file: a read-only CSV/.xlsx/.xlsm preview with worksheet selection, CSV reading options, row/column scrolling, cell details, and explicit preview limits. Sources remain unchanged; column analysis and cleaning remain future work.

- Added a native desktop CSV/Excel intake window using Tkinter/ttk and tkinterdnd2, with Browse, file drops, source-preserving session copies, current-session history, and separate original/saved location controls.
- Replaced the initial browser prototype; retained its saved-file compatibility. Added original-path manifests, source-change checks, and shutdown that waits for an active copy.

- Focused the active input scope and evaluation roadmap on CSV and Excel; existing separate PDF extraction/conversion functionality will be integrated in a later phase.
- Established the Python 3.12 package, CLI help/version, and locked development tooling.
- Added project-local Windows setup/run/check commands and portable Python scripts.
- Added documentation for product scope, architecture, draft data contracts, and milestones.
- Preserved supplied research references and recorded their relationship to FinExtract.
- Added automated quality checks and an isolated built-wheel installation check.

File preservation, bounded data preview, full-column inspection, explicit type/date checks, and the bounded date workflow are implemented. Broader raw-evidence processing, financial analysis, normalization, and financial validation remain planned.
