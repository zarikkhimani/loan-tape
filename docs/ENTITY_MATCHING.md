# Reviewed borrower relationships

**Match borrowers** proposes relationships within a saved Excel data set. Each
source row remains separate. Matching never deletes rows, chooses a canonical
borrower name, changes identifiers, or equates facilities, tranches, holdings,
positions or reporting dates. Group approval records only a borrower relationship.

This is an optional Windows/Python 3.12 feature for small review populations.
It has synthetic runtime and preservation evidence, not independently measured
matching accuracy. No portfolio or labels are sent to a service.

## Optional runtime setup

Normal application setup does not install Dedupe. From the repository folder, run:

```powershell
.\dev.bat python scripts/setup_entity_matching.py --portable-compiler
```

This creates `.tools/entity-matching/` from the locked `entity-matching` dependency
group. Dedupe is pinned to 3.0.3 and BTrees to 6.4. The script verifies installation,
training, grouping, unchanged input records and reload of its own freshly generated
synthetic model. It compares the ordinary `.venv` inventory before and after.
Application work checks the verified package inventory again inside its worker.

On this Windows/Python 3.12 machine, two dependencies have no compatible index
wheels. The explicit portable option downloads the upstream LLVM MinGW
**20260616 UCRT x86-64** archive (about 179 MiB) into `.tools/phase7-toolchain/`,
verifies SHA-256
`b9b68a4d276e16fa25802aaba458e4638f64b3884c290aaccdc2d87083b6ca35`,
and builds the unmodified locked sources. Compiler selection and PATH changes
apply only to child processes. No host installer, administrator access, persistent
PATH change or different Python version is needed. Omit `--portable-compiler`
only when a compatible compiler is already available. Failure remains visible;
there is no automatic engine or interpreter substitution.

The runtime report and logs are in `.tools/entity-matching/`. The compiler archive,
licenses, environment and model binaries stay local and are excluded from source
and wheel distributions. The setup uses the upstream [portable toolchain release](https://github.com/mstorsjo/llvm-mingw/releases/tag/20260616);
the [upstream toolchain notes](https://github.com/mstorsjo/llvm-mingw#releases)
describe unpacked installation and runtime compatibility. Revalidate after changing
dependencies. These compiler binaries are not redistributed by Loan Tape.

## Review workflow

1. Activate **Loan text field definitions** and explicitly map borrower columns
   with **Define column**. Version 1.1.0 adds source borrower address and borrower
   identifier meanings. Review the address role and identifier namespace. Loan and
   facility fields cannot be selected as borrower matching features. Reactivate and
   remap if an older dictionary snapshot is active.
2. Save the complete Excel data set, then choose **Match borrowers** above the grid.
   Select one to six mapped borrower fields. Text uses Dedupe's String comparator;
   identifiers use Exact. At least one text feature is required. Nothing is selected
   automatically. Original text is the default; the optional checkbox freezes the
   reviewed text result available when this dialog was opened. Reopen to select a
   newer working result.
3. Choose **Prepare / restart labels**. This reads the entire saved row population,
   including hidden rows and blank tails. Inspect **Excluded rows**. A row is excluded
   if any selected feature is blank, absent, empty, a missing token, a number,
   boolean, formula, error, unreadable text, or text exceeding 4 KiB. Nothing is
   guessed, trimmed, case-folded, normalized, or converted to text for matching.
4. In **Label pairs**, review source-linked pairs. Enter a reviewer and evidence
   reason, then choose **Same borrower** or **Different borrowers**. Supply at least
   ten pairs of each class, including difficult and representative examples.
   Duplicate pairs and contradictory labels are refused. Restart preparation to
   revise labels; previous completed model runs remain recorded for the session.
5. Confirm that the labels represent this population and choose an explicit
   grouping threshold strictly between zero and one. **Train and propose groups**
   creates a fresh model. Labels train the model; they do not approve its results.
6. In **Review groups**, inspect full feature values, scores and raw source evidence
   in the details pane. Choose a row number and **Jump to source**. Explicitly approve
   or reject every group. A group contradicting a different-borrower label cannot be
   approved; correct the training review and rerun. **Unclustered rows** remain
   unclassified, not confirmed different borrowers.
7. Choose **Save reviewed relationships and audit...** and a new `.json` file.
   Saving rechecks original bytes, saved scope, dictionary mappings and the selected
   text revision. Existing files cannot be overwritten. A zero-group result can
   also be saved explicitly.

Changing selected features clears draft labels and candidates. Changing the
threshold clears candidate decisions and requires retraining. Changes to the saved
data set or dictionary invalidate the dialog. Cancellation and shutdown terminate
only this operation's owned worker job and wait for cleanup.

## Evidence and retention

The JSON export contains the saved source hash, sheet/range, source row and cell
references, mapped raw evidence and missingness, selected features,
optional reviewed text history, exclusions, all training labels and reviewer
evidence, every blocked candidate pair and score, proposed groups, unclustered
rows, model settings and SHA-256, dependency/compiler provenance, final decisions,
and accepted same-borrower relationships. If Dedupe omits a blocked pair from its
score output, the audit records a null score and explicit status rather than an
invented zero. The export does not contain executable
model bytes. It is a data-only audit and has no application import/retraining path.
Unmapped source columns remain in the unchanged original workbook; the matching
audit does not claim to be a full replacement loan tape. Original tokens over
16 KiB retain an explicit byte count and SHA-256 reference to the preserved source,
as in the transformation foundation; their text is not truncated or reconstructed.

Fresh model binaries and unreviewed run JSON are kept under
`.artifacts/entity-matching/` for the session. Normal Exit deletes those source-bound
files after owned workers stop. Explicit JSON exports and the optional runtime
survive Exit. Application processing never loads model files selected by a user;
only the setup smoke reloads the model it has just generated.

## Limits and validation

- Excel `.xlsx`/`.xlsm` saved selections only; 2–500 data rows, 1–6 features and at
  most 2,000 reviewed pair labels. Each source row remains individually identified.
- Every matching feature must have usable literal text. Numeric identifiers remain
  excluded; they are not reconstructed. Exclusions are fully accounted for.
- Each audit/model is limited to 64 MiB; training times out after 300 seconds.
  Larger-population capacity has not been established.
- No independent labeled holdout corpus was supplied. Synthetic fixtures establish
  runtime and preservation behavior only. Precision, recall, calibration and actual
  borrower identity are not established by training success or a high score.
- Relationships do not yet compose into text/date Excel exports, reusable recipes,
  other data sets, CSV or XML. Model/label import is not implemented.
- Linux and hosted CI have not been verified for the optional runtime.

For source checks, distribution builds, installed-wheel actual matching and owned
worker cleanup, use:

```powershell
.\check.bat --entity-smoke
```

Add `--excel-smoke` to recheck the separate desktop Excel export paths as well.

Local validation on **19 October 2026 UTC**, Windows/Python 3.12.14: the full
`check.bat --entity-smoke --excel-smoke` passed **858 tests**, formatting, lint,
type checks, lock/dependency checks, source/wheel builds and installed-wheel smoke
workflows. Actual matching exercised Unicode names, literal zero-prefixed borrower
IDs, 12 constructed groups across 24 eligible rows, two explicit exclusions, JSON
audit output, source preservation, timeout/cancellation cleanup and session reset.
The separate xlwings 0.37.4 text/recipe/date export smoke also passed. The recipe UI
test isolates optional Office preview startup; dedicated tests still execute Excel.
This is local synthetic evidence, not a hosted CI, Linux or independent accuracy result.
