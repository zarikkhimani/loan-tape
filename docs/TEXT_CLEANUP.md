# Reviewed text cleanup

Phases 3–5 supply **Clean text** for complete saved `.xlsx`/`.xlsm` data sets.
It offers ftfy 6.3.1 repairs, RapidFuzz 3.14.6 spelling suggestions and exact
replacement rules, applying only individually chosen cells to a separate session
result. Original files, preserved intake copies and source grid values
remain unchanged. Phase 5 adds [reusable recipes](RECIPES.md) with fresh review on
each compatible source. No desktop Excel installation is needed for this action.

## Choose a field and preview

1. In **Dictionary packs**, activate **Loan text field definitions** (`loan.text`),
   or an appropriate existing custom text dictionary. The supplied pack starts inactive.
2. Open a workbook, save its complete data set, and select the source column.
3. Choose **Define column** and explicitly select its field meaning. Review any
   missing tokens. A header alone never establishes the field's meaning.
4. Choose **Clean text** in **Repair text** mode. **Repair garbled characters** is initially checked.
   **Combine equivalent Unicode characters (NFC)** is optional and initially off.
5. Choose **Preview cleanup**. Review the complete population counts and proposals.

For repair, only ordinary stored text in the chosen free-text column is eligible. Identifiers,
dates, amounts, rates, categories, fields with allowed-value lists or units, numeric
cells, booleans, formulas and source errors are excluded. Blank, absent, empty,
whitespace-only and explicitly mapped missing tokens keep their distinct states.
All mapped cells are accounted for, including hidden rows, gaps and blank tails.
Unmapped columns remain referenced by the unchanged saved source range.

Encoding repair proposes changes such as `CafÃ© Holdings` to `Café Holdings`.
It is a heuristic suggestion for review, not proof of the intended name. Existing
spaces, case, quote style, HTML entities, line endings, ligatures and character
width are not normalized. NFC can combine an accent and a preceding letter into
an equivalent composed character. It does not establish identity or spelling.
Text containing the replacement character `�` remains unresolved because the lost
characters cannot be recovered reliably. Uninterpretable values stay unchanged.

## Spelling suggestions and exact replacements

1. In **Clean text**, choose **Exact replacements**, then **Edit rules / spelling**.
   The same saved data set and explicit field mapping apply.
2. Enter the exact source text, including any spaces or line breaks. To populate
   it from current evidence, first preview with no rules, choose **All mapped cells**,
   highlight a current text value, then open the rule editor.
3. For a free-text field, choose **Minimum similarity** (0–100; initially 85) and
   **literal** or **nfc-casefold** comparison, then **Find similar spellings**.
   The source spelling must occur in this column's current eligible values.
4. Review candidates, scores, occurrence counts and first source rows. Candidates
   use the complete data set, including hidden rows, with 200 per page. No candidate
   is preselected. Highlight one and choose **Use selected as replacement** to draft
   an exact rule. You can also type both values and choose **Add exact rule**.
5. Review the draft table. **Remove selected rules** removes a draft. Duplicate
   source keys, even identical repeated rules, are rejected. To edit a rule, remove
   it and add the corrected pair. **Cancel** discards this editor's unaccepted edits.
6. Choose **Use rules for preview**, then **Preview cleanup** in the main dialog.
   Review and include individual changed cells as described below. Accepting a rule
   is not cell approval and does not run a preview automatically.

Similarity describes spelling, not entity identity or the probability that a name
is correct. Candidates come only from the same selected free-text column; no
external names or inferred missing text are supplied. **literal** compares raw
Unicode. **nfc-casefold** composes equivalent Unicode characters and folds case for
scoring only. It does not remove spaces or punctuation or alter either literal in
the rule. Scores sort descending; ties sort by raw text, independently of frequency.
The first source row is a location reference, not an approval of that spelling.

Exact rules match whole strings with all case, accents, spaces, punctuation and
line breaks significant. For example, a rule for ` Acme ` does not match `Acme`.
Rules in one step are simultaneous: `A → B` and `B → C` turn an original `A` into
`B`; a separately reviewed later step can turn that result into `C`. There is no
substring, regex, automatic trimming or fuzzy replacement. Nonblank replacements
may introduce a new free-text spelling, but cannot introduce mapped missing tokens.

For a mapped **category**, spelling search is disabled. **Show allowed values**
displays the frozen codes and their meanings. Type an exact source and a replacement
that is literally in that list. Check the source meaning before approving a code
change; the tool does not infer which category is correct. Identifiers, dates,
numbers, units, formulas, errors and missing states remain excluded.

Changing the search query or comparison settings clears candidates. Accepted rules
retain the settings under which they were chosen. Changing accepted rules clears
the cell preview and approvals; changes to data-set scope, mappings, dictionary
meaning or working result invalidate an open editor. Closing Clean text discards
its rule draft. Applied rule text and selected suggestion evidence remain in the
session revision. **Recipes** can explicitly save the configured working history for
future review; see [Reusable cleanup recipes](RECIPES.md).

## Review and apply

The default **Proposed changes** view shows up to 200 cells per page. Use **Previous**
and **Next** for the rest; the complete count stays visible. **All mapped cells**
also shows unchanged, excluded, unresolved and failed outcomes. Selecting one row
shows complete escaped current/proposed text, its reason and original evidence.
**Jump to source cell** returns to that worksheet location in the main preview.
The grid abbreviates long text for display only; details retain the complete literal.

