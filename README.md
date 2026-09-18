# Loan Tape

Loan Tape helps analysts inspect loan-portfolio data supplied as Excel, XML, or
CSV, review potential issues, and trace findings back to the original source.

It is being developed for **Private Credit, BDC, NAV, CFO/CDO, and SRT loan-tape
workflows**.

It runs locally and keeps original files unchanged. Analysts choose the data to
review and the checks to apply; ambiguous values remain visible for review.

> **Work in progress:** Version 0.1.0 is an early alpha, with features and coverage
> still being developed. Review findings and exported
> workbooks against the source before use. The project is not bank-approved or a
> substitute for underwriting, agreement review, or institutional model validation.

## Start here

The Windows desktop application is the simplest way to evaluate the project.

### Requirements

- Windows and Python **3.12**, including Tcl/Tk for the desktop interface.
- Internet access for the first installation.
- A local file containing synthetic data for your first review.
- Desktop Microsoft Excel **only for date-workflow exports and optional Excel
  integration**. Basic in-app inspection does not require Excel.

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
5. Finish with **Exit**. Normal exit clears temporary working copies and session
   analysis. Your originals, explicit exports, and dictionary packs remain.

A saved data set is the full selection to review; the preview shows only a page.
For XML steps, date exports, and detailed controls, see the [User guide](docs/USER_GUIDE.md).

## Supported files

| File | Available in 0.1.0 |
| --- | --- |
| Excel `.xlsx`, `.xlsm` | Worksheet navigation, saved data sets, complete-column inspection and checks, ordering, and date review/export. Source macros and formulas are not executed by in-app readers. |
| XML `.xml` | Record-group navigation, saved data sets, complete-column inspection and checks, ordering, and optional validation against a local XSD schema. |
| CSV `.csv` | Initial preview with separator and encoding controls. Saved data sets and complete-column checks are not yet available. |
| Excel `.xls`, `.xlsb` | Temporary working-copy preservation only. Supply a separate `.xlsx` copy for in-app review. |

Files must be local and no larger than **100 MiB**. PDF and OCR are not supported
in this release. The Files screen shows the selected format's available actions.

## Review results and Excel output

**Inspect column** summarizes every data row in a saved Excel or XML selection.
**Check column** flags values against your chosen Identifier, Text, Number, or Date
expectation. Findings retain source locations; a flag calls for review.

For a saved Excel data set, **Date workflow** lets you map date columns, choose
interpretation rules, and then run a separate set of red-flag checks.
**Export refined loan tape** writes a new Excel workbook containing:

- **Loan Tape:** the complete selected data set, with successfully interpreted
  mapped dates standardized and unresolved values retained literally.
- **Summary** and **Findings:** review totals and items needing attention.
- **Date Results**, **Pair Results**, and **Audit:** supporting evidence and settings.

This export requires Windows and desktop Excel. It preserves the original file
and refuses to overwrite an existing output. See [Date review and export](docs/DATE_ANALYSIS.md)
for the workflow and its limits. Other inspection/check dialogs do not yet export results.

## Review and control features

- Original source files remain unchanged; review uses a separate working copy.
- Blank values, zeroes, missing-value tokens, and source errors remain distinguishable.
- In-app readers do not calculate source formulas, run macros, or refresh links.
- Column checks and date interpretations use choices you make explicitly.
- Date calendar screening uses published SIFMA U.S. fixed-income schedules for
  **2019–2027**. Uncovered weekdays remain unknown; calendar flags require agreement
  context. See the [calendar guidance](src/loan_tape/guidance/SIFMA_CALENDAR.md).
- Versioned dictionary packs describe field meanings and allowed values.
- The application has no upload or telemetry integration.

## Important limitations

- General financial normalization, portfolio reconciliation, and credit decisions
  are not implemented.
- Saved column definitions do not yet execute a full set of portfolio rules.
  Rate parsing is currently available only through Python.
- XML export and PDF/OCR integration remain future work.
- Normal exit clears working copies, saved selections, column definitions, and
  saved date runs. Export any completed date review you need to retain.
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
behavior. GitHub Actions is configured for Windows and Linux; hosted results will
be available after the code is pushed. See [Contributing](CONTRIBUTING.md) for
development commands and Linux setup.

## Project documentation

- [Documentation index](docs/README.md) — choose a guide by task.
- [User guide](docs/USER_GUIDE.md) — setup help and detailed desktop instructions.
- [Operating guide](docs/OPERATIONS.md) — local records, retention, and failure handling.
- [Product and scope](docs/PRODUCT.md) · [Roadmap](docs/ROADMAP.md)
- [Architecture](docs/ARCHITECTURE.md) · [Release checklist](docs/RELEASING.md)
- [Changelog](CHANGELOG.md)

## License

Loan Tape is available under the [MIT License](LICENSE).
