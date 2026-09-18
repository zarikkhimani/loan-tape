# Draft data contracts

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

Review ground truth independently of rule output. Keep development and holdout sets separate, including source-layout diversity. Sample passing records as well as findings. Record anticipated/detected, anticipated/missed, new, false-positive, and untestable outcomes against an immutable taxonomy version. Synthetic test success is not measured real-corpus coverage.
