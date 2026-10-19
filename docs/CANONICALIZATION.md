# Canonicalization integration

## Status and purpose

Phase 1 defines the integration contract and supplies executable, isolated
compatibility probes. Phase 2 implements the Python transformation foundation:
complete Excel evidence, immutable previews, explicit approvals, derived revisions,
replay and atomic session storage. Phase 3 adds the desktop **Clean text** action
with pinned ftfy proposals, explicit cell choices and session results. Phase 4 adds
bounded spelling suggestions and reviewed exact rules in the same workflow. Phase 5
adds explicitly saved reusable recipes, compatible source binding and complete-run
publication. Phase 6 adds validated text/recipe workbook export and explicit compatible
date composition. Phase 7 adds reviewed borrower matching; Phase 8 adds complete
CSV/XML scopes, field mappings and reviewed text adapters. The broader contract
below still includes requirements for the later delivery phases.

The implemented first-release scope includes reviewed text repair, spelling suggestions, exact approved
replacements, reusable recipes, and an audited Excel export to Loan Tape's existing
native desktop workflow. Start with complete saved `.xlsx`/`.xlsm` data sets and
explicit dictionary field mappings. Phase 8 now supplies CSV/XML selection and
mapping prerequisites plus reviewed text adapters; XML data export remains separate work.

The owner's Canonicalization workspace was reviewed as an implementation reference:
`CanonicalApp/workflow.mjs`, `store.mjs`, `engines.mjs`, and its text, table, rules,
and matching workers. Reuse its preview/application separation, ordered recipes,
approved literal mappings, stale-preview rejection, and per-operation evidence.
This phase copies no upstream library or CanonicalApp implementation into the
runtime package. Loan Tape must run without that sibling checkout or its services.

The optional private Python/Excel reference was consulted for text cleanup and
source-preservation cautions. Its examples do not establish loan-field meaning or
current library compatibility; the synthetic probes below exercise the pinned APIs.
The reference itself remains private and outside distribution packages.

## Component selection

| Component | Phase 1 decision | Required adaptation |
| --- | --- | --- |
| ftfy 6.3.1 | Selected for Phase 3 proposals | Pin every effective setting. Encoding repair must not silently change punctuation, HTML entities, line endings, or Unicode conventions. |
| RapidFuzz 3.14.6 | Selected for Phase 4 suggestions | Pin scorer, comparison processor, threshold and ordering. Similarity scores describe text comparison, not borrower-identity confidence. |
| DataPatch 1.2.4 | Evaluated; not selected as the literal replacement executor | It strips outer whitespace even with `normalize=False`, `lowercase=False`, and `asciify=False`. Use an application-owned exact text map for approved rules. |
| Dedupe 3.0.3 | Phase 7 optional Windows runtime verified | Pinned project-local portable compiler builds the two missing native wheels without source patches. Borrower relationships remain separate from facilities, positions and reporting dates; every proposed group needs review. |
| dateparser 1.4.3 | Deferred | Explicit date order changes the interpretation of the same token. Preserve Loan Tape's current date parser, workbook epoch, timestamp and ambiguity policies. |
| pyjanitor 0.32.41 | Deferred to reviewed header aliases if needed | Cleanup can create duplicate and empty headers. Retain literal source labels and position identities; do not rename source columns. |
| OpenRefine | Separate optional companion | Keep Java, HTTP services and the embedded editor outside the Loan Tape runtime. This phase does not start or retest OpenRefine. |

The Phase 1 probes use isolated optional dependencies. Phase 3 selects ftfy 6.3.1
for the normal application runtime, with its wcwidth dependency recorded in the
lock; Phase 4 selects RapidFuzz 3.14.6. The other candidate engines remain optional
probe dependencies. The manifest
and lock change together with a concrete implemented feature.

## Integration contract 1.0

### Scope and field eligibility

Operate only on a saved, unchanged complete data set with an explicit active field
mapping and frozen dictionary snapshot. The analyst must select the transformation;
headers and Excel number formats do not establish applicability. Match fields by
source position and dictionary identity, never by a cleaned header alone.

