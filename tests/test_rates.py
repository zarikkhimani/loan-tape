"""Exact rate interpretation and policy boundaries using synthetic source evidence."""

import json
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from pathlib import Path

import pytest

from loan_tape.pack_format import load_pack
from loan_tape.packs import PackStore
from loan_tape.rate_parser import (
    BenchmarkAlias,
    RateEvidence,
    RateProfile,
    RateSource,
    parse_rate,
)

SOURCE = RateSource("b" * 64, 11, 5, "Rates")


def interpret(raw, profile=None, kind="text", **evidence):
    return parse_rate(RateEvidence(SOURCE, kind, raw, **evidence), profile or RateProfile())


@pytest.mark.parametrize(
    "raw,status,value,resolution,source_unit",
    [
        ("625 bps", "valid", "625", "1", "basis_points"),
        ("6.25%", "normalized", "625.00", "1.00", "percent"),
        ("0.0625 decimal rate", "normalized", "625.0000", "1.0000", "decimal_rate"),
    ],
)
def test_explicit_spread_units_normalize_to_exact_basis_points(
    raw, status, value, resolution, source_unit
):
    result = interpret(raw)
    assert result.status == status
    assert result.normalized_value == Decimal(value)
    assert result.normalized_unit == "basis_points"
    assert result.normalized_resolution == Decimal(resolution)
    assert result.source_unit == source_unit
    assert result.evidence.raw == raw and result.evidence.source == SOURCE


@pytest.mark.parametrize(
    "raw,status,value,resolution,source_unit",
    [
        ("625 bps", "normalized", "0.0625", "0.0001", "basis_points"),
        ("6.25%", "normalized", "0.0625", "0.0001", "percent"),
        ("0.0625 decimal", "valid", "0.0625", "0.0001", "decimal_rate"),
    ],
)
def test_absolute_rates_use_decimal_rate_canonical_unit(
    raw, status, value, resolution, source_unit
):
    result = interpret(raw, RateProfile(measure="coupon"))
    assert result.status == status
    assert result.normalized_value == Decimal(value)
    assert result.normalized_unit == "decimal_rate"
    assert result.normalized_resolution == Decimal(resolution)
    assert result.source_unit == source_unit


def test_unitless_values_return_all_exact_candidates_instead_of_guessing():
    result = interpret("0.0625")
    assert result.status == "ambiguous" and result.code == "unit_required"
    assert result.normalized_value is None
    assert [candidate.source_unit for candidate in result.candidates] == [
        "basis_points",
        "percent",
        "decimal_rate",
    ]
    assert [candidate.normalized_value for candidate in result.candidates] == [
        Decimal("0.0625"),
        Decimal("6.2500"),
        Decimal("625.0000"),
    ]


def test_explicit_profile_interprets_unitless_text_without_hiding_the_transform():
    profile = RateProfile(unitless_text_unit="percent")
    result = interpret("6.25", profile)
    assert result.status == "normalized" and result.code == "normalized_rate"
    assert result.normalized_value == Decimal("625.00")
    assert result.candidate is not None and result.candidate.source_unit == "percent"


def test_numeric_storage_hint_preserves_excel_percent_evidence():
    evidence = RateEvidence(
        SOURCE,
        "number",
        "0.065",
        raw_token="0.065",
        display_text="6.50%",
        number_format="0.00%",
        numeric_unit_hint="decimal_rate",
    )
    result = parse_rate(evidence, RateProfile(measure="coupon"))
    assert result.status == "valid"
    assert result.normalized_value == Decimal("0.065")
    assert result.normalized_resolution == Decimal("0.001")
    assert result.evidence.display_text == "6.50%"
    assert result.evidence.number_format == "0.00%"


def test_numeric_storage_hint_and_profile_conflict_is_reviewable():
    evidence = RateEvidence(SOURCE, "number", "0.065", numeric_unit_hint="decimal_rate")
    profile = RateProfile(measure="coupon", numeric_storage_unit="basis_points")
    result = parse_rate(evidence, profile)
    assert result.status == "ambiguous" and result.code == "numeric_unit_conflict"
    assert [candidate.source_unit for candidate in result.candidates] == [
        "decimal_rate",
        "basis_points",
    ]
    assert result.normalized_value is None


def test_numeric_value_needs_storage_unit_when_no_format_or_profile_establishes_one():
    result = interpret("0.065", RateProfile(measure="coupon"), "number")
    assert result.status == "ambiguous" and result.code == "numeric_unit_required"
    assert len(result.candidates) == 3


