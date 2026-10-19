# Release checklist

Use this checklist for subsequent Loan Tape public alpha releases. The repository
is already public, and `v0.1.0` is an existing alpha release. The current release
is **0.2.0**. Use a new version and tag for each release; preserve earlier tags,
release notes, and downloadable assets.

Local preparation and validation do not publish a release. Pushes, pull requests,
merges, tags, repository settings, and publication remain owner-authorized actions.
This checklist does not include a PyPI publication, production approval, or support SLA.

## Establish the candidate

- Prepare the changes on a focused branch, such as `codex/release-0.2.0`, for a pull
  request into `main`. Review existing uncommitted work before committing; do not
  discard it or bypass branch protection.
- Set the intended version in `pyproject.toml`, the single source of package version
  metadata. Use the pinned local uv tool to update `uv.lock`; do not edit the lockfile
  manually. Keep the Alpha classifier and confirm that the installed CLI reports
  the same version after setup.
- Move the applicable changelog entries into a dated version section. Before the
  final release commit, set the intended publication date and replace pending-only
  candidate wording in the README, documentation index, and changelog with accurate
  alpha-release wording. Describe implemented behavior and current limits.
- Confirm that `LICENSE` and package metadata still specify MIT. Keep the public
  README clear about Windows, desktop Excel requirements, optional borrower-matching
  setup, output meanings, and retention after Exit.
- Review every intended commit and release file. Keep client portfolios, manifests,
  local notes, credentials, generated review results, models, and labels out of Git
  and release assets. Only deliberately authored synthetic fixtures belong in tests.
- Keep owner-supplied research in ignored `.local/reference-library/`. Review
  `git log --all -- docs/reference .local` as well as the current tree. Removing a
  file from the latest tree does not remove earlier copies. If private material was
  committed, stop publication and obtain an owner-approved remediation plan; do not
  rewrite published history automatically.
- When updating uv, reconcile `.uv-version`, `tool.uv.required-version`, and the
  `uv_build` requirement together. Verify any reported Dependabot tool-version
  mismatch against its updater log, then revalidate the local setup.

## Validate locally

Run from the project folder with an existing Python 3.12 installation:

```powershell
.\setup.bat
.\check.bat
```

The standard check verifies the lockfile, dependency consistency, formatting, lint,
types, tests, CLI startup, source/wheel builds, archive contents, and required
calendar/profile resources. It installs the wheel and locked runtime dependencies
into an isolated environment and exercises the desktop, packs, dates, rates,
transformations, text cleanup, recipes, and complete CSV/XML text-review paths.

For a release that includes desktop Excel exports and borrower matching, prepare
or revalidate the optional local runtime, then use the complete check command in
place of the standard `check.bat` run:

```powershell
.\dev.bat python scripts/setup_entity_matching.py --portable-compiler
.\check.bat --excel-smoke --entity-smoke
```