Text repair and spelling suggestions initially accept mapped `text` fields only.
Mapped `category` fields may receive exact replacements into a frozen allowed-value
list; reject replacements outside that list. Dictionary field semantics may impose
additional exclusions. Exclude identifiers, dates, numbers, booleans, formulas and
stored errors from these operations, even if their displayed text resembles a name.
Do not treat a `category` label for a benchmark, rate method or currency as a generic
free-text field. Later eligibility extensions require an explicit policy version.

Blank, empty text, whitespace-only text, missing tokens, zero, source errors and
unreadable cells retain their distinct states. Missing-token detection uses the
exact mapped profile. A cleanup step must not turn a missing token into a valid
value or change its status without a separately approved interpretation rule.

### Evidence and identities

Every proposed or applied cell decision must retain:

- Original source SHA-256, saved data-set ID and exact selection; sheet and original
  one-based row/column; literal header and duplicate occurrence where applicable.
- Raw representation, source storage kind, formula/cache/error evidence and source
  presence state. Do not replace raw evidence with the displayed or cleaned string.
- Mapped field ID, entity, dictionary version/fingerprint and relevant allowed-value,
  unit, currency and missing-token snapshots.
- Input derived-revision ID; proposed text; outcome (`changed`, `unchanged`,
  `ineligible`, `unresolved`, or `failed`); and the reason for that outcome.
- Stable operation/rule ID and version, complete parameters and engine versions;
  approval decision, local reviewer attribution, justification and UTC decision time.

These are minimum information requirements; Phase 2's serialized keys are described below.
Keep extraction, source-data, transformation, validation and export failures distinct.
Do not invent raw precision or workbook tokens that an existing reader did not retain;
extend the reader or mark that evidence unsupported before applying transformations.

### Preview, application and replay

Preview the complete selected population with bounded pages. Show total eligible,
proposed-change, unchanged, ineligible, unresolved and failed counts, with a route to
every decision and its source. The visible page never limits processing coverage.

Bind a preview to the source hash, data-set scope, field snapshots, input revision,
ordered steps, parameters, engine versions and selected replacements. Changing any
of them invalidates approval. Recheck identities before applying. No suggestions are
preselected and no operation runs automatically on import, mapping or recipe load.

Apply approved operations to an immutable derived result, retaining the parent and
original evidence. Preserve row count/order, column positions, amounts and rates.
Build results in staging, validate all decisions and counts, then publish atomically.
Cancellation, changed sources, resource limits and failures publish no partial result.
Clear errors remain visible; an unavailable engine never silently substitutes another.

Exact rules compare original Unicode strings, including case, accents, spaces and
punctuation. Reject duplicate/conflicting literal keys before running a step. Fuzzy
comparison normalization affects suggestions only. Multiple steps consume the prior
step's derived value while keeping the original source evidence and every intermediate
decision. A later failure publishes none of that recipe's partial output.

Reconciliation accounts for each selected cell and row, changed/unchanged outcomes,
exclusions and unresolved evidence. Financial totals, when comparable and supported,
remain separated by source, block, reporting date, currency and portfolio. Preserving
a total alone does not establish correct row association.

### Rules, recipes and retention

Scope reusable rules to a named source/template profile, mapped field identity/entity,
dictionary snapshot, reporting context where relevant, and applicable input schema.
A source hash binds one run, not every future tape. Reusing a recipe on a new source
requires explicit remapping/compatibility review and a fresh preview.

Recipes are versioned data with stable IDs, explicit ordered operations, exact rule
tables, engine versions and fingerprints. Do not support arbitrary Python, GREL,
regular-expression replacement code, file paths or network calls in a recipe. Reject
missing fields, ambiguous mappings, changed meanings, conflicts and unsupported
versions without guessing replacements.

Source-bound previews, derived results and run evidence follow session-only retention
and must join the existing owned-worker shutdown/reset lifecycle. Only an explicit
Save recipe action or export retains material across sessions. Saved rules can contain
borrower names and remain confidential local data, excluded from Git and packages.
Phase 5 implements this retention choice in the UI and [recipe guide](RECIPES.md).

### Implemented limits through Phase 5

These are safety bounds, not capacity or performance claims. Phase 2 enforces mapped
cells, serialized payloads, tokens, ordered stages and decision-page sizes. Phase 4
enforces exact-rule and fuzzy-comparison limits. Phase 5 bounds saved recipes and
library reads. These bounds replace none
of the existing readers' file, XML or workbook limits.

