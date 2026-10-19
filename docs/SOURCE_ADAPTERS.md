# CSV and XML text review

Canonicalization Phase 8 supplies complete saved CSV scopes and explicit CSV/XML
field mappings to the same proposal, cell approval, reconciliation and replay
contracts used by Excel text cleanup. Open **CSV / XML text review...** from the
file preview. Source files and preserved intake copies remain unchanged.

## Workflow

1. Activate a suitable dictionary, such as **Loan text field definitions**.
2. For CSV, choose the encoding, separator and whether the first record contains
   headers, then **Save complete data set**. This reads the whole file. Automatic
   preview guesses are not used. Multiple saved scopes may use different explicit
   conventions; **Reload scopes** restores current saved metadata in the session.
3. For XML, first save a complete record group in the existing preview, then open
   text review. Its original saved group is the analysis boundary. Use a new saved
   group if its name or scope changes after mappings have been created.
4. Select a numbered field and **Define field**. Choose its active dictionary
   meaning, required currency/units/date convention and any explicit missing
   tokens. The editor preserves the dictionary version, fingerprint, full field
   meaning and allowed values. Labels do not infer meanings. Numbers, dates and
   identifiers can be mapped for evidence accounting but are excluded from cleanup.
5. Choose **Repair text**, optionally select NFC, and **Preview whole scope**.
   Alternatively choose **Exact replacement** and enter one literal source/target
   pair. Exact category replacements must belong to the frozen allowed-value list.
6. Review **Proposed changes** and **All outcomes**, select records, and explicitly
   **Include selected changes**. Enter a reviewer and reason before **Apply chosen
   changes**. Subsequent previews use only approved prior values. Changing settings
   clears current approval choices; changing mappings clears the working history.
7. Use **Save JSON audit...** to retain the complete original mapped evidence,
   proposals, approved/rejected decisions, rules, engine settings and revision IDs
   in a new file. Existing files cannot be replaced. Each save rechecks the current
   source, mappings and dictionary and replays the revision before publication.

**Source records** and **All outcomes** are paged in groups of 50. The selected
record's details show its full retained value and native location; the grid's short
display is not the evidence value. **Show source record** navigates to the XML
preview or the complete CSV source-record view. The field selector reaches every
field, including fields outside the original preview. The CSV header record remains
inspectable in Source records and is excluded from proposals only when designated.

## Evidence and missingness

CSV metadata records the explicit encoding, separator, quote character, strict
parser settings, header convention, full dimensions and source hash. Each cell
retains its one-based logical record and field number, physical first/last line,
and the record's actual field count. Quoted multiline values preserve their decoded
line endings. Duplicate and blank header labels retain position and occurrence.
Without headers, every parsed record is data. With headers, the first record must
cover the widest record, including late fields. Short records remain in scope with
absent fields; empty records remain records. Empty text, absence, whitespace,
explicit mapped missing tokens and literal zero remain distinct.

XML retains the saved group path in expanded namespace notation, the complete
namespace URI-to-alias correspondence, field path, group occurrence number and actual node
path when present. An absent field has no invented node path. Absent fields, empty
elements, empty attribute text and explicit `xsi:nil` remain different states.
Late fields are included for all records. Text is decoded XML text; lexical entity
spelling and original encoding remain in the unchanged source file identified by
its hash. XML parser restrictions remain in force: no DTD/entities, network schema
resolution, mixed content or repeated child flattening.

Neither adapter parses numeric/date tokens, trims whitespace, guesses identifiers,
or executes formula-looking text. Original file bytes are the lexical authority;
the audit records decoded values and source locations rather than claiming a
byte-for-byte reconstructed CSV/XML file. Tokens above 16 KiB are represented in
transformation evidence by length and SHA-256 and marked unresolved for cleanup.

## Limits and retention

- At most 100 MiB per source, 2,048 fields and 200,000 cells in the complete
  rectangular population, including CSV headers and absent fields.
- CSV uses the Python reader's 131,072-character field limit. Encoding/quoting
  failures anywhere in the file reject the complete read; no partial scope is saved.
- Existing XML depth, node, path, per-value and per-record limits still apply.
- 128 MiB per serialized evidence/result, 12 reviewed steps; 200 saved scopes and
  8 MiB of saved scope/mapping metadata per source. Limit failures are explicit.
- Scopes and mappings live in `.artifacts/source-adapters/<source-sha256>.json`.
  Writers use a per-source exclusive lock and reject stale edits. Normal failures
  remove staging/locks; an interrupted process may require inspection of a leftover
  lock before a later save. Corrupt settings never silently reset.
- Applied revisions use the existing source-bound `.artifacts/transformations/`
  session storage. Normal Exit removes both after owned workers stop. Explicit
  audit exports outside that managed storage survive. Saved recipes, original
  sources and dictionary packs retain their existing retention rules.

The current adapter dialog provides repair/NFC and one exact replacement per step.
The backend accepts the shared bounded exact-rule table. Spelling search UI,
portable recipe binding, borrower matching, financial date/rate workflows and
workbook exports remain on their existing Excel paths. CSV Inspect/Check/Order
integration and transformed CSV/XML file exports are separate work. A JSON audit
is evidence, not a rewritten source data file.

## Validation

Synthetic regressions execute the real readers and ftfy/exact engines, complete
populations beyond preview limits, encoding choices, multiline/duplicate headers,
namespace and missingness cases, literal identifiers, source preservation, replay,
stale inputs, cancellation, target races, rollback and session cleanup. Native
tests cover mapping, paging, chosen changes, exact follow-on steps, audit saving,
multiple CSV scopes, source navigation and worker shutdown. `check.bat` also runs
`scripts/smoke_source_adapters.py` from an isolated installed wheel. These checks do
not establish real-portfolio coverage, independent accuracy, capacity benchmarks,
Linux behavior or hosted CI results.
