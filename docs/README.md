# Documentation

Start with [Install and run](../README.md#start-here) for your first session.
Loan Tape 0.2.0 is an alpha release candidate awaiting publication; each guide
distinguishes current behavior from planned work.

## Using the app

| I want to… | Read |
| --- | --- |
| Install, launch, and review my first file | [Quick start](../README.md#start-here) |
| Navigate worksheets or XML, select data, and inspect/check columns | [User guide](USER_GUIDE.md) |
| Review dates and create an Excel deliverable | [Date review and export](DATE_ANALYSIS.md#desktop-review-and-excel-export) |
| Review text repairs, spelling suggestions and exact replacements | [Reviewed text cleanup](TEXT_CLEANUP.md) |
| Save and reuse ordered cleanup steps | [Reusable cleanup recipes](RECIPES.md) |
| Export reviewed text/recipe results and compatible dates | [Reviewed text export](TEXT_EXPORT.md) |
| Label and review borrower relationships | [Borrower relationships](ENTITY_MATCHING.md) |
| Understand what is cleared when I exit | [Operating guide](OPERATIONS.md#local-records-and-retention) |
| Define field meanings or edit a dictionary | [Dictionary packs](PACKS.md) |

## Understanding results

| I want to… | Read |
| --- | --- |
| Know what works today and what is planned | [Product scope](PRODUCT.md) and [Roadmap](ROADMAP.md) |
| Understand date meanings and parsing choices | [Date fields](DATE_FIELDS.md) and [Date parsing](DATES.md) |
| Understand holiday coverage and calendar flags | [SIFMA calendar guidance](../src/loan_tape/guidance/SIFMA_CALENDAR.md) |
| Understand the Python rate parser and its limits | [Rate fields and parsing](RATES.md) |
| Understand source preservation and data meaning | [Data contracts](DATA_CONTRACTS.md) |
| Review security boundaries or report a vulnerability | [Security policy](../SECURITY.md) |

## Developing the project

- [Contributing](../CONTRIBUTING.md): environment setup, commands, and change review.
- [Architecture](ARCHITECTURE.md): components, data flow, and implementation boundaries.
- [Canonicalization integration](CANONICALIZATION.md): component selection,
  compatibility probes, transformation APIs, text cleanup and exact rules, evidence and later phases.
- [Release checklist](RELEASING.md): validation, package checks, and publication steps.
- [Changelog](../CHANGELOG.md): changes by version.
- [Working instructions](../AGENTS.md): repository conventions and data invariants.

See [License](../LICENSE) for reuse terms.

- [CSV/XML text review](SOURCE_ADAPTERS.md): complete scopes, explicit mappings, native evidence and reviewed changes.