| Item | Initial bound and behavior |
| --- | --- |
| Mapped cells per run | 200,000; reject larger selections explicitly |
| Serialized evidence/result per run | 128 MiB; fail before publication |
| Text token | 16 KiB UTF-8; retain an over-limit cell as unresolved evidence |
| Ordered recipe steps | 12 |
| Exact replacements per step | 200 distinct literal keys |
| Serialized exact-rule parameters | 4 MiB; other operations retain the 16 KiB parameter cap |
| Distinct values per fuzzy comparison | 10,000; require a narrower scope above this |
| Suggestions per page | 200; state total count and allow navigation/filtering |
| Saved recipe file | 16 MiB; includes its fingerprint envelope |
| Recipe library | 500 files; 64 MiB aggregate inventory reading bound |

Limits must count actual payloads, support cancellation, and never truncate raw
evidence silently. Over-limit tokens need source-linked unresolved records without
copying unbounded content into the result. A resource failure blocks publication.

### Outputs and future entity matching

Phase 6 exports use the existing owned xlwings process pattern to create a new
values-only workbook. Retain the full selected data set, apply only approved derived
values, write source-derived strings literally, and include raw evidence, decisions,
rule/engine snapshots and reconciliation. Compose text and date results only when
their source, selection, mappings and parent revisions agree; reject conflicting
changes. Existing sources and export targets cannot be overwritten. XML export is
outside this integration plan.

Dedupe may suggest borrower/entity groups after explicit feature selection and
representative labeling. An entity relationship must not merge/delete loan rows or
equate different facilities, tranches, positions or reporting dates. Preserve every
candidate, label, model version, decision and source reference. Model binaries stay
local and only freshly created trusted models may be reloaded by the smoke probe.
Independent reviewed data is a prerequisite for any matching-accuracy claim.

## Phase 2 implementation

The Phase 2 foundation is engine-neutral. It adds no runtime dependency and does
not invoke ftfy, RapidFuzz, DataPatch or Dedupe. Phase 3 supplies its first engine
adapter and desktop review controls. The foundation accepts proposals as literal text
data supplied explicitly by a caller; operation parameters are recorded JSON data,
never executable instructions.

`transformation_excel.read_transformation_snapshot` requires the current saved
`SavedTable`, `DefinitionScope` and active `Catalog`. It checks frozen field meanings,
dictionary fingerprints, exact original headers and the whole selected population.
Dictionary missing codes must be included explicitly in the mapped missing tokens.
The existing OOXML evidence reader retains original text, numeric tokens, storage
types, formulas, cached tokens, source presence and coordinates without running Excel.
Duplicate headers retain their occurrence within the complete selected header row.
Unsupported merged or malformed evidence fails explicitly through that reader.

`transformations.preview_transformation` accepts an operation snapshot and explicit
`CellProposal` objects keyed by original row/column. Every mapped cell gets a decision,
including cells outside the supplied proposal list. Only mapped free-text fields are
eligible in this phase. Identifiers, dates, numbers, categories, units, code lists,
formulas, source errors and missing states cannot receive replacements. Phase 4 adds
category allowed-value replacements under its separate versioned policy. Missing tokens are
matched literally, with no implicit trimming or case folding. A proposed replacement
that introduces a blank, whitespace-only string or mapped missing token is unresolved.

`apply_transformation` requires a `TransformationApproval` with the exact preview
fingerprint, an explicit tuple of selected source cells, reviewer, justification and
UTC decision timestamp. Nothing is preselected: an empty selection applies no changes.
A failed engine decision blocks the whole revision. Unresolved and ineligible cells
retain their original state. Parent revisions are replayed before reuse; later stages
consume only approved prior values and retain all original and intermediate evidence.
This is a single-operation foundation, not a saved recipe runner.

`publish_transformation` re-reads source evidence and active mappings before applying,
stages the complete result, rechecks the source hash, and publishes through an atomic
hard link without replacing a file. Failure or cancellation removes staging and
publishes no partial result. The caller must supply current table/mapping/catalog
state and use the existing owned-worker lifecycle. The Phase 3 adapter also supplies
a final saved-data-set/mapping/catalog guard immediately before publication.
`load_transformation` requires the unchanged source and current mappings, then replays
all recorded proposals and approvals before accepting the stored result. Replay checks
the foundation's decisions, not the correctness or accuracy of a future engine.

