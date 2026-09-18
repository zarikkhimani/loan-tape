# Security policy

## System and scope

Loan Tape is a public alpha desktop and Python application for preserving and
reviewing loan-portfolio files. This policy covers `src/loan_tape/`, the CLI,
desktop launchers, local metadata, dictionary packs, dependencies, and build and
validation tooling. Windows with Python 3.12 is the current desktop target.

The input boundary is CSV, XML, and Excel. PDF extraction/OCR integration, hosted
services, automated credit decisions, and production deployment are not current
features. This policy records engineering requirements; it is not bank approval,
regulatory certification, a completed security audit, or a claim of financial
correctness. See [Product](docs/PRODUCT.md) for the maintained feature scope.

## Supported versions

| Version | Security updates |
| --- | --- |
| Latest `0.1.x` release | Yes |
| Current `main` branch | Development fixes only; may be incomplete |
| Earlier or modified copies | No guaranteed updates |

This alpha has no long-term-support commitment. Upgrade to the latest tagged
`0.1.x` release before reporting a problem that may already be fixed.

## Reporting a concern

Report suspected vulnerabilities privately to the repository owner. Where enabled,
use [GitHub private reporting](https://github.com/zarikkhimani/loan-tape/security/advisories/new).
If that route is unavailable, contact the owner through an existing private channel;
do not fall back to a public issue. Private reporting availability and response
commitments have not been established by this local setup.

Include the affected revision/version, operating system and Python/Excel versions,
the reachable operation, expected and observed behavior, impact, and a minimal
synthetic reproduction. Remove borrower details, portfolio values, original paths,
credentials, and confidential screenshots/logs. Do not attach live source files or
intake manifests. Ordinary bugs can use the repository's issue templates.

Remediation should target the current development version and include a regression
case. No response-time SLA is established.

## Assets and trust boundaries

- **Protect:** original files and session intake copies; borrower and portfolio information;
  raw identifiers and values; file hashes, locations, selections, and source lineage;
  local credentials; and unrelated user Excel sessions.
- **Untrusted input:** file bytes, filenames, CSV fields, XML names/attributes/text,
  workbook formulas and relationships, imported pack JSON, and reference material.
  Local origin, a permitted extension, or a familiar filename does not establish trust.
- **Operator boundary:** the desktop and Python API run with the current user's
  filesystem permissions. This is a single-user local workflow, with no application
  authentication, tenant isolation, encrypted store, or tamper-proof audit archive.
- **Parsing boundary:** automated inspection interprets data without executing
  source formulas, macros, links, schemas, stylesheets, or pack-provided code.
- **Excel boundary:** automatic comparison admits only conservatively checked
  plain-data workbooks, uses a disposable read-only copy, and owns its helper
  processes. The explicit **Open in Excel** action instead launches normal visible
  Excel with the saved file; Excel's settings and the operator's actions apply.
- **Distribution boundary:** local intake, analysis artifacts, reference research,
  credentials, and logs must not enter source control or release archives. Setup
  downloads packages; application inspection has no upload or telemetry integration.

## Security invariants

1. Preserve original bytes and session intake copies while processing. Publish completed
   intake atomically, retain SHA-256 and source-location evidence, and reject observed
   changes during copying. Normal application exit removes session copies and
   source-linked state after workers stop without changing the original. A digest
   provides identity evidence, not proof of authenticity.
2. Validate filenames before filesystem access. Reject explicit network/UNC and
   Windows device source paths. Do not allow file-derived paths or package
   relationships to escape their intended data boundary.
3. Automated readers must not calculate formulas, execute macros, update external
   links, fetch source-specified resources, or save inspected workbooks. Unsafe or
   unsupported Excel-comparison features must produce a visible skip/error.
4. XML parsing must reject DTD/entity use and enforce its documented structural and
   size limits. No schema-hint or stylesheet retrieval is permitted.
5. Preserve raw values and source coordinates. Distinguish missing, empty, zero,
   invalid, ambiguous, and unreadable values. Do not repair identifiers, infer
   financial meaning, or turn partial analysis into a successful complete result.
6. Bind saved selections and analysis evidence to their source identity. Keep
   corrupt, stale, unsupported, and cancelled results visibly distinguishable.
7. Treat packs as validated, versioned data. Activation is explicit and snapshots
   are checked; source references are evidence, not instructions to execute or fetch.
8. Shut down only application-owned workers and Excel processes. A cancelled read
   must not publish partial success or terminate unrelated user sessions.
9. Use synthetic tests and keep confidential data out of commits, issue reports,
   logs submitted for support, and distributions. Future exports must preserve
   literal source text and the separate-output writer policy in `AGENTS.md`.

## Findings and severity

Report concrete, reachable breaches of these boundaries: unintended execution or
network access, path traversal, unauthorized disclosure or overwrite, loss of source
integrity, misleading completion after missing data, or termination of unrelated
processes. File-triggered workstation resource exhaustion is also relevant.

Explain the attacker-controlled input, entry point, necessary operator action,
existing controls, demonstrated impact, and uncertainty. Distinguish automatic
inspection from deliberate manual opening in Excel. Local-only operation does not
make malicious source files safe; severity depends on realistic reachability and
impact rather than a generic web-service threat model.

No finding class is blanket-excluded and no new accepted-risk decision is made by
this policy. Unimplemented services are not deployed attack surfaces; their eventual
introduction requires a policy review. Known limitations below remain eligible for
assessment, rather than being instructions to suppress findings.

## Known limitations

- Intake's 100 MiB limit and preview's 20-row/10-column display page are not universal
  memory, CPU, or elapsed-time limits. Automatic OOXML readers now share member,
  per-part, aggregate expanded-byte, path, encryption, and compression-ratio checks;
  XML readers have separate structural budgets. These declarative checks are not a
  killable process sandbox, so complex third-party parser work can still consume
  substantial resources within the accepted limits.
- Local XSD dependencies are enumerated, confined, size/count/depth bounded, and
  hash-bound before schema compilation. The compiler still runs in the application
  process; valid-but-complex schemas are not subject to a hard memory or elapsed-time
  limit.
- Dictionary packs have per-file, per-collection, aggregate pack/profile, and
  cancellation limits. Valid content is still parsed locally and should be reviewed
  before activation.
- Current-session file history validates manifest structure and saved-file
  existence/size; listing does not rehash every file. Hashes and local metadata can
  be edited by anyone with access to the working directory. No authenticity or
  malicious concurrent-writer guarantee is made.
- Path checks are not a workstation network policy: mapped drives, redirects, and
  operating-system permissions require separate administration.
- **Open in Excel** is outside automated inspection restrictions. It can invoke
  Excel's normal interpretation, calculation, links, and prompts, and permits the
  operator to save changes to the intake copy. Close that workbook before application
  exit; a Windows file lock prevents reset and produces a visible error rather than
  silently claiming cleanup. Use it only when that is intended.
- Local artifacts can contain source values and original absolute paths. Normal exit
  removes named file-session locations but is not secure erasure; forced termination,
  filesystem errors, or interrupted work may leave temporary material.
  Backup, encryption, permissions, retention, and endpoint protection belong to the
  operating environment. Git ignore patterns are not access controls.
- Third-party parsers, Excel, Python/Tk, and build tools remain dependencies. Locked
  versions and passing tests do not establish that they are vulnerability-free.

Use the [operating guide](docs/OPERATIONS.md) for storage, review, and incident
handling, and the [release checklist](docs/RELEASING.md) for validation evidence.
