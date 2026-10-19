# Draft data contracts

Phase 8 CSV/XML adapters use native source metadata in transformation snapshots:
format, source SHA-256, explicit parser/group options, complete dimensions,
header/field labels and first data record. CSV cells retain record/field plus
physical line spans and actual record width; XML cells retain occurrence, node and
field paths with namespace-to-URI evidence. No synthetic workbook coordinates are
introduced. Fields reuse immutable dictionary/rule snapshots; proposals, approvals,
population reconciliation and revisions reuse the existing transformation contract.
See [SOURCE_ADAPTERS.md](SOURCE_ADAPTERS.md) for missingness and retention details.

These are design constraints, not implemented schemas or a complete error taxonomy. Final field names and serialization formats will be versioned with their implementation.

| Record family | Responsibility |
| --- | --- |
| Source manifest | Identity, hash, format, reporting context, and extraction version |
| Raw evidence | Original tokens and structural evidence with source addresses |
| Field dictionary | Source/target definitions, units, mapping status, and transformation rule |
| Positions | Canonical position fields with explicit missingness and interpretation status |
| Field lineage | Links from each normalized field to all contributing evidence and transformations |
| Exceptions | Rule finding, origin, field/record references, severity, and review status |
| Change log | Original/replacement values, rule, justification, approval state, reviewer, and time |
| Reconciliation | Comparable population, source/output counts and totals, exclusions, unresolved differences |
| Taxonomy coverage | Reviewed outcomes against a frozen taxonomy, including missed issues and false positives |

Use `source_manifest` consistently; the handoff's Excel-specific `sources.csv` is treated as the same conceptual output. Make field lineage common to the CSV and Excel adapters. For CSV, preserve source record and column positions; for Excel, preserve sheet and cell addresses. Lineage starts at the supplied file. Preserve any known upstream conversion metadata separately without inferring or certifying the original document's contents.

## Implemented dictionary pack contract

The independent dictionary pack/catalog format is implemented and versioned separately; see [PACKS.md](PACKS.md). Its expected types and missingness settings are descriptive metadata, not applied analysis rules. Activation profiles select exact pack snapshots and do not establish column mappings, field equivalence, reporting context, or regulatory applicability. The other processing record families remain draft contracts.

## Field semantics

The [canonicalization integration contract](CANONICALIZATION.md#integration-contract-10)
defines reviewed text transformations, exact rules, derived revisions and replay.
Phase 2 implements version 1 snapshots, previews, approvals and immutable derived
revision records, with an Excel adapter and atomic session storage. See the
[implemented schemas and limits](CANONICALIZATION.md#phase-2-implementation).
Phase 3 supplies pinned ftfy proposals and explicit desktop approvals. Its operation
records the selected column, all effective settings and engine/dependency versions;
application regenerates the exact reviewed output before publication. Phase 4 adds
the versioned `exact-text-rules` operation with a complete literal table, selected
column, policy and executor version. A rule chosen from spelling suggestions also
records source/parent/corpus identities, score, threshold, comparison settings,
Unicode version, scorer and RapidFuzz version. Replay verifies every eligible match
against the table. Category replacement is limited to frozen allowed values under
this specific policy; other transformations retain free-text eligibility.

Phase 5 implements recipe format 1: stable ID, semantic version, name, source/template
profile, applicability, relative mapped schema, frozen dictionary meanings and ordered
supported operations. A canonical fingerprint covers the complete data-only document.
Fresh source bindings record snapshot/recipe identities, profile, current reporting
context and explicit reviewer/time. Every recipe operation embeds that binding and
its recipe/step identity; no prior cell approvals are reused. Full-run envelopes
also retain the recipe and binding. Only the complete approved chain is published.
Saved recipes persist independently of temporary source-bound results. See
[RECIPES.md](RECIPES.md).

Phase 6 exports the complete selection with only approved text overlays and optionally
compatible valid date interpretations. Source tokens remain literal text, preserving
exact digits; ISO date text is explicit. Full raw evidence, every step decision and
the replayable histories are retained in workbook sheets. Chunked canonical JSON
preserves values too large for one audit cell. Existing targets, source workbooks and
intake copies cannot be overwritten. Complete recipe histories and matching original
date evidence are required. See [TEXT_EXPORT.md](TEXT_EXPORT.md).

- Identifiers remain text, including leading zeros and long digit strings.
- Missing, blank, invalid, unreadable, and numeric zero remain distinct.
- Preserve raw text before parsing. Any parse failure produces a typed status and a finding.
- Currency and unit definitions are explicit; a currency symbol alone may be ambiguous.
- Keep principal, commitment, cost, amortized cost, and fair value separate.
- Normalize contractual spreads to exact decimal basis points only when source meaning and units are established; use exact decimal rates for confirmed coupons, benchmark observations, floors, caps, and yields.
- Preserve source unit and resolution. Define any quantization, tolerance, and rounding explicitly rather than inheriting binary-float or display-format behavior.
- Require an established date convention before interpreting ambiguous date strings.
- Keep formulas and saved results separate, with cache validity treated as unknown unless established.

## Rules and findings

Rules need a stable ID, version, description, required fields, applicability, check logic, severity, allowed action, and review policy. Distinguish passing, failing, inapplicable, and unevaluable rules. Missing evidence must not silently count as a pass.

Keep error origin separate from operational action. Source-data, interpretation, extraction, normalization, validation, and export failures can have different severities and require different responses. Cross-field checks apply only when field definitions and populations are comparable.

## Evaluation

Entity relationships carry their source population hash, exact selected borrower
features, raw mapped evidence, optional reviewed text parent, exclusions, all labels,
blocked candidate pairs, grouping threshold, model/dependency provenance and explicit
group decisions. Borrower identifiers compare as literal text only. Training labels
and candidate approval are separate review stages; contradictory distinct-borrower
labels prevent group approval. Unclustered rows are unclassified. Accepted
same-borrower relationships never merge, delete or rewrite loan rows. Source, mapping
or saved-scope drift blocks publication. See [ENTITY_MATCHING.md](ENTITY_MATCHING.md).

Review ground truth independently of rule output. Keep development and holdout sets separate, including source-layout diversity. Sample passing records as well as findings. Record anticipated/detected, anticipated/missed, new, false-positive, and untestable outcomes against an immutable taxonomy version. Synthetic test success is not measured real-corpus coverage.