Version 1 serialization uses:

| Record | Contents |
| --- | --- |
| Snapshot | `dataset`, frozen `fields` and header evidence, row-ordered `cells`, and `population`; SHA-256 identifies the canonical document. |
| Preview | Snapshot and parent revision IDs, complete operation metadata and parameters, literal proposals, every cell decision and reconciliation. |
| Approval | Preview ID, selected source coordinates, reviewer, justification and UTC timestamp. |
| Revision | Original snapshot and ordered stages containing previews, approvals and applied/rejected counts. Its fingerprint identifies the complete history. |
| Saved envelope | Format version, revision fingerprint and complete revision. Unknown formats or altered results fail replay/integrity checks. |

The immutable records return detached dictionaries for inspection. Preview pages
contain at most 200 decisions and retain complete counts. `derived_text_values`
provides only the approved source-coordinate overlay: it does not rebuild or export a
workbook. Unmapped columns remain referenced by the unchanged source selection;
reconciliation reports their count without claiming financial normalization or totals.

Tokens over 16 KiB UTF-8 are represented by their byte length, SHA-256 and source
coordinates, with an unresolved outcome. Their text is neither truncated nor copied
into the result. Original bytes remain in the source. The 128 MiB limit checks actual
serialized payloads, including the saved envelope and retained stage history; a run
may hit that limit before reaching 200,000 mapped cells or 12 stages. These are not
benchmarked capacity guarantees. The existing reader's memory limits still apply.

Saved revisions use `.artifacts/transformations/<source-sha256>-<run-id>.json`.
Normal file-session reset removes these records and matching interrupted `.tmp`
staging files after workers stop. Unrelated sources and artifacts remain. There is
no persistent recipe-saving or text-export action in Phase 2.

Run the fictional end-to-end example from a configured checkout:

```powershell
.\dev.bat python scripts/smoke_transformations.py
```

It creates a temporary workbook, preserves an intake copy, reads evidence, previews
and explicitly approves one literal change, saves/reloads the revision, checks both
source files and removes session evidence. `check.bat` also runs this example against
the installed wheel outside the source checkout.

Phase 2 validation on 18 October 2026 UTC: the Windows `check.bat` run passed
719 tests, formatting, lint, type checks, dependency/lock checks, distribution builds
and all installed-wheel smoke tests, including the transformation workflow. The final
focused run passed all 41 transformation tests after adding staging-collision
preservation and exercising a real 18,000-byte Unicode source token. The final
adapter also passed type/lint checks. Atomic hard-link tests used the existing
project-local environment outside the restricted filesystem sandbox; no host
configuration changed. Hosted CI, Linux, real-portfolio behavior and capacity
benchmarks remain unverified.

## Phase 3 implementation

`text_cleanup.py` adds actual ftfy 6.3.1 proposals for one explicitly selected,
mapped free-text column across its complete saved Excel data set. Every effective
configuration value is explicit and recorded. Encoding repair is initially enabled;
NFC is optional. Lossy replacement, byte-space restoration, partial UTF-8 decoding,
quote/width/ligature conversion, HTML unescaping, line-ending conversion and control
removal are disabled. Replacement characters remain unresolved. The version is
checked before processing; failures never silently select another engine.

`review_excel_text` reads current dictionary and original OOXML evidence before
generating a full-population preview. `apply_excel_text` repeats that read and actual
engine execution, compares the exact review, and checks current saved selection,
definitions and catalog again before atomic publication. Later previews consume
only approved prior values through the Phase 2 parent-revision contract.

`text_cleanup_ui.py` integrates **Clean text** with the existing Excel preview and
owned worker group. It shows proposal/current/original evidence, complete counts,
filters and 200-cell pages, explicit per-cell inclusion, reviewer/justification,
source jumps, cancellation, settings/scope/mapping/dictionary invalidation and
**Start from source**. Applied results remain separate from source grid values and
current date exports. No proposal is preselected. Closing the main application
cancels work, waits for workers and clears source-bound session revisions.

