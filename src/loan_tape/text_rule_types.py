"""Versioned literal-rule data and field policy, independent of engines and UI."""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from typing import Any

from loan_tape._date_json import canonical
from loan_tape.pack_format import object_keys, parse_json
from loan_tape.recipe_context import validate_recipe_context

EXACT_OPERATION = "exact-text-rules"
EXACT_VERSION = "1.0.0"
EXACT_ENGINE = "loan-tape-literal-map"
RAPIDFUZZ_VERSION = "3.14.6"
MAX_RULES = 200
MAX_RULE_BYTES = 4 * 1024 * 1024
TOKEN_BYTES = 16 * 1024


def literal(value: str) -> None:
    if not isinstance(value, str) or not value or value.isspace():
        raise ValueError("Rules require nonblank literal source and replacement text.")
    if len(value.encode("utf-8")) > TOKEN_BYTES:
        raise ValueError("Rule text exceeds the 16 KiB UTF-8 token limit.")


@dataclass(frozen=True)
class SpellingEvidence:
    snapshot_id: str
    parent_id: str | None
    column: int
    corpus_id: str
    score: float
    threshold: int
    comparison: str
    unicode_version: str
    engine_version: str = RAPIDFUZZ_VERSION
    scorer: str = "fuzz_cpp.ratio"
    ordering: str = "score-desc,literal-asc"

    def __post_init__(self) -> None:
        identities: tuple[str, ...] = (self.snapshot_id, self.corpus_id)
        if self.parent_id is not None:
            identities += (self.parent_id,)
        for value in identities:
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)
            ):
                raise ValueError("Spelling evidence requires SHA-256 identities.")
        if type(self.column) is not int or self.column < 1:
            raise ValueError("Spelling evidence requires a source column.")
        if type(self.threshold) is not int or not 0 <= self.threshold <= 100:
            raise ValueError("Similarity threshold must be an integer from 0 to 100.")
        if (
            type(self.score) not in {int, float}
            or not math.isfinite(self.score)
            or not self.threshold <= self.score <= 100
        ):
            raise ValueError("Invalid spelling similarity score.")
        if (
            self.comparison not in ("literal", "nfc-casefold")
            or not isinstance(self.unicode_version, str)
            or not self.unicode_version
        ):
            raise ValueError("Unsupported spelling comparison settings.")
        if (
            self.engine_version != RAPIDFUZZ_VERSION
            or self.scorer != "fuzz_cpp.ratio"
            or self.ordering != "score-desc,literal-asc"
        ):
            raise ValueError("Unsupported spelling evidence version or scorer.")


@dataclass(frozen=True)
class ExactRule:
    source: str
    target: str
    suggestion: SpellingEvidence | None = None

    def __post_init__(self) -> None:
        literal(self.source)
        literal(self.target)
        if self.source == self.target:
            raise ValueError("A replacement must differ from its exact source text.")
        if self.suggestion is not None and not isinstance(self.suggestion, SpellingEvidence):
            raise ValueError("Invalid spelling evidence on a rule.")

    @property
    def id(self) -> str:
        return "literal-" + hashlib.sha256(canonical(asdict(self)).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ExactRulesSettings:
    rules: tuple[ExactRule, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.rules, tuple)
            or len(self.rules) > MAX_RULES
            or any(not isinstance(r, ExactRule) for r in self.rules)
        ):
            raise ValueError("Use at most 200 immutable exact replacement rules.")
        keys = [rule.source for rule in self.rules]
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate or conflicting exact source keys are not allowed.")
        object.__setattr__(self, "rules", tuple(sorted(self.rules, key=lambda r: r.source)))
        if len(canonical(asdict(self)).encode("utf-8")) > MAX_RULE_BYTES - 1024:
            raise ValueError("Exact rules exceed the 4 MiB parameter limit.")

    def parameters(self, column: int) -> str:
        if type(column) is not int or column < 1:
            raise ValueError("Choose an explicit source column for exact rules.")
        return canonical({"policy": "literal-text-category-v1", "column": column, **asdict(self)})


def read_rule_parameters(text: str) -> tuple[int, ExactRulesSettings]:
    data = object_keys(
        parse_json(text, "exact rules"), {"policy", "column", "rules"}, {"recipe"}, "exact rules"
    )
    if "recipe" in data:
        validate_recipe_context(data["recipe"])
    if data["policy"] != "literal-text-category-v1" or not isinstance(data["rules"], list):
        raise ValueError("Unsupported exact-rule policy or table.")
    rules = []
    for value in data["rules"]:
        row = object_keys(value, {"source", "target", "suggestion"}, set(), "exact rule")
        evidence = row["suggestion"]
        if evidence is not None:
            evidence = SpellingEvidence(
                **object_keys(
                    evidence, set(SpellingEvidence.__dataclass_fields__), set(), "spelling evidence"
                )
            )
        rules.append(ExactRule(row["source"], row["target"], evidence))
    settings = ExactRulesSettings(tuple(rules))
    settings.parameters(data["column"])
    return data["column"], settings


def free_text(field: dict[str, Any]) -> bool:
    return (
        field["data_type"] == "text"
        and field["code_list"] is None
        and field["canonical_unit"] is None
        and not {"currency", "unit"}.intersection(field["context"])
    )


def exact_field(field: dict[str, Any]) -> bool:
    return free_text(field) or (
        field["data_type"] == "category"
        and field["code_list"] is not None
        and bool(field["allowed_values"])
        and field["canonical_unit"] is None
    )


def validate_rule_field(definition: dict[str, Any], settings: ExactRulesSettings) -> None:
    field = definition["field"]
    if not exact_field(field):
        raise ValueError(
            "Exact rules require mapped free text or a category with frozen allowed values."
        )
    missing = set(definition["rules"]["missing_tokens"])
    allowed = {item["value"] for item in field["allowed_values"]}
    for rule in settings.rules:
        if rule.source in missing or rule.target in missing:
            raise ValueError("Exact rules cannot replace or introduce mapped missing tokens.")
        if field["data_type"] == "category" and rule.target not in allowed:
            raise ValueError("Category replacement is outside the frozen allowed-value list.")
