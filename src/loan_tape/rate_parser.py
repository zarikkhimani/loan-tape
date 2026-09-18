"""Exact rate interpretation, independent of loan rules, market data, Excel and UI."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Literal

from loan_tape.pack_format import ID_PATTERN, VERSION_PATTERN, object_keys, parse_json

PARSER_VERSION = "1.0.0"
MAX_RATE_TEXT = 256

RateUnit = Literal["basis_points", "percent", "decimal_rate"]
CanonicalRateUnit = Literal["basis_points", "decimal_rate"]
RateMeasure = Literal[
    "spread",
    "coupon",
    "floor",
    "cap",
    "yield",
    "reference_rate",
]
RateKind = Literal["blank", "text", "number", "formula", "error", "boolean", "date", "unsupported"]
RateStatus = Literal[
    "valid", "normalized", "ambiguous", "invalid", "missing", "unsupported", "source_error"
]

RATE_UNITS: tuple[RateUnit, ...] = ("basis_points", "percent", "decimal_rate")
RATE_MEASURES = frozenset({"spread", "coupon", "floor", "cap", "yield", "reference_rate"})
RATE_KINDS = frozenset(
    {"blank", "text", "number", "formula", "error", "boolean", "date", "unsupported"}
)

_NUMBER_BODY = r"(?:[0-9][0-9,]*(?:\.[0-9]+)?|\.[0-9]+)"
_UNIT_BODY = (
    r"(?:%|bp|bps|basis\s+points?|pct|percent(?:age)?(?:\s+points?)?|"
    r"decimal(?:\s+rate)?)"
)
_SIMPLE_AMOUNT = re.compile(
    rf"(?P<number>[+-]?{_NUMBER_BODY})(?:\s*(?P<unit>{_UNIT_BODY}))?",
    re.IGNORECASE,
)
_COMPOSITE_AMOUNT = re.compile(
    rf"(?P<benchmark>.+?)\s*(?P<operator>[+-])\s*"
    rf"(?P<number>{_NUMBER_BODY})(?:\s*(?P<unit>{_UNIT_BODY}))?",
    re.IGNORECASE,
)
_UNGROUPED_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)")
_COMMA_GROUPED_NUMBER = re.compile(
    r"[+-]?(?:(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?|\.[0-9]+)"
)
_SCIENTIFIC_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)[Ee][+-]?[0-9]+")


def _alias_key(value: str) -> str:
    return " ".join(value.split()).casefold()


@dataclass(frozen=True)
class BenchmarkAlias:
    """An explicit source token to stable reference-rate identity mapping."""

    alias: str
    reference_rate: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.alias, str)
            or not self.alias
            or self.alias != self.alias.strip()
            or len(self.alias) > 100
        ):
            raise ValueError(
                "Benchmark aliases must be non-empty trimmed text up to 100 characters."
            )
        if (
            not isinstance(self.reference_rate, str)
            or not ID_PATTERN.fullmatch(self.reference_rate)
            or len(self.reference_rate) > 100
        ):
            raise ValueError("Reference rates require stable lowercase IDs.")


@dataclass(frozen=True)
class RateProfile:
    """A serializable rate representation policy; it does not map source columns."""

    id: str = "explicit-spreads"
    version: str = "1.0.0"
    measure: RateMeasure = "spread"
    unitless_text_unit: RateUnit | None = None
    numeric_storage_unit: RateUnit | None = None
    missing_tokens: tuple[str, ...] = ()
    whitespace: Literal["reject", "strip"] = "reject"
    grouping: Literal["reject", "comma"] = "reject"
    allow_composite: bool = True
    benchmark_aliases: tuple[BenchmarkAlias, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not ID_PATTERN.fullmatch(self.id) or len(self.id) > 100:
            raise ValueError("Rate profile requires a stable lowercase ID.")
        if not isinstance(self.version, str) or not VERSION_PATTERN.fullmatch(self.version):
            raise ValueError("Rate profile version must be major.minor.patch.")
        if not isinstance(self.measure, str) or self.measure not in RATE_MEASURES:
            raise ValueError("Unsupported rate measure.")
        for name, value in (
            ("unitless_text_unit", self.unitless_text_unit),
            ("numeric_storage_unit", self.numeric_storage_unit),
        ):
            if value is not None and (not isinstance(value, str) or value not in RATE_UNITS):
                raise ValueError(f"Unsupported {name}.")
        if not isinstance(self.missing_tokens, tuple) or any(
            not isinstance(value, str) or not value for value in self.missing_tokens
        ):
            raise ValueError("missing_tokens must be a tuple of non-empty strings.")
        if len(set(self.missing_tokens)) != len(self.missing_tokens):
            raise ValueError("missing_tokens contains duplicates.")
        if any(value != value.strip() for value in self.missing_tokens):
            raise ValueError("Missing tokens must not contain surrounding whitespace.")
        if not isinstance(self.whitespace, str) or self.whitespace not in {"reject", "strip"}:
            raise ValueError("Unsupported whitespace policy.")
        if not isinstance(self.grouping, str) or self.grouping not in {"reject", "comma"}:
            raise ValueError("Unsupported grouping policy.")
        if type(self.allow_composite) is not bool:
            raise ValueError("allow_composite must be true or false.")
        if not isinstance(self.benchmark_aliases, tuple) or any(
            not isinstance(value, BenchmarkAlias) for value in self.benchmark_aliases
        ):
            raise ValueError(
                "benchmark_aliases must be an immutable tuple of BenchmarkAlias values."
            )
        alias_keys = [_alias_key(value.alias) for value in self.benchmark_aliases]
        if len(set(alias_keys)) != len(alias_keys):
            raise ValueError("benchmark_aliases contains duplicate case-insensitive aliases.")

    @property
    def canonical_unit(self) -> CanonicalRateUnit:
        return "basis_points" if self.measure == "spread" else "decimal_rate"

    def to_json(self) -> str:
        return json.dumps({"format_version": 1, **asdict(self)}, sort_keys=True, ensure_ascii=False)

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_json(cls, text: str) -> RateProfile:
        fields = set(cls.__dataclass_fields__)
        data = object_keys(
            parse_json(text, "rate profile"), fields | {"format_version"}, set(), "rate profile"
        )
        if type(data["format_version"]) is not int or data["format_version"] != 1:
            raise ValueError("Unsupported rate profile format_version.")
        if not isinstance(data["missing_tokens"], list):
            raise ValueError("missing_tokens must be a JSON array.")
        if not isinstance(data["benchmark_aliases"], list):
            raise ValueError("benchmark_aliases must be a JSON array.")
        aliases = []
        for index, value in enumerate(data["benchmark_aliases"]):
            row = object_keys(
                value,
                {"alias", "reference_rate"},
                set(),
                f"rate profile benchmark_aliases[{index}]",
            )
            aliases.append(BenchmarkAlias(row["alias"], row["reference_rate"]))
        return cls(
            id=data["id"],
            version=data["version"],
            measure=data["measure"],
            unitless_text_unit=data["unitless_text_unit"],
            numeric_storage_unit=data["numeric_storage_unit"],
            missing_tokens=tuple(data["missing_tokens"]),
            whitespace=data["whitespace"],
            grouping=data["grouping"],
            allow_composite=data["allow_composite"],
            benchmark_aliases=tuple(aliases),
        )


@dataclass(frozen=True)
class RateSource:
    """Original record/field coordinates for CSV, XML or workbook evidence."""

    source_sha256: str
    row: int
    column: int
    sheet: str | None = None
    source_path: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.source_sha256
        ):
            raise ValueError("Rate source requires a SHA-256 identity.")
        if any(type(value) is not int or value < 1 for value in (self.row, self.column)):
            raise ValueError("Rate source requires positive original row and column positions.")
        for name, value in (("sheet", self.sheet), ("source_path", self.source_path)):
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"{name} must be non-empty when supplied.")


@dataclass(frozen=True)
class RateEvidence:
    """A source representation retained before any rate conversion."""

    source: RateSource
    kind: RateKind
    raw: str | None
    storage_type: str | None = None
    raw_token: str | None = None
    display_text: str | None = None
    number_format: str | None = None
    numeric_unit_hint: RateUnit | None = None
    present: bool = True
    formula: str | None = None
    formula_attributes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.source, RateSource):
            raise ValueError("Rate evidence requires a validated source location.")
        if not isinstance(self.kind, str) or self.kind not in RATE_KINDS:
            raise ValueError("Unsupported rate evidence kind.")
        for value in (
            self.raw,
            self.storage_type,
            self.raw_token,
            self.display_text,
            self.number_format,
            self.formula,
        ):
            if value is not None and not isinstance(value, str):
                raise ValueError("Retain source representations as text, not converted numbers.")
        if self.numeric_unit_hint is not None and (
            not isinstance(self.numeric_unit_hint, str) or self.numeric_unit_hint not in RATE_UNITS
        ):
            raise ValueError("Unsupported numeric unit hint.")
        if self.numeric_unit_hint is not None and self.kind != "number":
            raise ValueError("Only numeric evidence may carry a numeric unit hint.")
        if type(self.present) is not bool or (not self.present and self.kind != "blank"):
            raise ValueError("Only absent blank cells may have present=False.")
        if self.kind == "blank" and self.raw is not None:
            raise ValueError("Blank evidence cannot contain a value; use text for empty text.")
        if self.raw is None and self.kind not in {"blank", "formula", "unsupported"}:
            raise ValueError("Nonblank evidence requires its source representation.")
        if not isinstance(self.formula_attributes, tuple) or any(
            not isinstance(pair, tuple)
            or len(pair) != 2
            or not all(isinstance(value, str) for value in pair)
            for pair in self.formula_attributes
        ):
            raise ValueError("Formula attributes must be immutable text pairs.")
        if len({key for key, _ in self.formula_attributes}) != len(self.formula_attributes):
            raise ValueError("Duplicate formula attributes.")
        if self.kind != "formula" and (self.formula is not None or self.formula_attributes):
            raise ValueError("Formula metadata requires formula evidence.")


@dataclass(frozen=True)
class RateCandidate:
    """One exact interpretation, including its source-derived resolution."""

    source_value: Decimal
    source_unit: RateUnit
    source_resolution: Decimal
    normalized_value: Decimal
    normalized_unit: CanonicalRateUnit
    normalized_resolution: Decimal
    reference_rate: str | None = None
    reference_rate_token: str | None = None


@dataclass(frozen=True)
class RateResult:
    evidence: RateEvidence
    profile: RateProfile
    status: RateStatus
    code: str
    candidate: RateCandidate | None = None
    candidates: tuple[RateCandidate, ...] = ()
    missing_kind: str | None = None
    notes: tuple[str, ...] = ()
    parser_version: str = PARSER_VERSION

    @property
    def normalized_value(self) -> Decimal | None:
        return None if self.candidate is None else self.candidate.normalized_value

    @property
    def normalized_unit(self) -> CanonicalRateUnit | None:
        return None if self.candidate is None else self.candidate.normalized_unit

    @property
    def normalized_resolution(self) -> Decimal | None:
        return None if self.candidate is None else self.candidate.normalized_resolution

    @property
    def source_unit(self) -> RateUnit | None:
        return None if self.candidate is None else self.candidate.source_unit

    @property
    def reference_rate(self) -> str | None:
        return None if self.candidate is None else self.candidate.reference_rate


@dataclass(frozen=True)
class _ParsedAmount:
    value: Decimal
    resolution: Decimal
    units: tuple[RateUnit, ...]
    inferred_unit: bool
    grouped: bool


def _parse_number(token: str, grouping: str) -> tuple[Decimal | None, Decimal | None, str | None]:
    if "," in token:
        if grouping == "reject":
            return None, None, "grouping_not_enabled"
        if _COMMA_GROUPED_NUMBER.fullmatch(token) is None:
            return None, None, "invalid_grouping"
    elif _UNGROUPED_NUMBER.fullmatch(token) is None:
        return None, None, "invalid_number"
    cleaned = token.replace(",", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None, None, "invalid_number"
    if not value.is_finite():
        return None, None, "invalid_number"
    fraction = cleaned.lstrip("+-").partition(".")[2]
    resolution = Decimal(1).scaleb(-len(fraction))
    return value, resolution, None


def _unit(value: str) -> RateUnit:
    key = " ".join(value.casefold().split())
    if key in {"bp", "bps", "basis point", "basis points"}:
        return "basis_points"
    if key in {
        "%",
        "pct",
        "percent",
        "percentage",
        "percent point",
        "percent points",
        "percentage point",
        "percentage points",
    }:
        return "percent"
    return "decimal_rate"


def _amount(
    token: str,
    unit_token: str | None,
    default_unit: RateUnit | None,
    grouping: str,
) -> tuple[_ParsedAmount | None, str | None]:
    value, resolution, error = _parse_number(token, grouping)
    if error is not None:
        return None, error
    assert value is not None and resolution is not None
    units: tuple[RateUnit, ...]
    if unit_token is not None:
        units = (_unit(unit_token),)
        inferred = False
    elif default_unit is not None:
        units = (default_unit,)
        inferred = True
    else:
        units = RATE_UNITS
        inferred = True
    return _ParsedAmount(value, resolution, units, inferred, "," in token), None


def _candidate(
    amount: _ParsedAmount,
    unit: RateUnit,
    profile: RateProfile,
    *,
    reference_rate: str | None = None,
    reference_rate_token: str | None = None,
) -> RateCandidate:
    if profile.measure == "spread":
        factors: dict[RateUnit, Decimal] = {
            "basis_points": Decimal(1),
            "percent": Decimal(100),
            "decimal_rate": Decimal(10000),
        }
        canonical: CanonicalRateUnit = "basis_points"
    else:
        factors = {
            "basis_points": Decimal("0.0001"),
            "percent": Decimal("0.01"),
            "decimal_rate": Decimal(1),
        }
        canonical = "decimal_rate"
    with localcontext() as context:
        context.prec = max(512, len(amount.value.as_tuple().digits) + 32)
        normalized = amount.value * factors[unit]
        normalized_resolution = amount.resolution * factors[unit]
    return RateCandidate(
        amount.value,
        unit,
        amount.resolution,
        normalized,
        canonical,
        normalized_resolution,
        reference_rate,
        reference_rate_token,
    )


def parse_rate(evidence: RateEvidence, profile: RateProfile) -> RateResult:
    """Interpret explicit rate syntax without guessing field meaning, units or benchmarks."""
    notes: list[str] = []
    representation_changed = False

    def result(
        status: RateStatus,
        code: str,
        *,
        candidate: RateCandidate | None = None,
        candidates: tuple[RateCandidate, ...] = (),
        missing_kind: str | None = None,
    ) -> RateResult:
        return RateResult(
            evidence=evidence,
            profile=profile,
            status=status,
            code=code,
            candidate=candidate,
            candidates=candidates,
            missing_kind=missing_kind,
            notes=tuple(notes),
        )

    def finish(
        amount: _ParsedAmount,
        *,
        reference_rate: str | None = None,
        reference_rate_token: str | None = None,
        composite: bool = False,
        ambiguity_code: str = "unit_required",
    ) -> RateResult:
        if amount.grouped:
            notes.append("Comma grouping removed for interpretation; original retained.")
        candidates = tuple(
            _candidate(
                amount,
                unit,
                profile,
                reference_rate=reference_rate,
                reference_rate_token=reference_rate_token,
            )
            for unit in amount.units
        )
        if len(candidates) != 1 or (composite and reference_rate is None):
            if composite and reference_rate is None and len(candidates) != 1:
                ambiguity_code = "reference_rate_and_unit_required"
            elif composite and reference_rate is None:
                ambiguity_code = "unmapped_reference_rate"
            return result("ambiguous", ambiguity_code, candidates=candidates)
        candidate = candidates[0]
        changed = (
            representation_changed
            or amount.grouped
            or amount.inferred_unit
            or composite
            or candidate.source_unit != profile.canonical_unit
        )
        status: RateStatus = "normalized" if changed else "valid"
        if composite:
            code = "parsed_spread_expression"
        else:
            code = "normalized_rate" if status == "normalized" else "canonical_rate"
        return result(status, code, candidate=candidate)

    if evidence.kind == "formula":
        return result("unsupported", "formula_not_evaluated")
    if evidence.kind == "error":
        return result("source_error", "stored_source_error")
    if evidence.kind in {"boolean", "date", "unsupported"}:
        return result("unsupported", "unsupported_source_type")
    if evidence.kind == "blank":
        return result(
            "missing", "missing_value", missing_kind="blank" if evidence.present else "absent"
        )
    assert evidence.raw is not None
    raw = evidence.raw
    if evidence.kind == "text":
        if raw == "":
            return result("missing", "missing_value", missing_kind="empty_text")
        if raw.isspace():
            return result("missing", "missing_value", missing_kind="whitespace")
        if raw != raw.strip():
            if profile.whitespace == "reject":
                return result("invalid", "surrounding_whitespace")
            raw = raw.strip()
            representation_changed = True
            notes.append("Surrounding whitespace stripped for interpretation; original retained.")
        if raw in profile.missing_tokens:
            return result("missing", "declared_missing_token", missing_kind="token")
    if len(raw) > MAX_RATE_TEXT:
        return result("unsupported", "unsupported_text_representation")

    if evidence.kind == "number":
        value, resolution, error = _parse_number(raw, profile.grouping)
        if error is not None:
            return result("invalid", error)
        assert value is not None and resolution is not None
        units = []
        for unit in (evidence.numeric_unit_hint, profile.numeric_storage_unit):
            if unit is not None and unit not in units:
                units.append(unit)
        if len(units) > 1:
            amount = _ParsedAmount(value, resolution, tuple(units), False, "," in raw)
            return finish(amount, ambiguity_code="numeric_unit_conflict")
        if units:
            inferred = evidence.numeric_unit_hint is None
            amount = _ParsedAmount(value, resolution, (units[0],), inferred, "," in raw)
        else:
            amount = _ParsedAmount(value, resolution, RATE_UNITS, True, "," in raw)
        return finish(amount, ambiguity_code="numeric_unit_required")

    if _SCIENTIFIC_NUMBER.fullmatch(raw) is not None:
        return result("invalid", "scientific_notation_not_enabled")

    composite_match = _COMPOSITE_AMOUNT.fullmatch(raw)
    if composite_match is not None:
        if not profile.allow_composite:
            return result("unsupported", "composite_rate_not_enabled")
        if profile.measure != "spread":
            return result("ambiguous", "composite_measure_conflict")
        parsed_amount, error = _amount(
            composite_match.group("number"),
            composite_match.group("unit"),
            profile.unitless_text_unit,
            profile.grouping,
        )
        if error is not None:
            return result("invalid", error)
        assert parsed_amount is not None
        if composite_match.group("operator") == "-":
            parsed_amount = _ParsedAmount(
                -parsed_amount.value,
                parsed_amount.resolution,
                parsed_amount.units,
                parsed_amount.inferred_unit,
                parsed_amount.grouped,
            )
        reference_token = composite_match.group("benchmark").strip()
        alias_map = {
            _alias_key(alias.alias): alias.reference_rate for alias in profile.benchmark_aliases
        }
        reference_rate = alias_map.get(_alias_key(reference_token))
        return finish(
            parsed_amount,
            reference_rate=reference_rate,
            reference_rate_token=reference_token,
            composite=True,
        )

    simple_match = _SIMPLE_AMOUNT.fullmatch(raw)
    if simple_match is None:
        return result("invalid", "format_mismatch")
    parsed_amount, error = _amount(
        simple_match.group("number"),
        simple_match.group("unit"),
        profile.unitless_text_unit,
        profile.grouping,
    )
    if error is not None:
        return result("invalid", error)
    assert parsed_amount is not None
    return finish(parsed_amount)