No proposals are preselected. Highlight reviewed rows and choose **Include selected
changes**. Choices persist across pages. **Remove selected** and **Clear choices**
withdraw approvals. Enter a **Reviewer** and **Reason for changes**, then choose
**Apply selected changes**. Each applied revision records those details, a UTC
timestamp, selected source cells, original/intermediate values and engine settings.
A failed processing decision blocks application; excluded and unresolved cells
cannot be selected for replacement.

Application re-reads the preserved workbook, re-runs the pinned engine, and checks
the saved data set, column mappings and active dictionary snapshots before publishing
the complete session result. Changed inputs/settings require another preview and
review. Editing settings or mappings clears choices. Unsaved data-set edits and
inactive/changed meanings disable the workflow. If a previous result is incompatible
with revised mappings, use **Start from source**, then preview again.

Further previews use approved prior values in the current data-set result. Closing
and reopening Clean text within the same open file preview retains that working
result. **Start from source** selects the original baseline for subsequent work;
previous session evidence remains until Exit. Closing the file preview releases
its current working-result selection. There is no saved-run browser or automatic
resume after restarting the application.

## Retention and limits

Applied revisions are local session JSON under `.artifacts/transformations/`.
Normal **Exit** cancels processing, waits for owned workers and removes the source-bound
revisions and staging files along with the intake copy and mappings. Forced
termination may leave temporary evidence. The original source stays unchanged.
The application uses ordinary local storage; keep session files outside Git.

**Export reviewed result...** retains completed text/recipe results in a separate
validated workbook, with optional compatible date composition. It preserves source
tokens, including numbers, as literal text; see [Reviewed text export](TEXT_EXPORT.md).
Existing date-workflow exports use their existing date results and do not include
these text changes automatically. **Save recipe** explicitly retains
ordered settings/rules after Exit; a loaded recipe requires fresh compatibility
review and cell approvals. Phases 7 and 8 now provide borrower matching and
CSV/XML adapters in their separate workflows.

The foundation enforces 200,000 mapped cells, 128 MiB serialized evidence/results,
16 KiB UTF-8 text tokens, and 12 reviewed steps. A rule step permits up to 200
distinct literal keys and 4 MiB of serialized rule parameters. Spelling comparison
permits up to 10,000 distinct eligible values; above that, choose a narrower saved
data set. Neither candidates nor cell decisions are silently sampled.
A run can reach its payload limit
earlier. Over-limit text has an unresolved source-linked length/hash record; it is
not silently truncated. Cancellation and resource failures publish no partial result.
These are safety bounds, not benchmarked capacity claims.

## Project-authored text meanings

These source-name definitions are descriptive. They are not a regulatory standard,
legal-name certification, or a rule that two similarly named records are one entity.

| Field | Meaning and scope |
| --- | --- |
| `borrower_name` | The literal name supplied for the borrower role on the mapped record. Confirm that role; keep borrower identifiers, guarantors and reporting context separate. |
| `facility_name` | The literal descriptive facility name associated with a loan record. It uses the pack's `loan` entity scope. Keep facility/tranche identifiers, positions and reporting dates separate. |

Neither definition permits merging rows or inferring missing digits or names.
Map an identifier as an identifier even if its source cells are stored as text.

## Implementation and checks

The adapter pins every effective ftfy setting, records engine/configuration and
wcwidth versions, and rechecks the engine before application. Lossy replacement,
space restoration, partial UTF-8 decoding, quote conversion, HTML unescaping,
line-ending changes, width/ligature conversion and control removal are disabled.
See [ftfy configuration](https://ftfy.readthedocs.io/en/latest/config.html) and the
[transformation contract](CANONICALIZATION.md#phase-2-implementation).

Spelling uses the compiled RapidFuzz `fuzz_cpp.ratio` scorer with `processor=None`;
the chosen comparison transform is explicit application code. A selected suggestion
records the source/parent/corpus identities, score, threshold, comparison, Unicode
version, engine version, scorer and ordering. Applied exact rules record their
entire literal table and executor policy/version. Replay verifies every eligible
match against that table. See the primary [RapidFuzz ratio documentation](https://rapidfuzz.github.io/RapidFuzz/Usage/fuzz.html#ratio).

Regression coverage exercises actual engine output, NFC opt-in, preserved literals,
missing/source states, stale inputs, failure and cancellation. Native desktop tests
exercise multi-page choices, source jumps, application, reopening, invalidation and
shutdown while preview/application workers are active. `check.bat` also runs
`scripts/smoke_text_cleanup.py` against an isolated installed wheel.

Phase 4 validation on 18 October 2026 UTC: Windows `check.bat` passed all 765 tests,
formatting, lint, types, dependency/lock checks, both distribution builds and every
installed-wheel smoke test, including actual spelling search and exact application
after text repair. Native tests covered candidate/cell paging, category restrictions,
stale mappings, cancellation, shutdown and editor callback release. Linux, hosted
CI, real portfolios and capacity benchmarks were not run.

CSV/XML users now have a separate **CSV / XML text review...** dialog for complete
scopes, field mappings, repair/NFC, exact replacement, explicit cell approvals and
JSON audit saving. See [SOURCE_ADAPTERS.md](SOURCE_ADAPTERS.md). Existing Excel
spelling/recipe/workbook-export controls are not exposed through that adapter.
