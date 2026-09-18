# Rate fields and parsing

## Phase 1 boundary

Phase 1 provides the inactive `loan.rates` dictionary pack and a pure scalar rate
parser. It establishes field meanings, exact units, preserved source evidence and
reviewable outcomes before complete-pool analysis is added.

It does not map columns, read complete CSV/XML/Excel data sets, calculate yield or
coupon, retrieve market rates, interpret agreements, apply cross-field rules, change
source values, drive the desktop UI or export results. Prime is not assumed to be an
agreement-defined Base Rate or ABR, and a generic SOFR label does not establish method
or tenor.

## Canonical conventions

Rate meaning remains separate from representation.

| Meaning | Canonical unit | Example |
| --- | --- | --- |
| Contractual spread or margin | Exact decimal basis points | Confirmed spread `6.25%` becomes `625.00` bps |
| Coupon, reference-rate value, floor, cap or yield | Exact decimal rate | `6.25%` becomes `0.0625` |

The parser uses `Decimal`, never binary floating point, and does not quantize or round.
It retains source precision as a resolution for later comparison. Thus `625 bps` and
`6.25%` both have 1 bp spread resolution, while `6.250%` has 0.1 bp resolution. That
evidence does not authorize a correction or establish a universal tolerance.

The dictionary deliberately separates:

- rate type, reference-rate identity, method and tenor;
- contractual spread from discount margin or another yield measure;
- supplied benchmark value from benchmark identity;
- stated, cash, PIK and total coupon;
- reference-rate floors/caps from all-in coupon floors/caps;
- yield value from yield measure and valuation context;
- rate observation/as-of date from contractual effective date.

Required and blank settings remain unspecified because applicability depends on the
source, portfolio and agreement. Pack aliases are search suggestions, never confirmed
column mappings.

## Evidence and profiles

`RateSource` binds evidence to a SHA-256 source identity and positive original row and
column positions, with an optional worksheet name or XML-style source path.

`RateEvidence` preserves the raw value, storage token and type, displayed text, number
format, presence, formula metadata and an optional validated numeric storage-unit hint.
The parser never evaluates formulas or treats their cached values as rates. Stored
errors, dates, booleans and unsupported types remain distinct outcomes.

A future Excel evidence reader may establish that numeric `0.065` is a decimal rate
because a validated percentage format displays `6.50%`. It must retain both forms and
supply that unit hint explicitly; the scalar parser does not interpret arbitrary Excel
format strings.

`RateProfile` is immutable, JSON-serializable and content-fingerprinted. It records the
expected measure, explicit units for unitless text or numeric storage, exact missing
tokens, whitespace/grouping policy, composite-expression policy, and source-specific
benchmark aliases. There is no automatic or locale-dependent unit mode.

Benchmark aliases are explicit profile decisions. A profile may bind `S` and `SOFR`
to `usd.sofr`; an unmapped `ABR` remains reviewable rather than becoming Prime or
another benchmark automatically.

## Scalar syntax and ambiguity

The parser accepts conservative ASCII decimal forms:

- `625 bp`, `625 bps`, `625 basis points`;
- `6.25%`, `6.25 pct`, `6.25 percent`;
- `0.0625 decimal`, `0.0625 decimal rate`;
- `SOFR+625`, `SOFR + 6.25%`, or `Prime - 50 bps` when composite text is enabled.

Strict comma grouping requires an explicit profile policy. Scientific notation, locale
decimal commas, trailing decimal points, non-ASCII digits and unknown unit words are
not guessed.

Without an applicable unit policy, unitless spread text `0.0625` exposes all three
candidates instead of choosing one:

| Possible source unit | Candidate spread |
| --- | ---: |
| Basis points | 0.0625 bps |
| Percent | 6.25 bps |
| Decimal rate | 625 bps |

Plausibility and portfolio distributions belong to a later analysis phase and cannot
silently promote one candidate.

## Outcomes

Every result retains the evidence, profile and parser version.

| Status | Meaning |
| --- | --- |
| `valid` | Explicit representation already uses the canonical unit |
| `normalized` | Deterministic unit conversion, profile or composite decomposition produced the value |
| `ambiguous` | More than one unit is possible or a benchmark token is unmapped |
| `invalid` | Representation does not match the enabled syntax or policy |
| `missing` | Absent, blank, empty text, whitespace or exact declared missing token |
| `unsupported` | Formula, source type or disabled representation needs another workflow |
| `source_error` | Source contains an explicit stored error |

Accepted results contain one `RateCandidate`; ambiguous results contain every
applicable candidate and no accepted value. Each candidate retains source and canonical
values/units, both resolutions, and any benchmark token and stable identity.

## Python API

```python
from loan_tape.rate_parser import (
    BenchmarkAlias,
    RateEvidence,
    RateProfile,
    RateSource,
    parse_rate,
)

source = RateSource("a" * 64, row=2, column=7, sheet="Loans")
evidence = RateEvidence(source, "text", "SOFR + 6.25%")
profile = RateProfile(
    measure="spread",
    benchmark_aliases=(BenchmarkAlias("SOFR", "usd.sofr"),),
)
result = parse_rate(evidence, profile)

assert result.status == "normalized"
assert str(result.normalized_value) == "625.00"
assert result.normalized_unit == "basis_points"
assert result.reference_rate == "usd.sofr"
```

Profiles round-trip through `to_json()` and `RateProfile.from_json()`. Any policy or
alias change changes the profile fingerprint.

Synthetic tests cover unit equivalence, ambiguity, benchmark expressions, numeric
format evidence, exact precision, grouping, missing states, formulas, malformed input,
immutable contracts and inactive pack behavior. They establish the Phase 1 contract,
not correctness or coverage for a real portfolio.