The inactive `loan.text` dictionary supplies project-authored borrower/facility
name meanings for explicit mapping. It adds no identity inference or row merging.
See [Reviewed text cleanup](TEXT_CLEANUP.md) for the user workflow, field meanings,
retention and limits. Phases 4 and 5 add spelling suggestions, rules and persistent
recipes. Phases 6, 7 and 8 now supply exports, entity matching and CSV/XML adapters respectively.

The actual-engine regression suite covers conservative settings, NFC opt-in,
preserved source bytes and literals, missing/source states, parent revisions,
stale data and changes during staging, engine failure and cancellation. Native
tests exercise more than one proposal page, approval controls, source jumps,
reopening, invalidation and active-worker shutdown. `scripts/smoke_text_cleanup.py`
runs actual preview/application/replay/cleanup against the isolated installed wheel.

Phase 3 validation on 18 October 2026 UTC: Windows `check.bat` passed all **734
tests**, formatting, lint, type checks, locked dependency checks, both distribution
builds and every installed-wheel smoke test. The run used Python 3.12.14 and the
existing project-local environment outside the restricted filesystem sandbox for
atomic hard-link publication. Native checks also verified minimum-window usability
and release of retired editor/cleanup callbacks. No host configuration changed.
Hosted CI, Linux, real portfolios and large-population capacity remain unverified.

## Phase 4 implementation

`text_rules.py` compares one explicit spelling with the complete eligible population
of the selected free-text column, consuming approved parent values when present.
RapidFuzz 3.14.6's compiled `fuzz_cpp.ratio` scorer runs with `processor=None` and
the chosen integer threshold. The explicit comparison is raw Unicode or NFC followed
by casefold. Candidates preserve their original literal text and sort by descending
score then ascending literal text. No frequency-based winner is chosen. The result
records population counts, source/parent identity and a hash of all distinct values,
counts and first source rows. More than 10,000 distinct values fails clearly.

`text_rule_types.py` supplies immutable rules and the `literal-text-category-v1`
policy. The `exact-text-rules` operation and `loan-tape-literal-map` executor are
version 1.0.0. Keys match whole Unicode strings; rules are simultaneous in a step.
Duplicate keys, no-ops, blanks, excessive tokens and mapped missingness are rejected.
Category targets must belong literally to the frozen allowed list. The foundation
requires proposals for every eligible exact match and rejects extra, missing or
altered proposals during preview and replay. Other operation types still cannot
change categories. Rule parameters permit 200 keys and a 4 MiB serialized limit;
the existing total evidence, token and stage limits also apply.

`text_rules_ui.py` adds the session draft editor to **Clean text**. Its search worker
uses the existing owned-worker group and cancellation lifecycle. Candidate selection
is explicit, as are draft acceptance, complete cell preview and per-cell approval.
Rules selected from candidates retain the score, source/parent/corpus identities,
comparison, Unicode version, engine/scorer versions and ordering. These are records
of the suggestion's origin, not a claim that spelling similarity establishes identity.
Accepted rules reuse the existing application recheck and atomic publication path.
Manual rules record literal text and rule IDs without invented similarity evidence.

Native tests cover multi-page candidates/cell choices, duplicate draft rejection,
category restrictions, stale mappings, callback release, cancelled search and app
shutdown. Actual-engine tests cover exact Unicode/whitespace, deterministic scoring,
the actual 10,001-value rejection boundary, rule limits, source preservation, chained
repair/rules and replay. The installed-wheel text smoke now executes both engines
and the literal executor. This phase does not add recipe persistence, text export or
entity matching. User instructions are in [TEXT_CLEANUP.md](TEXT_CLEANUP.md).

Phase 4 validation on 18 October 2026 UTC: Windows `check.bat` passed **765 tests**,
formatting, lint, strict types, dependency/lock checks, source/wheel builds and all
installed-wheel smoke tests. The isolated installed wheel ran actual ftfy,
RapidFuzz, literal application, saved replay and source-bound cleanup. Atomic
publication tests used the existing project-local environment outside the restricted
filesystem sandbox; no host configuration changed. Hosted CI, Linux, real portfolios
and capacity benchmarks remain unverified.

## Phase 5 implementation

