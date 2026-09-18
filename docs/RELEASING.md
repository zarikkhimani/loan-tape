# Release checklist

Use this checklist for a reviewed Loan Tape public alpha. Building locally is
distinct from publishing. The source is MIT-licensed and the intended first public
version is `0.1.0`; this does not imply a PyPI publication, production approval, or
support SLA. Remote pushes, tags, settings, releases, and visibility changes remain
deliberate owner actions.

## Establish the candidate

- Record the exact revision and any uncommitted changes. A working directory with
  no commits or concurrent edits is not an immutable release candidate.
- Review the actual changed files and source-data exclusions. Only deliberately
  authored synthetic fixtures belong in tests; never include client portfolios,
  manifests, local notes, credentials, or generated review results.
- Keep owner-supplied research in ignored `.local/reference-library/`, not in the
  repository. Before the first public push, confirm
  `git log --all -- docs/reference` returns no commits. Removing a file only from the
  latest tree does not remove it from Git history. If any commit contains that path,
  do not push the existing history or change visibility; obtain owner approval to
  create a clean public history from the reviewed tree.
- Set the intended version in `pyproject.toml`, the single source of package version
  metadata. Update `uv.lock` with the pinned local uv tool when metadata changes.
- Confirm `LICENSE` is present, package metadata says MIT, and the public README
  clearly identifies the release as unfinished alpha software.
- Move applicable changelog entries into a dated version section and confirm that
  README, Product, Security, and Operations describe the delivered behavior.
- When updating uv itself, reconcile `.uv-version`, `tool.uv.required-version`, and
  the `uv_build` requirement together. Do not manually repair the lockfile.

## Validate locally

Run from the project folder:

```powershell
.\setup.bat
.\check.bat
```

`check.bat` checks the lockfile, installed dependency consistency, formatting, lint,
types, tests, CLI startup, source/wheel builds, required calendar guidance, and
distribution contents. It installs the wheel and locked runtime dependencies into
an isolated temporary environment and exercises its CLI, intake/preview, packs, and
date foundation. It removes those temporary build environments after verification.

Record passed/failed/skipped checks. Windows native tests require an interactive
desktop; headless Linux UI skips must not be described as UI passes. For changes to
Excel comparison, process ownership, or shutdown, additionally run on Windows with
desktop Excel:

```powershell
.\.venv\Scripts\python.exe scripts/smoke_excel.py
.\.venv\Scripts\python.exe scripts/smoke_shutdown.py
```

Confirm a synthetic end-to-end user workflow for the changed feature, including
unchanged source bytes and visible failure cases. A successful build alone does not
validate a new reader, normalization rule, or financial interpretation.

## Retain and inspect a handoff build

After the checks pass, create retained artifacts using the same pinned tool:

```powershell
$env:UV_CACHE_DIR = Join-Path $PWD '.cache\uv'
$env:UV_PYTHON_DOWNLOADS = 'never'
.\.tools\Scripts\uv.exe build --python .\.venv\Scripts\python.exe --out-dir .\dist
.\.venv\Scripts\python.exe scripts/check.py --distributions .\dist
Get-FileHash .\dist\*.whl, .\dist\*.tar.gz -Algorithm SHA256
```

Use a clean output folder or move earlier builds aside deliberately; the artifact
check rejects multiple wheels/source archives to prevent version ambiguity. It
checks retained archive contents and calendar guidance without repeating source
tests. Do not edit or rebuild the candidate after recording its hashes without
revalidating and recording new identities.

Record the candidate revision, package version, Python/uv/OS versions, lockfile
identity, check results, artifact SHA-256 values, known limitations, and reviewer.
Filename/path exclusions are not a secret-content scanner: inspect the intended
  release contents before public distribution.

## Publish the GitHub repository

Do these steps in order so the repository is reviewable before its visibility
changes:

1. **Freeze and commit the candidate.** Confirm `git status` contains only intended
   release files, review the complete diff, and commit on `main`. Record the commit
   SHA. Do not publish from a dirty working tree. For the first public release, also
   prove the publishable history is free of owner-supplied reference material as
   described above; a clean working tree alone is not sufficient.
2. **Push while the repository is still private.** Push `main`, then verify the
   **Quality** workflow passes for the exact commit on both `windows-latest` and
   `ubuntu-latest`. Local checks do not establish hosted CI success.
3. **Complete the GitHub About panel.** Use this description:

   > Local, source-preserving review of CSV, XML, and Excel loan tapes with explicit lineage and analyst controls.

   Add topics: `loan-tape`, `credit`, `private-credit`, `excel`, `xml`,
   `data-quality`, and `python`. Set the website to the README or leave it blank.
4. **Turn on repository security controls.** In **Settings → Code security and
   analysis**, enable dependency graph, Dependabot alerts/security updates, secret
   scanning where available, and private vulnerability reporting. Confirm the
   Security policy link opens `SECURITY.md` and the issue-template security link
   opens a private advisory form.
5. **Protect `main`.** Require a pull request and the two status checks named
   `Python 3.12 / windows-latest` and `Python 3.12 / ubuntu-latest`. Require branches
   to be up to date before merge. Keep force pushes and branch deletion disabled.
   For a solo-maintainer alpha, one approving review is recommended but may be
   deferred if it would make emergency maintenance impossible; record that choice.
6. **Make the repository public.** In **Settings → General → Danger Zone**, change
   visibility only after the prior checks are complete. Immediately open the public
   README, LICENSE, Security policy, issue forms, Actions page, and file tree in a
   signed-out/private browser view to confirm the intended content is visible and no
   working data is present.
7. **Create the tag and GitHub release.** From the unchanged validated commit:

   ```powershell
   git tag -a v0.1.0 -m "Loan Tape 0.1.0 public alpha"
   git push origin v0.1.0
   ```

   Create a GitHub release from `v0.1.0`, title it **Loan Tape 0.1.0 (alpha)**, and
   use the `0.1.0` changelog section plus the README's not-yet-implemented list as
   release notes. Attach the retained wheel, source archive, and a text file of their
   SHA-256 hashes only if those exact files passed the retained-distribution check.
   Mark it as a pre-release. Do not publish to PyPI as part of this checklist.
8. **Verify after publication.** Re-run the public Actions workflow if GitHub did not
   run it for the tag, inspect dependency-update proposals, test the private security
   reporting route, and confirm branch rules still target the actual check names.
   Record unavailable controls honestly.

A release decision must state outstanding defects and unresolved data or security
limitations. Retain the previous validated artifact for rollback; rollback must
preserve source files and local review metadata and consider schema compatibility.

The discipline follows FinExtract's release checklist while using Loan Tape's
version metadata, lockfile, packaged SIFMA guidance, and isolated wheel checks.
