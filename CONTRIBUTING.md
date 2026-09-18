# Contributing

Start with Python 3.12 and the setup commands in [README.md](README.md). Setup is project-local; no activation or global tooling install is necessary.

Loan Tape is an alpha and welcomes focused bug fixes, tests, documentation, and
small feature proposals that fit the maintained [product scope](docs/PRODUCT.md).
Please do not attach real loan tapes, borrower information, intake manifests,
credentials, or confidential screenshots to an issue or pull request.

## Before opening a pull request

1. Search existing issues and open a feature request before a large behavioral or
   data-model change.
2. Create a focused branch from `main`; do not combine unrelated cleanup.
3. Use synthetic fixtures and preserve the source/lineage invariants in `AGENTS.md`.
4. Add or update regression coverage and user-facing documentation with the change.
5. Run `check.bat` on Windows or `python scripts/check.py` in the configured
   environment on Linux.
6. Open a pull request using the template, state what passed or was skipped, and
   call out any data, Excel, security, or compatibility limitations.

Report suspected vulnerabilities through the private route in
[SECURITY.md](SECURITY.md), not a public issue.

## Everyday commands

On Windows, run `setup.bat` once and use the wrappers below from the project folder.

```powershell
.\run.bat --help
.\check.bat
.\dev.bat ruff format .
.\dev.bat pytest
```

On Linux, prepare the environment with an existing Python 3.12 installation:

```sh
python3.12 scripts/setup.py
.venv/bin/python -m loan_tape --help
.venv/bin/python scripts/check.py
```

For targeted tools, use `.venv/bin/python scripts/dev.py <command> [arguments]`.
Desktop use additionally requires Tcl/Tk and a graphical display. Windows is the
verified desktop target; date-workflow Excel export requires Windows and desktop Excel.
The full check entry point is `python scripts/check.py` from a configured environment
on either operating system.

Setup, checks, and `dev.bat` automatically keep temporary files and uv, pip, Ruff,
and mypy caches under `.cache/`. Direct `python -m pytest` runs also configure
local temporary storage and a persistent pytest cache. Pytest storage is separated
by the actual executing account, so Windows sandbox commands do not reuse a
private temp directory owned by the interactive user. Pytest still manages unique
run directories and its normal retention; no shared `--basetemp` is forced.

These settings apply only to the launched process and its children. They do not
change Windows permissions, PATH, or system environment variables. Storage errors
remain visible; there is no fallback to a Windows temp/cache folder. `.cache/` is
ignored by Git and excluded from distribution archives.

When calling uv directly for dependency maintenance, keep its cache local and prevent automatic interpreter downloads:

```powershell
$env:UV_CACHE_DIR = Join-Path $PWD '.cache\uv'
$env:UV_PYTHON_DOWNLOADS = 'never'
```

Use `dev.bat` for targeted checks to avoid manually setting environment variables.

Tooling documentation: [uv projects and lockfiles](https://docs.astral.sh/uv/guides/projects/) and [uv build file selection](https://docs.astral.sh/uv/concepts/build-backend/#file-inclusion-and-exclusion). The build explicitly excludes local environments, caches, and supplied reference documents.

## Dependencies

Runtime dependencies belong in `[project.dependencies]`; development tools belong in `[dependency-groups].dev`. Use the pinned local uv executable to update `uv.lock`, then run setup and checks. Do not hand-edit the lockfile.

```powershell
.\.tools\Scripts\uv.exe add <package>
.\.tools\Scripts\uv.exe add --dev <development-package>
.\.tools\Scripts\uv.exe lock --upgrade-package <package>
```

Add CSV and Excel dependencies only when implementing their milestones. PDF extraction and conversion functionality already exists separately and will be integrated in a later phase. Until that integration is requested, keep PDF/OCR parsers, engines, and model dependencies outside the current scope. The bundled research recommendations are candidates to verify, not an installation checklist.

The prepared Dependabot configuration uses the [uv ecosystem](https://docs.astral.sh/uv/guides/integration/dependabot/)
for the manifest/lockfile and separately checks GitHub Actions weekly. It does not
auto-merge updates. uv/uv_build upgrades are manual so `.uv-version`, the required uv
version, and the build-backend pin remain aligned. Review those pins during release
preparation even when no update proposal appears. Hosted update behavior is unverified
until the configuration is pushed and GitHub processes it.

CI uses read-only repository permissions, immutable action revisions, and disables
persisted checkout credentials, following [GitHub's workflow security guidance](https://docs.github.com/en/actions/reference/security/secure-use).
Preserve those boundaries when updating the workflow; verify action revisions
against their upstream repositories. Dependency consistency checks are not a
vulnerability audit.

## Changes and review

Use focused branches (`codex/` is the maintainer convention). Keep commits
understandable, record the relevant validation, and update the changelog for
meaningful behavior changes. Contributors should push to their own fork and open a
pull request; do not push directly to `main` or change repository settings.

Tests must use synthetic data and check behavior or data preservation. Record the purpose of future fixtures. Include expected findings and expected clean cases when adding validation rules. A taxonomy finding needs evidence of its origin and applicability.

## Release readiness

Follow the [release checklist](docs/RELEASING.md), including retained-archive checks,
synthetic workflow evidence, and exact candidate identity. Use the
[operating guide](docs/OPERATIONS.md) for data handling and the
[security policy](SECURITY.md) for private vulnerability reporting and review scope.
Publishing is a separate user-authorized step.