def test_composite_spreads_require_explicit_benchmark_aliases():
    profile = RateProfile(
        unitless_text_unit="basis_points",
        benchmark_aliases=(
            BenchmarkAlias("S", "usd.sofr"),
            BenchmarkAlias("SOFR", "usd.sofr"),
            BenchmarkAlias("Prime", "usd.prime"),
        ),
    )
    sofr = interpret("SOFR + 6.25%", profile)
    assert sofr.status == "normalized" and sofr.code == "parsed_spread_expression"
    assert sofr.reference_rate == "usd.sofr"
    assert sofr.normalized_value == Decimal("625.00")
    assert sofr.candidate is not None and sofr.candidate.reference_rate_token == "SOFR"
    prime = interpret("Prime - 50 bps", profile)
    assert prime.reference_rate == "usd.prime"
    assert prime.normalized_value == Decimal("-50")
    short = interpret("s+325", profile)
    assert short.reference_rate == "usd.sofr" and short.normalized_value == Decimal("325")


def test_unmapped_benchmark_retains_token_and_normalized_candidate_for_review():
    profile = RateProfile(unitless_text_unit="basis_points")
    result = interpret("ABR+100", profile)
    assert result.status == "ambiguous" and result.code == "unmapped_reference_rate"
    assert len(result.candidates) == 1
    assert result.candidates[0].reference_rate is None
    assert result.candidates[0].reference_rate_token == "ABR"
    assert result.candidates[0].normalized_value == Decimal("100")


def test_composite_expression_does_not_silently_become_coupon_or_yield():
    result = interpret(
        "SOFR+350",
        RateProfile(measure="coupon", unitless_text_unit="basis_points"),
    )
    assert result.status == "ambiguous" and result.code == "composite_measure_conflict"
    assert result.candidates == () and result.normalized_value is None
    disabled = interpret(
        "SOFR+350",
        RateProfile(unitless_text_unit="basis_points", allow_composite=False),
    )
    assert disabled.status == "unsupported" and disabled.code == "composite_rate_not_enabled"


def test_source_precision_is_retained_without_rounding():
    result = interpret("6.2575%")
    assert result.normalized_value == Decimal("625.7500")
    assert result.candidate is not None
    assert result.candidate.source_value == Decimal("6.2575")
    assert result.candidate.source_resolution == Decimal("0.0001")
    assert result.normalized_resolution == Decimal("0.0100")
    assert result.evidence.raw == "6.2575%"


def test_grouping_and_whitespace_require_explicit_policies():
    assert interpret("1,250 bps").code == "grouping_not_enabled"
    grouped = interpret("1,250 bps", RateProfile(grouping="comma"))
    assert grouped.status == "normalized" and grouped.normalized_value == Decimal("1250")
    assert "original retained" in grouped.notes[0]
    assert interpret(" 6.25% ").code == "surrounding_whitespace"
    stripped = interpret(" 6.25% ", RateProfile(whitespace="strip"))
    assert stripped.normalized_value == Decimal("625.00") and stripped.notes


def test_missing_zero_and_source_failures_stay_distinct():
    profile = RateProfile(missing_tokens=("N/A",), unitless_text_unit="basis_points")
    rows = [
        interpret(None, profile, "blank", present=False),
        interpret(None, profile, "blank"),
        interpret("", profile),
        interpret(" \t", profile),
        interpret("N/A", profile),
    ]
    assert [result.missing_kind for result in rows] == [
        "absent",
        "blank",
        "empty_text",
        "whitespace",
        "token",
    ]
    assert all(result.status == "missing" for result in rows)
    zero = interpret("0", profile)
    assert zero.status == "normalized" and zero.normalized_value == Decimal("0")
    assert interpret("#VALUE!", profile, "error").status == "source_error"
    assert interpret("TRUE", profile, "boolean").status == "unsupported"
    assert interpret("2026-09-17", profile, "date").status == "unsupported"


def test_formulas_are_never_evaluated_even_with_a_cached_value():
    evidence = RateEvidence(
        SOURCE,
        "formula",
        "0.0625",
        raw_token="0.0625",
        display_text="6.25%",
        number_format="0.00%",
        formula="A1+B1",
    )
    result = parse_rate(evidence, RateProfile(measure="coupon"))
    assert result.status == "unsupported" and result.code == "formula_not_evaluated"
    assert result.normalized_value is None and result.evidence.formula == "A1+B1"


