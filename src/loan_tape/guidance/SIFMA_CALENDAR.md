# SIFMA U.S. fixed-income calendar guidance

## Governing source

Loan Tape uses SIFMA as its sole built-in provider for U.S. fixed-income holiday screening. The maintained source pages are SIFMA's [current U.S. holiday recommendations](https://www.sifma.org/resources/general/holiday-schedule) and [U.S. holiday archive](https://www.sifma.org/resources/general/us-holiday-archive). This project-authored guidance and the normalized factual resource ship in the GitHub repository, source distribution, and installed package. SIFMA has not endorsed this project.

SIFMA states that its recommendations apply to trading in U.S. dollar-denominated government securities, mortgage-backed and asset-backed securities, over-the-counter investment-grade and high-yield corporate bonds, municipal bonds, and specified secondary money-market instruments. The recommendations do not create a universal rule for loan closing, funding, payment, or maturity dates. The governing agreement must establish whether this market calendar applies.

## Implemented coverage

The built-in calendar ID is `us.sifma_fixed_income`. The bundled schedule has complete published-year coverage for 2019 through 2027, verified on 2026-09-17. This range covers the supplied 2019–2028 date population through the latest schedule SIFMA has published.

No holiday calendar is projected beyond published SIFMA coverage. For a weekday outside 2019–2027, `business_day` is unknown. Saturday and Sunday remain deterministic for every supported year, including the full 1900–2126 default review horizon. Add a later year only after a credible SIFMA schedule is available and record its source and verification date. Never backcast current holiday rules into an earlier uncovered year.

## Decision rules

1. Preserve every source date and its original representation. Calendar screening never moves, rolls, repairs, or replaces a date.
2. A Saturday or Sunday is a certain non-business day under the weekend calculation, even when holiday coverage for the year is unavailable.
3. A published SIFMA full-close recommendation is non-business for this screening calendar.
4. A published SIFMA early close remains a business day and is retained as a separate event. SIFMA states that early closes do not affect settlement closing time.
5. A weekday in an uncovered year remains unknown. Do not infer that it is a business day and do not generate a holiday from a recurring formula.
6. Retain actual and observed dates, full versus early close, publication source, verification date, calendar version, and coverage status separately.
7. SIFMA recommendations are subject to change and each firm decides whether its fixed-income department remains open. Special closures and Good Friday employment-release exceptions require published evidence.
8. A weekend or full-close match is a review flag unless the user confirms the relevant activity and cites an agreement requirement. Only that explicit combination may elevate a certain match to an error.
9. Keep unsupported financial-centre, currency, rate-fixing, payment, settlement, and contractual business-day conventions outside this calendar. Fail clearly rather than substituting SIFMA.

## Published exceptions and observations

The factual resource preserves SIFMA's exact annual recommendations rather than reconstructing them at runtime. Examples include Good Friday as an early-close-only day in 2021, 2023, and 2026; Saturday New Year's Day with no weekday full close for 2022; observed Friday closures for Saturday Juneteenth, Independence Day, or Christmas where SIFMA published them; and no Veterans Day full close when the holiday fell on Saturday in 2023.

These differences are why the engine does not generate a century of holiday dates. Gregorian weekday calculation is reliable; market recommendations and one-off changes require published evidence.

## Distribution and maintenance

`loan_tape/calendar_data/sifma_us_fixed_income.json` contains normalized project-authored facts and source metadata, not copied proprietary forms. `scripts/check.py` verifies byte-for-byte inclusion of this guidance and that resource in both the wheel and source archive. Synthetic tests independently enumerate key published dates, early-close behavior, unknown years, century weekends, source retention, and saved-run replay.

When extending coverage, update the factual resource, its semantic version, verification date, source metadata, tests, user documentation, and changelog together. Review the current SIFMA page for revisions to previously published years. Do not relabel calculated or third-party dates as SIFMA-published.
