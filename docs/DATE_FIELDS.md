# Date field definitions

Version 1.0.0. These are project-authored definitions for the inactive `loan.dates`
dictionary pack. They establish a vocabulary, not proof that a source field has
that meaning. They are not issued by SIFMA or another market association and are not loan compliance rules.

| Field ID | Meaning to confirm from the source | Required context |
| --- | --- | --- |
| `closing_date` | Original closing event for the mapped loan or facility | Event definition and loan/facility scope. Signing, funding, amendment closing and trade settlement remain distinct. |
| `original_maturity_date` | Contractual final maturity at original establishment | Original agreement and loan/facility scope, before later maturity changes. |
| `current_maturity_date` | Contractual final maturity in effect as represented at the reporting date | Reporting date, effective agreement/amendments, and loan/facility scope. |
| `reporting_date` | Source-stated date to which the report or portfolio information relates | Report scope and as-of basis; not the session date or file timestamp. |

Use fully qualified IDs such as `loan.dates:current_maturity_date`. Labels and
aliases are searchable suggestions; activation does not map columns or run checks.
A generic maturity header alone cannot establish original versus current maturity.
Conditional/springing maturities and reinvestment assumptions require additional
definitions later. Required/blank permissions remain unspecified, not mandatory.

The source representation is a separate concern. [Date parsing](DATES.md) describes
explicit format, century, missing-token and timestamp settings. Parsing cannot
prove contractual validity. Calendar screening follows the packaged
[SIFMA guidance](../src/loan_tape/guidance/SIFMA_CALENDAR.md), preserving published
coverage and agreement applicability rather than imposing a universal closing-day rule.

The pack lives under `packs/loan-dates/`, follows the existing four-file format,
and starts inactive. It is available through the existing pack catalog commands.
As with other starter packs, installed applications receive it via an external
packs directory; the wheel does not automatically install or activate starter packs.
