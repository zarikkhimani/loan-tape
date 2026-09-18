## Change

Describe the problem and the resulting behavior.

## Validation

- [ ] Local quality checks pass (`check.bat` or `python scripts/check.py`).
- [ ] Relevant regression cases cover the changed behavior.
- [ ] Changes to data meaning, provenance, or outputs are documented.
- [ ] Examples, fixtures, and logs contain no confidential portfolio data.
- [ ] Source preservation, literal identifiers, and incomplete/error outcomes remain explicit.
- [ ] Dependency changes update the manifest and lockfile together; no new source execution or network behavior is implicit.
- [ ] Security boundaries or release limitations affected by this change are documented.

List checks performed and any remaining limitations.

Distinguish local checks from hosted CI, skipped tests from passes, and mocked Excel
behavior from a real Office smoke test. For suspected vulnerabilities, follow
`SECURITY.md` and keep sensitive reproduction details out of public reviews.