This requires Windows and desktop Microsoft Excel. The extra checks execute actual
installed-wheel text/recipe/date exports and Dedupe matching, including output
validation, source preservation, cancellation, timeout, and owned-process cleanup.
The portable compiler and optional environment remain project-local. Preserve their
runtime report and provenance locally; do not attach `.tools/`, model binaries,
training labels, or logs containing source data. See [borrower runtime setup](ENTITY_MATCHING.md#optional-runtime-setup)
and [reviewed text export](TEXT_EXPORT.md).

Record passes, failures, and skips separately. Native desktop passes require an
interactive Windows session. Headless Linux UI skips do not establish desktop
coverage, and ordinary hosted runners do not validate installed desktop Excel.
Synthetic matching checks do not establish independent matching accuracy.

For changes to Excel preview comparison or its shutdown behavior, also run:

```powershell
.\dev.bat python scripts/smoke_excel.py
.\dev.bat python scripts/smoke_shutdown.py
```

Confirm a synthetic user workflow for each changed feature, including unchanged
source bytes and visible failure cases. Test the intended source ZIP in a fresh
project folder using the documented Windows setup and launch commands. The GitHub
source ZIP includes desktop launch scripts; the wheel and source distribution are
Python package downloads. A successful build alone does not establish reader or
financial-interpretation correctness.

## Review on GitHub and identify the final commit

1. Commit the reviewed candidate on its release branch and record its SHA. Push
   that branch and open a pull request into `main` when authorized. Describe the
   delivered behavior, local validation, and remaining limitations.
2. Require the **Quality** workflow to pass both named checks for the reviewed PR:
   `Python 3.12 / windows-latest` and `Python 3.12 / ubuntu-latest`. Resolve failures
   and satisfy the repository's review requirements before merging.
3. After the authorized merge, record the resulting `main` commit SHA. Verify both
   Quality checks for that exact SHA; an earlier release's pass or a different PR
   commit is not evidence for the merged revision.
4. Use a clean checkout of that recorded revision for final local validation and
   retained builds. Confirm `git status --short` is empty, `git rev-parse HEAD`
   matches the recorded SHA, and `.\run.bat --version` reports the intended version.
   Any subsequent source or documentation edit creates a new candidate requiring
   the applicable checks and new artifact identities.

Local checks do not establish hosted success. Record a Dependabot updater result
separately from the Quality workflow, including confirmation that any tooling
version fix succeeds after it reaches GitHub.

## Confirm repository controls

Review existing settings rather than repeating first-publication setup:

- Keep the About description, topics, README link, license, issue forms, and pull
  request template accurate for the delivered application.
- Confirm `main` requires pull requests and the two Quality checks above. Keep
  branches up to date before merge and preserve restrictions on force pushes and
  branch deletion. Record the chosen review requirement for the solo-maintainer
  alpha; do not bypass protection to release.
- Confirm dependency alerts/security updates, secret scanning where available,
  and private vulnerability reporting. Open the Security policy and issue form's
  private-reporting link. A local policy file does not prove a remote setting is
  enabled; record unavailable controls or permission-limited verification.
- Check the public README, LICENSE, documentation, issue forms, Actions page, and
  file tree in a signed-out browser view. Visibility changes are not part of a
  routine release from this already public repository.

## Retain and inspect the release build

Build only from the clean, validated final revision. Use a new version-specific
output directory; preserve previous builds. For a 0.2.0 release build:

```powershell
$releaseDirectory = '.\dist\0.2.0'
if (Test-Path -LiteralPath $releaseDirectory) {
    throw 'Choose an unused release output directory; preserve existing builds.'
}
.\dev.bat .\.tools\Scripts\uv.exe build --python .\.venv\Scripts\python.exe --out-dir $releaseDirectory
if ($LASTEXITCODE -ne 0) { throw 'Release build failed.' }
.\check.bat --distributions $releaseDirectory
if ($LASTEXITCODE -ne 0) { throw 'Release archive validation failed.' }
$releaseArtifacts = Get-ChildItem -LiteralPath $releaseDirectory -File |
    Where-Object { $_.Name -like '*.whl' -or $_.Name -like '*.tar.gz' }
$releaseArtifacts | ForEach-Object {
    $releaseHash = Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
    '{0}  {1}' -f $releaseHash.Hash.ToLowerInvariant(), $_.Name
} | Set-Content -LiteralPath (Join-Path $releaseDirectory 'SHA256SUMS.txt') -Encoding ascii
```

The retained-distribution check requires exactly one wheel and one source archive.
It validates actual archive paths, license/guides, and calendar/profile resources
without repeating source tests. Filename exclusions do not scan secret contents;
inspect the intended release contents before public distribution.

Verify package filenames and metadata match `0.2.0`. Install the exact retained
wheel into an isolated local environment and check its version and relevant user
workflows. Do not edit or rebuild after recording hashes without revalidating and
recording new identities.

Keep a local release record containing the final commit SHA, package version,
Python/uv/OS versions, lockfile identity, local and hosted results, artifact names
and SHA-256 values, limitations, and reviewer. The public `SHA256SUMS.txt` contains
hashes and filenames only, without workstation paths or private logs.

## Create the new tag and release

Proceed only after publication is authorized, the final commit and its checks are
confirmed, and the exact retained downloads have passed validation.

1. Confirm that the new tag does not already exist locally or remotely. Preserve
   `v0.1.0` and every earlier release. If `v0.2.0` already exists, stop and inspect
   its identity; do not force-update a tag or replace released downloads.
2. From the clean checkout of the recorded, validated `main` commit, create and
   push only the new tag. Confirm that `HEAD` is the recorded release SHA first:

   ```powershell
   $releaseCommit = git rev-parse HEAD
   git tag -a v0.2.0 $releaseCommit -m "Loan Tape 0.2.0 alpha"
   if ($LASTEXITCODE -ne 0) { throw 'Tag creation failed.' }
   git push origin refs/tags/v0.2.0
   if ($LASTEXITCODE -ne 0) { throw 'Tag push failed.' }
   ```

3. In GitHub **Releases**, choose **Draft a new release** and select the existing
   `v0.2.0` tag. Confirm that the tag resolves to the recorded SHA. Use the title
   **Loan Tape 0.2.0 (alpha)** and mark **This is a pre-release**.
4. Write notes from the 0.2.0 changelog: new text/recipe/export workflows, optional
   borrower review, CSV/XML support, fixes, requirements, retention, and known
   limits. State actual local and hosted results. Link to documentation at this
   tag so the release instructions remain stable as `main` changes.
5. Attach only the exact validated wheel, source archive, and `SHA256SUMS.txt`.
   Explain that **Source code (zip)** is the desktop starting point with Python
   3.12. Keep user portfolios, optional runtimes, compiler archives, models, labels,
   and local validation logs out of release assets.
6. Save and review the draft, confirm the pre-release label and downloads, then
   publish under the owner's authorization. Preparing a draft does not establish
   that publication occurred. Do not publish to PyPI as part of this process.

GitHub documents [drafts, assets, and pre-release publication](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)
and [branch protection and required checks](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).

## Verify after publication

- Confirm the public release, tag SHA, version, notes, and pre-release label. Download
  the published packages and compare their actual bytes with `SHA256SUMS.txt`.
- Test the public source ZIP's setup and launch path in a fresh local folder. Confirm
  that release links open the documentation belonging to the released tag.
- Verify Quality results for the release commit and tag event, inspect dependency
  updater results, and recheck the private security reporting route. Report skipped
  or unavailable checks honestly; publication itself does not establish success.
- Preserve earlier validated releases and their hashes. Record outstanding defects
  and data/security limitations. Any rollback must preserve original source files
  and local review metadata and account for schema compatibility.
