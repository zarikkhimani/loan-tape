"""Exercise the rate foundation from an isolated installed wheel."""

from decimal import Decimal
from pathlib import Path

from loan_tape.pack_format import load_pack
from loan_tape.rate_parser import (
    BenchmarkAlias,
    RateEvidence,
    RateProfile,
    RateSource,
    parse_rate,
)


def main() -> None:
    pack = load_pack(Path(__file__).resolve().parents[1] / "packs" / "loan-rates")
    assert pack.id == "loan.rates"
    assert next(field for field in pack.fields if field.id == "spread_bps").unit == ("basis points")
    source = RateSource("d" * 64, 2, 4, "Rates")
    profile = RateProfile(
        id="installed-spreads",
        benchmark_aliases=(BenchmarkAlias("SOFR", "usd.sofr"),),
    )
    profile = RateProfile.from_json(profile.to_json())
    result = parse_rate(RateEvidence(source, "text", "SOFR + 6.25%"), profile)
    assert result.status == "normalized"
    assert result.normalized_value == Decimal("625.00")
    assert result.normalized_resolution == Decimal("1.00")
    assert result.reference_rate == "usd.sofr"
    ambiguous = parse_rate(RateEvidence(source, "text", "0.0625"), profile)
    assert ambiguous.status == "ambiguous" and len(ambiguous.candidates) == 3
    print("Installed-wheel rate dictionary and exact scalar parsing passed.")


if __name__ == "__main__":
    main()
