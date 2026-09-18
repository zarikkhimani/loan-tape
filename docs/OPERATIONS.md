# Operating guide

Loan Tape supports local analyst review of CSV, XML, and Excel source data. Use
the [README](../README.md) for launch instructions and [Product](PRODUCT.md) for
current capabilities. Inspection findings require review against source evidence;
they do not establish a loan agreement violation or financial correctness.

## Before using portfolio data

Keep the original in its approved location. Use a workstation and storage location
authorized for the data, with suitable permissions, encryption, backups, and
retention. The application creates ordinary local files and does not supply these
controls. A project folder inside a synchronized Documents directory may be copied
by that service independently of Loan Tape; confirm the folder's actual sync policy.

First exercise installation and the intended workflow with a synthetic file. Use
Python 3.12 and the locked project environment. The optional background Excel reader
requires Windows and installed desktop Excel. `.xls`/`.xlsb` can be preserved, but
their in-app preview readers are not implemented.

## Daily review

1. Add a local file and wait for successful preservation. Review the filename,
   saved location, and original location in **Details**; duplicate names are separate
   entries. Extension acceptance does not validate the file's contents.
2. Review the selected file's capability label. For a previewable format, select
   **Open file** and review the full sheet/record-group inventory and explicit coverage
   errors. `.xls`/`.xlsb` remain preserved-only until a separate `.xlsx` copy is supplied.
   A visible page is only a window into the available data.
3. Review data set boundaries and header choices before saving. Workbook layout
   suggestions are editable and do not infer loan-field meaning. XML selections
   cover complete record groups.
4. Select the supported inspection/check operation explicitly. Retain raw values,
   source addresses/paths, chosen rule settings, and the source reporting context
   in the authorized review record. The fixed session date is the computer's launch
   date, not an inferred portfolio reporting date.
5. Investigate failed reads, stale selections, ambiguity, and incomplete coverage
   before relying on a result. Do not modify source values to force reconciliation.
6. Close any working copy opened manually in Excel, then use **Exit** and allow copying,
   owned-worker cleanup, and the session reset to complete. The application remains
   open with an error if Windows prevents deletion. Review artifacts are not a durable
   analysis export unless that feature explicitly says so.

**Open in Excel** opens the actual saved file in a normal user-owned Excel window.
It is separate from the controlled, disposable-copy comparison reader. Excel may
calculate or offer active content, and a manual save can change the intake copy.
For evidence-preserving work, prefer the in-app read-only preview and make a separate
working copy before manual editing. Close that workbook before Loan Tape so Windows
can remove the session copy. Loan Tape never terminates a user-owned Excel session.

## Local records and retention

Desktop launchers use the project folder. Direct CLI launches use their current
working directory for default runtime storage; `--storage-dir` can change intake.

| Location | Contents | Handling |
| --- | --- | --- |
| Original source location | User-supplied file | Retain independently; never rely on intake as the only backup. |
| `inputs/<id>/` | Session working bytes and manifest, including hash and original absolute path | Confidential temporary evidence; removed on normal application exit. |
| `.artifacts/sessions/` | Session timestamps, offset, reference date | Removed on normal application exit. Record required context in an authorized export. |
| `.artifacts/selections/` | Workbook data set definitions | Session-only; removed on normal application exit. |
| `.artifacts/xml-selections/` | Source-bound XML data set definitions and view positions | Session-only; removed on normal application exit. |
| `.artifacts/column-definitions/` | Source-bound mappings, units, date formats, and rule metadata | Session-only; removed on normal application exit. |
| `.artifacts/date-runs/` | Completed date-workflow settings, evidence, findings, and reconciliation | Session-only; use an explicit validated export for retained evidence. |
| `.artifacts/packs/` | Active catalog profiles and exact-content snapshots | Preserve to reproduce the chosen catalog. |
| Other `.artifacts/` subfolders | Temporary comparisons, column values/findings, ordering stores, and validation output | May contain confidential values; normal cleanup is not secure erasure. |
| `.local/` | Local analyst/developer notes, if used | Excluded from Git/builds; apply the same confidentiality rules. |
| `.venv/`, `.tools/`, `.cache/` | Local runtime and tooling | Recreate from setup/lockfile; do not treat as portfolio evidence. |

Retention periods must come from the data owner; this project does not invent a
bank retention schedule. A normal exit removes file-session storage but is not secure
erasure and cannot clean up after forced termination. Preserve approved evidence through
an explicit export or other authorized record before exiting. Dictionary profiles and
explicit exports remain separate. Do not delete a whole working directory as a routine
troubleshooting step.

## Control evidence

| Control | Implementation and check | Limit |
| --- | --- | --- |
| Source preservation and reset | `intake.py`, `workspace_reset.py`; reset/intake tests | Working-copy listing checks size/structure, not a fresh hash or authenticity; reset is not secure erasure. |
| Non-executing inspection | `inspection.py`, `xml_preview.py`, `excel_compare.py`, `excel_worker.py`; reader tests | Manual Open in Excel is a separate boundary. |
| Source-bound selections | `selection.py`, `xml_selection.py`; selection/navigation tests | Local writable metadata is not a tamper-proof audit ledger. |
| Literal values and review outcomes | Column and date services; corresponding tests | The bounded date workflow includes calendar screening and a review export; broader financial workflows remain separate milestones. |
| Owned-process cleanup | `excel_process.py`, `workers.py`; shutdown tests and optional Excel smoke checks | Office integration requires separate execution on Windows with Excel. |
| Distribution hygiene | `scripts/check.py`, `scripts/_distribution.py`; archive regression tests | Filename/path checks do not scan arbitrary file contents for secrets. |

The [security policy](../SECURITY.md) documents resource-limit gaps and other trust
boundaries. Tests provide evidence for specific cases, not blanket assurance.

## Failures and suspected incidents

For an ordinary error, record the application version, operation, visible message,
and whether the result was partial or unavailable. Reproduce with synthetic data.
Keep original paths, cell values, screenshots, and manifests out of public reports.

For suspected execution, disclosure, overwrite, or unexpected network activity,
stop processing that file, preserve relevant evidence in the approved location,
and contact the owner privately using [Security](../SECURITY.md). Do not repeatedly
open the suspicious workbook in Excel to investigate. Follow the organization's
incident procedure where one applies; this guide does not authorize external uploads.

## Maintenance

Run `check.bat` after local dependency or implementation changes. Dependency update
proposals require review and complete validation; there is no automatic merge.
The prepared Dependabot configuration takes effect only after an authorized push
and successful GitHub processing. Remote access, private reporting, alerts, branch
protection, and retention settings must be verified separately by the owner.

This guide adapts FinExtract's local processing, private reporting, and release
discipline, reviewed at revision `26985d12fd257a70931af3d017785ce49c9f610f`.
Loan Tape keeps its own locked tooling, source-preservation contracts, current
feature boundaries, and public-alpha distribution controls.