`recipes.py` captures a reviewed working history as 1–12 ordered, portable operations.
Only the implemented ftfy settings and exact literal rules are accepted, with pinned
engine/configuration versions. Portable rules omit old source matches, cell approvals
and similarity claims. Users explicitly save a named recipe with a stable ID,
semantic version, source/template profile and applicability/reporting context.
Canonical JSON determines the fingerprint; save never replaces an existing version.
Malformed, unknown, oversized or tampered files fail visibly.

The input schema freezes every mapped field definition, missing-token setting,
relative column, literal source header and duplicate occurrence, plus selected width
and the header convention. Reuse can change the file, sheet, range position and row
count; it requires compatible mappings and explicit profile/current-context review.
No mappings or field meanings are inferred. A binding records the new source snapshot,
recipe fingerprint, reviewer and confirmation time.

`recipe_execution.py` regenerates each step from the source and approved intermediate
values. `recipe_run_ui.py` reuses the native cell review workflow with no preselected
changes and explicit approval, including reject-all steps. Earlier approvals stay in
memory. Final application executes every engine again, checks the complete approved
history and current inputs, then uses the existing atomic publisher for one revision.
Failures, cancellation and stale inputs publish no partial run. The prior working
result remains selected until a complete run succeeds.

`recipe_context.py` validates recipe/binding evidence retained in every operation.
A completed recipe archive additionally retains its full recipe and binding for
validated loading. Later ordinary cleanup retains earlier recipe operation evidence.
`recipe_ui.py` provides capture, metadata editing, ordering/removal, explicit
save/load and a local library. Saved files in `.artifacts/recipes/` survive Exit;
drafts and source-bound run evidence retain their existing temporary lifetimes.
See [Reusable cleanup recipes](RECIPES.md) for compatibility, confidentiality,
retention and user instructions. Phase 6 supplies text workbook export.

Regression coverage exercises cross-source/shifted-range reuse, version collisions,
ordering, fresh approvals, schema rejection, strict data-only validation, tampering,
source preservation and later-step/publication failures. Native tests cover the
library, step review, discard, stale inputs, callback release and shutdown during
active workers. The installed-wheel smoke runs the same saved recipe against a new
synthetic workbook and verifies recipe retention after source-bound session reset.

Phase 5 validation on 19 October 2026 UTC: Windows `check.bat` passed **802 tests**,
formatting, lint, strict types, dependency/lock checks, both distribution builds and
every installed-wheel smoke test. The isolated installed package executed saved
recipe reuse on a second synthetic workbook, fresh binding, staged approvals,
complete publication, saved replay and retention after reset. Atomic publication
tests used the existing project-local environment outside the restricted filesystem
sandbox. No host configuration changed. Hosted CI, Linux, real portfolios and
large-population capacity remain unverified.

## Phase 6 implementation

`text_export_payload.py` replays the approved revision against current source evidence
and frozen mappings, rejects incomplete recipe chains, then reads every cell in the
complete selection. Final approved text values overlay original source coordinates.
An explicitly included date run must match source/selection and raw evidence, retain
current dictionary snapshots, agree with shared column definitions and propose no
conflicting changes. Only valid dates are composed. Original-source date runs have
no text parent, so composition covers compatible independent columns.

The new workbook contains Loan Tape, Summary, Steps, Cell Decisions, Source Evidence
and Audit, with optional Date Results/Date Findings. Every selected source cell and
every step decision is accounted for. Canonical JSON records split into numbered
chunks preserve the full histories and rule/configuration evidence without truncation.
Source tokens, including numbers and identifiers, remain literal text; valid dates
are ISO text. This phase does not infer numeric conversions or copy source workbook
styles, visibility, macros or links. Formula expressions remain literal evidence.

`text_export.py` checks current metadata, uses an owned xlwings writer, validates each
staged value/type and output dimension, checks inputs again, then publishes without
replacement. A second saved-file/input check protects the published result; failed
attempts remove only files they own. Existing targets created during a race remain
untouched. `text_export_excel.py` owns process cancellation/timeout and rejects output
formulas, error cells, macro parts and external relationships. No source workbook is
opened in Excel, and no alternate writer silently replaces xlwings.

`text_export_ui.py` provides explicit export from the current complete revision,
unchecked optional date inclusion, output opening and owned-worker cancellation.
Intermediate recipe review windows cannot export. Full selected-range limits are
200,000 cells, 256 MiB payload/output and Excel sheet/cell limits; long histories may
reach evidence limits first. See [Reviewed text export](TEXT_EXPORT.md).

