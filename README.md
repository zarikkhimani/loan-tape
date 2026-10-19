# Loan Tape

Loan Tape is a Windows desktop application for inspecting loan-portfolio data
supplied as Excel, CSV, or XML. Analysts can review potential issues, approve text
changes, reuse cleanup recipes, review borrower relationships, and create outputs
that retain source evidence and review decisions.

It is being developed for **Private Credit, BDC, NAV, CFO/CDO, and SRT loan-tape
workflows**.

It runs locally and keeps original files unchanged. Analysts choose the data to
review and the checks to apply; ambiguous values remain visible for review.

> **Early alpha:** This README describes the **0.2.0 alpha release candidate**.
> See the [0.2.0 changelog](CHANGELOG.md#020---2026-10-19) for changes awaiting
> publication. Features and coverage are still being developed.
> Review findings and outputs against the source before use. The project is not
> bank-approved or a substitute for underwriting, agreement review, or institutional
> model validation.

## Start here

Windows is the primary desktop platform. Use it for the complete workflow,
including exports through desktop Microsoft Excel.

### Requirements

- Windows and Python **3.12**, including Tcl/Tk for the desktop interface.
- Internet access for the first installation.
- A local file containing synthetic data for your first review.
- Desktop Microsoft Excel **only for workbook exports and optional Excel
  integration**. In-app inspection, text review, and recipe creation work without it.
- Borrower matching requires a separate optional local runtime. Follow the
  [borrower-matching setup guide](docs/ENTITY_MATCHING.md#optional-runtime-setup)
  before using **Match borrowers**; normal setup does not install it.

### Install and run

Download the repository using **Code → Download ZIP** on GitHub and extract it,
or clone it. Open PowerShell in the project folder and run these commands in order:

```powershell
.\setup.bat
.\start-ui.bat
```

Setup creates an isolated environment inside the project folder. After setup,
double-click **start-ui.bat** whenever you want to open the app.
See [setup help](docs/USER_GUIDE.md#setup-and-launch-help) if Python is not found.

### Review your first file

Use a synthetic `.xlsx` file for the complete introductory workflow.

1. Select **Add file**, or drag your file into the window. Wait for its working
   copy to appear in **Files**.
2. Select the file and choose **Open file**.
3. Review the worksheet, full data range, and header row. Name the selection and
   choose **Save data set**. This saves the setup without changing the workbook.
4. Select a column and choose **Inspect column** to see blanks, types, and repeated
   values, or **Check column** to test an expectation you choose. Review findings
   and use **Jump to cell** to inspect their source.
5. To review text changes, activate **Loan text field definitions** in **Dictionary
   packs**. Select a text column, choose **Define column**, and confirm its field
   meaning and any missing-value tokens. Headers do not establish field meaning.
6. Choose **Clean text**, then **Preview cleanup**. Review proposals and their
   source evidence, choose **Include selected changes**, enter a reviewer and
   reason, and choose **Apply selected changes**. You can save ordered cleanup
   steps through **Recipes** for fresh review on another compatible data set.
7. With desktop Excel installed, choose **Export reviewed result...** in **Clean
   text** to save a new workbook containing the reviewed result and its audit.
   Use the separate date workflow if you also need date review. For CSV/XML text
   review, save a JSON audit using the [format-specific workflow](docs/SOURCE_ADAPTERS.md).
8. Finish with **Exit** after saving any results you need. Originals, explicit
   exports, saved recipes, and dictionary packs remain; working copies and
   source-bound session results are cleared.

A saved data set is the full selection to review; the preview shows only a page.
For XML steps, date exports, and detailed controls, see the [User guide](docs/USER_GUIDE.md).

## Supported files and capabilities

The following features are available in the **current source build**. Text changes
require explicit field mappings and individual approval.

| Capability | Excel `.xlsx`, `.xlsm` | CSV `.csv` | XML `.xml` |
| --- | --- | --- | --- |
| Preview and save a complete data set | Yes | Yes, with explicit reading conventions | Yes, within a selected record group |
| Inspect/check complete columns and order the view | Yes | No | Yes |
| Define field meanings using dictionaries | Yes | Yes, in CSV / XML text review | Yes, in CSV / XML text review |
| Review text repair and exact replacements | Yes | Yes | Yes |
| Spelling suggestions and reusable recipes | Yes | No | No |
| Review borrower relationships | Optional, 2–500 data rows | No | No |
| Date interpretation and calendar review | Yes | No | No |
| Validate against a selected local XSD | No | No | Yes |
| Export a reviewed Excel workbook | Yes, requires desktop Excel | No | No |
| Save a separate JSON audit | Borrower relationships | Reviewed text changes | Reviewed text changes |

Files must be local and no larger than **100 MiB**; individual workflows have
additional limits described in their guides. `.xls` and `.xlsb` files support
temporary working-copy preservation only. Supply a separate `.xlsx` copy for
in-app review. PDF and OCR remain outside the current implementation.

**CSV / XML text review...** adds complete source scopes, explicit dictionary mappings,
reviewed text changes and separate JSON audits. See [CSV/XML text review](docs/SOURCE_ADAPTERS.md).

## Review workflows

**Inspect column** summarizes every data row in a saved Excel or XML selection.
**Check column** flags values against your chosen Identifier, Text, Number, or Date
expectation. Findings retain source locations; a flag calls for review.

**Clean text** previews garbled-character repairs, optional Unicode normalization,
spelling suggestions and exact replacements for an explicitly mapped column.
Spelling search accepts free text; category replacements require allowed values.
You choose each change, provide a reviewer and reason, and apply it to a separate
session result. Activate the supplied **Loan text field definitions** dictionary
and use **Define column** first. See
[Reviewed text cleanup](docs/TEXT_CLEANUP.md).

**Clean text → Recipes** saves ordered cleanup settings and literal rules for reuse.
Loading requires a fresh compatibility review and per-step cell approvals. Saved
recipes survive Exit; incomplete runs publish no partial result. See
[Reusable cleanup recipes](docs/RECIPES.md).

**Match borrowers** provides optional local Dedupe training, explicit pair labeling,
and candidate-group review for saved Excel data sets of **2–500 data rows**. Every loan
row stays separate; approving a relationship does not merge rows or standardize
borrower identities. The feature has synthetic runtime checks, with independent
matching-accuracy evaluation still pending. See
[Borrower relationships](docs/ENTITY_MATCHING.md) and its
[optional runtime setup](docs/ENTITY_MATCHING.md#optional-runtime-setup).

**Date workflow** lets you map date columns in a saved Excel data set, choose
interpretation rules, and then run a separate set of red-flag checks. A flag calls
for review against the source and the governing agreement. See
[Date review and export](docs/DATE_ANALYSIS.md).

## Export and audit outputs

Choose a new output file to retain a completed review. Workbook exports require
Windows and desktop Excel. Existing output files cannot be overwritten.

| Action | Output | Contents |
| --- | --- | --- |
| Clean text → Export reviewed result... | New `.xlsx` workbook | Complete selection, approved text changes, summary, ordered steps, cell decisions, source evidence, and audit. A compatible saved date run can be included explicitly. |
| Date workflow → Export refined loan tape | New `.xlsx` workbook | Complete selection with successfully interpreted dates standardized, plus Summary, Findings, Date Results, Pair Results, and Audit sheets. |
| Match borrowers → Save reviewed relationships and audit... | New `.json` audit | Reviewed borrower relationships, selected features, training labels, candidate decisions, exclusions, and source evidence. Every source row remains separate. |
| CSV / XML text review → Save JSON audit... | New `.json` audit | Original mapped evidence, proposed and approved text changes, review decisions, settings, and source locations. |

Reviewed text/recipe exports create a **new values-only workbook**. Source tokens,
including numeric tokens and identifiers, stay literal text; included standardized
dates use ISO `YYYY-MM-DD` text. Source formulas remain literal expressions, with
their evidence retained. Source formatting, macros, connections, and links are not
copied. See [Reviewed text export](docs/TEXT_EXPORT.md) for output meanings and limits.

CSV/XML audits record the review and do not create a transformed CSV/XML data file.
Borrower relationships are not incorporated into Excel exports. Standalone date
exports do not include text-cleanup results; use reviewed text export to combine
compatible text and date work. Other inspection/check dialogs do not yet export results.

## Review and control features

- Original source files remain unchanged; review uses a separate working copy.
- Blank values, zeroes, missing-value tokens, and source errors remain distinguishable.
- In-app readers do not calculate source formulas, run macros, or refresh links.
- Column checks and date interpretations use choices you make explicitly.
- Text changes retain source evidence, reviewer decisions, reasons, and ordered
  history. Changed sources, mappings, dictionaries, or settings require fresh review.
- Recipe runs publish a complete result only after every step passes validation;
  failed or cancelled runs retain the prior result. Exports validate saved output
  and protect original sources and existing output files.
- Date calendar screening uses published SIFMA U.S. fixed-income schedules for
  **2019–2027**. Uncovered weekdays remain unknown; calendar flags require agreement
  context. See the [calendar guidance](src/loan_tape/guidance/SIFMA_CALENDAR.md).
- Versioned dictionary packs describe field meanings and allowed values.
- The application has no upload or telemetry integration.

## What is kept after Exit

- **Retained:** original source files, explicitly saved workbook/JSON exports,
  saved recipes, dictionary packs, and active dictionary profiles.
- **Cleared on normal Exit:** intake working copies, saved data-set selections,
  source field mappings, date runs, derived text results, and source-bound borrower
  training runs and model files, after owned workers stop.

Save any completed review you need through an explicit export or audit before
exiting. Recipes retain reusable settings and literal rules; they do not preserve
the session's reviewed data result or transfer cell approvals to a new source.
Saved recipes and exports can contain confidential text. See the
[Operating guide](docs/OPERATIONS.md#local-records-and-retention) for storage and handling.

## Important limitations

- General financial normalization, portfolio reconciliation, and credit decisions
  are not implemented.
- Saved column definitions do not yet execute a full set of portfolio rules.
  Rate parsing is currently available only through Python.
- Spelling suggestions, reusable recipes, borrower matching, date workflows, and
  workbook exports currently require saved Excel data sets. CSV/XML text review
  supports text repair and exact replacements, with separate JSON audits.
- Transformed CSV/XML data-file exports and PDF/OCR integration remain future work.
- Forced termination can leave temporary files. If an Excel window locks a working
  copy, close it and retry **Exit**.
- **Open in Excel** is a separate manual action: Excel uses its normal settings and
  may calculate formulas or offer active content.

## Privacy and security

Keep real portfolios and generated results outside Git. Use synthetic data in
issues, tests, and screenshots. The app uses ordinary local storage; follow your
organization's data-handling requirements.

Read the [Operating guide](docs/OPERATIONS.md) for retention and failure handling,
and the [Security policy](SECURITY.md) for security boundaries and private reporting.

## Development

Use `.\run.bat --help` for command-line options. From a configured checkout, run:

```powershell
.\check.bat
```

This checks dependencies, formatting, types, tests, builds, and installed-package
behavior using synthetic fixtures. With desktop Excel installed and the optional
[borrower-matching runtime](docs/ENTITY_MATCHING.md#optional-runtime-setup) set up,
also exercise actual Excel exports and Dedupe execution from the installed wheel:

```powershell
.\check.bat --excel-smoke --entity-smoke
```

These checks cover source preservation, reviewed changes, output validation,
cancellation, and owned-worker cleanup. They do not establish real-portfolio
coverage or independently measured matching accuracy.

GitHub Actions runs the standard checks on Windows and Linux to check portability
of the core processing. Linux is optional for development; it is not required to
use the Windows app and does not support its desktop Excel integration.

Local checks and hosted GitHub Actions are separate runs. Hosted results become
available after a push or pull request; a local Windows pass does not establish
that Linux or hosted checks have passed. See [Contributing](CONTRIBUTING.md) for
development commands and Linux setup.

## Project documentation

- [Documentation index](docs/README.md): choose a guide by task.
- [User guide](docs/USER_GUIDE.md): setup help and detailed desktop instructions.
- [Operating guide](docs/OPERATIONS.md): local records, retention, and failure handling.
- [Product and scope](docs/PRODUCT.md) · [Roadmap](docs/ROADMAP.md)
- [Architecture](docs/ARCHITECTURE.md) · [Release checklist](docs/RELEASING.md)
- [Changelog](CHANGELOG.md)

## License

Loan Tape is available under the [MIT License](LICENSE).