@pytest.mark.parametrize(
    "raw",
    [
        "6.25e-2",
        "6,25%",
        "6.25%%",
        "6.25 percentish",
        "625.",
        "６.２５%",
        "NaN",
        "Infinity",
        "USD SOFR",
    ],
)
def test_unconfigured_or_malformed_representations_are_not_guessed(raw):
    result = interpret(raw)
    assert result.status == "invalid" and result.normalized_value is None


def test_profile_roundtrip_and_fingerprint_bind_every_policy():
    profile = RateProfile(
        id="source-spreads",
        measure="spread",
        unitless_text_unit="basis_points",
        numeric_storage_unit="decimal_rate",
        missing_tokens=("ND",),
        whitespace="strip",
        grouping="comma",
        benchmark_aliases=(BenchmarkAlias("S", "usd.sofr"),),
    )
    reopened = RateProfile.from_json(profile.to_json())
    assert reopened == profile and reopened.fingerprint == profile.fingerprint
    assert replace(profile, numeric_storage_unit="percent").fingerprint != profile.fingerprint


@pytest.mark.parametrize(
    "key,value",
    [
        ("format_version", True),
        ("format_version", 2),
        ("measure", "rate"),
        ("unitless_text_unit", "auto"),
        ("numeric_storage_unit", 1),
        ("missing_tokens", [" N/A "]),
        ("missing_tokens", "N/A"),
        ("whitespace", "guess"),
        ("grouping", "locale"),
        ("allow_composite", 1),
        ("benchmark_aliases", [{"alias": "S", "reference_rate": "UPPER"}]),
        ("version", "latest"),
        ("extra", "unexpected"),
    ],
)
def test_invalid_profile_contract_fails_clearly(key, value):
    document = json.loads(RateProfile().to_json())
    document[key] = value
    with pytest.raises(ValueError):
        RateProfile.from_json(json.dumps(document))


def test_duplicate_profile_json_and_aliases_are_rejected():
    text = RateProfile().to_json()
    with pytest.raises(ValueError, match="duplicate"):
        RateProfile.from_json(
            text.replace('"format_version": 1', '"format_version": 1, "format_version": 1')
        )
    with pytest.raises(ValueError, match="duplicate"):
        RateProfile(
            benchmark_aliases=(
                BenchmarkAlias("SOFR", "usd.sofr"),
                BenchmarkAlias("sofr", "usd.sofr"),
            )
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"raw": Decimal("0.1")},
        {"kind": "blank", "raw": "value"},
        {"present": False},
        {"present": 1},
        {"numeric_unit_hint": "auto"},
        {"kind": "text", "numeric_unit_hint": "percent"},
        {"formula": "A1+B1"},
        {"formula_attributes": [("t", "shared")]},
    ],
)
def test_evidence_rejects_inconsistent_or_mutable_representations(changes):
    with pytest.raises(ValueError):
        RateEvidence(**{"source": SOURCE, "kind": "text", "raw": "6.25%", **changes})


def test_results_and_source_locations_are_immutable():
    xml_source = RateSource("c" * 64, 4, 9, source_path="/loans/loan[4]/spread")
    result = parse_rate(
        RateEvidence(xml_source, "text", "625 bps"),
        RateProfile(),
    )
    assert result.evidence.source.source_path == "/loans/loan[4]/spread"
    with pytest.raises(FrozenInstanceError):
        result.status = "invalid"


def test_rate_dictionary_keeps_meanings_units_and_benchmarks_distinct(tmp_path):
    root = Path(__file__).resolve().parents[1]
    pack = load_pack(root / "packs" / "loan-rates")
    fields = {field.id: field for field in pack.fields}
    assert pack.id == "loan.rates"
    assert fields["spread_bps"].unit == "basis points"
    assert fields["stated_coupon_rate"].unit == "decimal rate"
    assert fields["yield_rate"].context[:2] == ("yield_measure", "rate_as_of_date")
    assert fields["reference_rate_floor"].definition != fields["coupon_rate_floor"].definition
    assert all(field.required is None and field.blank_allowed is None for field in pack.fields)
    rates = next(code_list for code_list in pack.code_lists if code_list.id == "reference_rate")
    codes = {code.value for code in rates.codes}
    assert {"usd.sofr", "usd.prime", "agreement.base_rate", "other"} <= codes
    store = PackStore(root / "packs", tmp_path / "state")
    assert store.catalog().fields == ()
    store.activate("loan.rates")
    assert store.catalog().get_field("loan.rates:spread_bps").field.unit == "basis points"
