# Reusable cleanup recipes

Phase 5 adds **Clean text → Recipes** for saved Excel data sets. A recipe is an
ordered plan of reviewed text-repair settings and exact replacement rules. Saving
it is explicit and persistent. Loading it does not run a transformation, approve
any cells or change a workbook.

## Save a recipe from reviewed work

1. In **Clean text**, preview and apply the repair or exact-rule steps you want to
   reuse. Each step still needs its own cell review. You can work across mapped
   columns by reopening Clean text on another column in the same data set.
2. Open **Recipes**. Enter a **Recipe name**, **Source / template profile** and
   **Applicability / reporting context**. Describe which source template, roles and
   reporting circumstances make these operations appropriate. Use `1.0.0` for an
   initial version.
3. Choose **Capture working steps**. This creates a draft from the current working
   result's complete ordered history. It does not save a file. The draft includes
   the configured rules and settings, including rules whose individual occurrences
   were rejected. It never copies old cell approvals to a new run.
4. Inspect the ordered steps and full parameter details. **Move up**, **Move down**
   and **Remove step** change the draft. Order matters: a later step receives only
   values explicitly approved in earlier steps. A recipe must retain 1–12 steps.
5. Choose **Save recipe**. The library refreshes after the save succeeds.

Saving retains the template name, applicability description, mapped field meanings,
dictionary versions/fingerprints, literal headers and duplicate occurrences,
mapping rules/context, ordered operations and complete literal replacement tables.
The recipe does not retain the old source file, its cell population, cell approvals,
old spelling scores or source-specific suggestion matches. Literal rules can still
contain confidential borrower names, and field notes may also contain sensitive text.

To change operation settings or literal rule values, review the revised operations
in Clean text and capture the resulting working history. The recipe editor supports
ordering/removal, not arbitrary code or parameter scripting.

## Reuse on a source

1. Preserve the input, save its complete data set and explicitly define its columns
   against the appropriate active dictionary. A recipe never creates these mappings
   automatically.
2. Open **Clean text → Recipes**, select a library entry and choose **Load selected**.
   Inspect the template, applicability, mapped schema and every ordered step.
3. Enter the **Current run context** and **Reviewer**. Confirm that you reviewed
   the template, mappings and reporting context for this source, then choose
   **Bind source and review recipe**.
4. In the step window, choose **Preview cleanup**. Review the whole population and
   source details, include only the intended changed cells, enter a reason and choose
   **Approve step**. Highlighting a cell is not approval. Approving with no included
   cells explicitly leaves that step unchanged.
5. Repeat the fresh preview and cell review for every step. The final action is
   **Approve and publish recipe**. It rechecks the entire run before publishing one
   complete session result.

Runs start from the original source evidence. Earlier approvals are staged in
memory; they do not update the current working result or publish intermediate
files. Only the successful final step selects the completed result in Clean text.
The prior working result remains selected if the recipe is discarded or fails.

The source file, sheet, data-set name, row count and absolute range location may
differ between runs. Compatibility requires the same selected-column count,
header/no-header convention, relative mapped-column positions, exact mapped headers
and duplicate occurrences, complete frozen field definitions and mapping settings.
Unmapped columns stay outside processing. Missing, additional or changed mappings,
changed dictionary versions, reordered fields and changed missing-token conventions
require explicit repair of the mappings or a new compatible recipe. There is no
fuzzy header matching or automatic field remapping.

The reviewer confirms business applicability and current reporting context; the
software verifies the recorded structural bindings. The source hash and complete
snapshot bind this one run. Another source needs its own confirmation and previews.
Similarity searches are not recipe steps: a chosen spelling is stored as an exact
literal replacement and must be reviewed again against the new source's cells.

## Versions and retention

Saved files live at `.artifacts/recipes/<recipe-id>-<version>.json`. They survive
normal **Exit**, unlike intake copies, mappings and source-bound run results. The
folder is excluded from Git and distribution packages. Back up or remove retained
recipes deliberately according to the data owner's requirements.

A recipe has a stable ID, a `major.minor.patch` version, format version and content
fingerprint. Saving refuses to overwrite an existing ID/version. After loading and
editing a recipe, choose a new version to retain the same ID, or **New copy ID** to
create an independent recipe. An unsuccessful save leaves existing versions intact.
Malformed library entries show an error and cannot run; they are not silently skipped.
Fingerprints detect content changes; these local files are not authenticated signatures
or a tamper-proof audit service.

Draft edits disappear when their window closes. **Discard recipe run**, cancellation,
changed mappings/dictionaries and processing failures discard staged approvals.
The application waits for owned workers on Exit. Cancellation before atomic
publication leaves no result; it does not undo a save or complete publication that
has already finished. A failed later step never publishes a partial recipe.

Applied results retain the recipe ID/version/fingerprint, explicit source binding,
profile, current context, binding reviewer/time, step number, operation parameters,
every cell outcome and fresh cell approvals. The complete recipe and binding are
also saved with a completed recipe run. Later ordinary cleanup steps retain prior
recipe operation evidence in their history. Normal Exit clears source-bound results;
it leaves saved recipes intact. Phase 6 adds [reviewed workbook export](TEXT_EXPORT.md)
for completed recipes. Intermediate staged steps cannot be saved or reopened as
completed results, exported, or used for borrower matching. These boundaries share
the same ordered-history validation, including when a caller uses the lower-level
transformation persistence API.

## Limits and verification

Only the pinned ftfy repair operation and versioned literal replacement operation
are executable recipe steps. Unknown operations, engine/configuration versions,
executable expressions and unsupported keys fail explicitly. No Python, regex,
network callback or arbitrary file operation can run from a recipe.

Recipes permit 12 steps and a 16 MiB serialized file. The library permits 500 files
and a 64 MiB bounded inventory read. Existing limits also apply: 200 exact rules and
4 MiB parameters per rule step, 16 KiB tokens, 200,000 mapped cells and 128 MiB run
evidence. These are safety limits, not measured capacity claims. Long histories may
reach the evidence limit before the other bounds.

Service tests exercise save/load/version collisions, fresh-source and shifted-range
bindings, strict data-only validation, ordered parent values, zero-choice approvals,
late engine failures, cancellation, staging races and retention after Exit. Native
tests exercise the recipe library, capture/save/load, ordered review, discard, stale
mappings, callback release and shutdown during preview/application. The installed
wheel smoke runs a saved recipe on a second fictional source and verifies both
source preservation and recipe retention after session reset.

Validation on 19 October 2026 UTC: Windows `check.bat` passed **802 tests**,
formatting, lint, strict type checks, dependency/lock checks, source/wheel builds
and all installed-wheel smoke tests using Python 3.12.14. This includes 32 recipe
service cases and five native recipe scenarios. Atomic publication checks used the
existing project-local environment outside the restricted filesystem sandbox; no
host configuration changed. Hosted CI, Linux, real portfolios and large-population
capacity remain unverified.