Regression coverage includes exact source overlays, approved/rejected and hidden rows,
identifier/formula-like literals, blank tails, source/metadata changes, incompatible
date mappings/evidence, incomplete recipes, malformed outputs, external links,
publication races and cancellation. Native tests cover explicit date selection,
successful output retention, stale context and shutdown. `check.bat --excel-smoke`
also executes real recipe/date export plus cancellation/timeout from the installed
wheel. Phase 6 prepares and checks the local release; public publication remains
a separate authorized action.

Phase 6 validation on 19 October 2026 UTC: Windows `check.bat --excel-smoke`
passed **830 tests**, formatting, lint, strict types, dependency/lock checks, both
distribution builds and all installed-wheel smoke tests. Python 3.12.14 and xlwings
0.37.4 executed real text/recipe/date export from the isolated installed package,
including exact saved values, original preservation, retention, cancellation after
Excel startup and timeout cleanup. No Excel processes remained afterward. Hosted
CI, Linux, real portfolios and capacity remain unverified. No host changes occurred.

## Reproduce the Phase 1 probes

From a configured checkout with Python 3.12:

```powershell
.\dev.bat python scripts/probe_canonicalization.py
```

This creates isolated environments under `.tools/canonicalization-probe/` and
`.tools/canonicalization-dedupe-probe/`, co-installing application runtime requirements
with the optional locked probe groups. It does not install the application itself
into those environments. The ordinary `.venv/` package inventory is compared before
and after. Caches and temporary files use the normal project-local helpers.

The default checks binary-only installation. An explicit project-local source-build
attempt, using only already installed compiler tools, is available with:

```powershell
.\dev.bat python scripts/probe_canonicalization.py --dedupe-source-build
```

Neither mode installs host software, downloads a Python runtime, changes PATH, starts
OpenRefine, or contacts a matching/reconciliation service. Dependency installation
uses the configured package index. The base profile continues independently of a
Dedupe failure. A failed install or case returns nonzero and retains its error/log.
There is no automatic change of interpreter, source patch, or engine fallback.

Each run writes a unique ignored `.artifacts/canonicalization-phase1/<run>/report.json`
with UTC timestamps, manifest/lock/probe hashes, primary-environment comparison, profile
outcomes and package/license metadata. Per-profile logs and `cases.json` retain the
actual probe decisions. All inputs are fictional literals; no portfolio file is read.

The cases exercise encoding repair and preserved conventions; the compiled RapidFuzz
scorer; DataPatch whitespace behavior versus exact literals; explicit date ambiguity;
header collisions and text preservation; and, if installation succeeds, Dedupe
training, partitioning, source preservation and model reload. Training-fixture success
is a runtime smoke check, not independent matching validation.

## Local results, 18 October 2026 UTC

On Windows x86-64, Python **3.12.14**, uv **0.12.15**, the locked base profile
installed from binary distributions and passed `uv pip check`. Each of its five
engine cases passed: ftfy, RapidFuzz, DataPatch, dateparser and pyjanitor. Pandas
3.0.6 and NumPy 2.5.4 were present in that environment alongside the declared Loan
Tape runtime dependencies. The ordinary application environment was unchanged.

Dedupe 3.0.3 **did not reach import/training** on this machine. The binary-only
attempt stopped at `affinegap==1.12`, which has no matching Python 3.12 Windows
wheel. An explicit source-build attempt failed building
`dedupe-levenshtein-search==1.4.5` with `Microsoft Visual C++ 14.0 or greater is
required`. This is a dependency-chain blocker, not proof that Dedupe's own Python
3.12 wheel or algorithm is broken. No compiler or other host software was installed.
The Dedupe profile and overall optional probe return nonzero; the base cases retain
their separate passing outcomes.

At Phase 1, Phase 7 was gated on a separately authorized toolchain installation, a reviewed
reproducible project-local build toolchain, or another explicitly reviewed integration
design. Do not substitute the sibling project's Python 3.10 environment or patch
source silently. This restriction does not gate the selected text components or
exact-rule contract. Linux, hosted CI, large-population behavior, and real-portfolio matching
have not been verified by these probes.

Phase 7 resolved the local dependency blocker on 19 October 2026 UTC with the
checksum-pinned LLVM MinGW 20260616 UCRT toolchain inside `.tools/`. The unmodified
locked affinegap and dedupe-levenshtein-search sources built for Python 3.12.14.
Dedupe 3.0.3 passed training, partitioning, fresh-model reload and source-preservation
probes; the ordinary environment remained unchanged. The optional application
runtime is prepared by `scripts/setup_entity_matching.py --portable-compiler`.
See [ENTITY_MATCHING.md](ENTITY_MATCHING.md) for the bounded implementation,
review workflow, provenance, retention and remaining evaluation limits.

The full Windows `check.bat` validation passed: **679 tests**, formatting, lint,
type checks, lock and dependency checks, distribution builds, and the isolated
installed-wheel smoke tests. The successful run used the existing project-local
environment outside the restricted filesystem sandbox because that sandbox denied
the application's atomic hard-link publication tests. No application code or host
configuration was changed to work around that restriction. This result does not
establish a hosted CI or Linux pass.

## License and provenance review

The installed package metadata and available license/notice-file hashes are recorded
for every probe dependency, including transitives. Direct upstream licenses are:
ftfy Apache-2.0; RapidFuzz MIT; DataPatch MIT; Dedupe MIT; dateparser BSD-3-Clause;
pyjanitor MIT. OpenRefine publishes BSD-3-Clause terms. Preserve the relevant license,
copyright and notice material if any code or binary is later redistributed. A future
bundled application needs review of its actual transitive payload; this inventory
does not establish a legal conclusion or change Loan Tape's MIT license.

Primary sources checked for the pinned APIs and package metadata:

- [ftfy configuration](https://ftfy.readthedocs.io/en/latest/config.html) and
  [ftfy 6.3.1](https://pypi.org/project/ftfy/6.3.1/).
- [RapidFuzz documentation](https://rapidfuzz.github.io/RapidFuzz/) and
  [RapidFuzz 3.14.6](https://pypi.org/project/RapidFuzz/3.14.6/).
- [DataPatch 1.2.4](https://pypi.org/project/datapatch/1.2.4/) and its
  [normalization implementation](https://github.com/opensanctions/datapatch/blob/3da3906d636336c4c4195bd1354865a6f23817f8/datapatch/util.py).
- [Dedupe 3.0.3](https://pypi.org/project/dedupe/3.0.3/),
  [affinegap 1.12 files](https://pypi.org/project/affinegap/1.12/#files),
  [dateparser 1.4.3](https://pypi.org/project/dateparser/1.4.3/), and
  [pyjanitor 0.32.41](https://pypi.org/project/pyjanitor/0.32.41/).
- [uv dependency groups](https://docs.astral.sh/uv/concepts/projects/dependencies/).

## Delivery phases

1. **Contract and compatibility:** this document, locked optional probes, executed
   synthetic evidence and an explicit component decision.
2. **Transformation foundation:** immutable source-linked decisions, staged derived
   results, complete population accounting and regression coverage.
3. **Reviewed text cleanup:** mapped text columns, ftfy/settings previews, explicit
   application, invalidation and source navigation in the existing desktop.
4. **Spelling suggestions and rules:** RapidFuzz candidates and reviewed exact maps.
5. **Recipes (completed):** ordered versioned replay, fresh compatible source
   binding, complete-run publication and explicit persistent recipe saving.
6. **Export and first-release preparation (implemented):** compatible composed
   results, validated xlwings output, native checks, installed-package checks and
   updated user/operations documentation. Publication is separate.
7. **Entity matching (implemented):** a verified optional Windows/Python 3.12 Dedupe
   runtime, borrower-feature selection, representative pair labels, reviewed groups
   and separate JSON relationship evidence. No row merging or identity accuracy
   claim; independent evaluation remains conditional on a reviewed holdout corpus.
8. **CSV/XML adapters (implemented):** complete saved scopes and explicit field
   mappings feed shared proposal/approval/replay contracts with native lineage and
   missingness. Repair/NFC, exact replacements and new-file JSON audits are available
   in a native dialog. Recipes, matching and workbook/date exports keep their Excel
   boundaries. See [SOURCE_ADAPTERS.md](SOURCE_ADAPTERS.md).
