"""Complete-column literal replacement and bounded, suggestion-only text similarity."""

from __future__ import annotations

import hashlib
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from importlib.metadata import version
from threading import Event

import rapidfuzz
from rapidfuzz.fuzz_cpp import ratio  # type: ignore[import-not-found]

from loan_tape._date_json import canonical
from loan_tape.text_rule_types import (
    EXACT_ENGINE,
    EXACT_OPERATION,
    EXACT_VERSION,
    RAPIDFUZZ_VERSION,
    ExactRule,
    ExactRulesSettings,
    SpellingEvidence,
    free_text,
    literal,
)
from loan_tape.transformations import (
    MAX_PAGE_SIZE,
    MAX_RESULT_BYTES,
    CellProposal,
    TransformationOperation,
    TransformationPreview,
    TransformationRevision,
    TransformationSnapshot,
    preview_transformation,
)
from loan_tape.workbook_index import check_cancelled

MAX_DISTINCT = 10_000


def rule_operation(column: int, settings: ExactRulesSettings) -> TransformationOperation:
    return TransformationOperation(
        EXACT_OPERATION, EXACT_VERSION, EXACT_ENGINE, EXACT_VERSION, settings.parameters(column)
    )


def preview_exact_rules(
    snapshot: TransformationSnapshot,
    column: int,
    settings: ExactRulesSettings,
    *,
    parent: TransformationRevision | None = None,
    cancelled: Event | None = None,
) -> TransformationPreview:
    baseline = preview_transformation(
        snapshot,
        rule_operation(column, ExactRulesSettings()),
        (),
        parent=parent,
        cancelled=cancelled,
    )
    rules = {rule.source: rule for rule in settings.rules}
    proposals = []
    for item in baseline.to_dict()["decisions"]:
        check_cancelled(cancelled)
        if item["column"] != column or item["outcome"] != "unchanged":
            continue
        rule = rules.get(item["input_text"])
        if rule is not None:
            proposals.append(
                CellProposal(
                    item["row"],
                    column,
                    rule.source,
                    rule.target,
                    rule.id,
                    "Reviewed exact literal replacement.",
                )
            )
    return preview_transformation(
        snapshot,
        rule_operation(column, settings),
        tuple(proposals),
        parent=parent,
        cancelled=cancelled,
    )


@dataclass(frozen=True)
class SpellingSettings:
    threshold: int = 85
    comparison: str = "literal"

    def __post_init__(self) -> None:
        if type(self.threshold) is not int or not 0 <= self.threshold <= 100:
            raise ValueError("Similarity threshold must be an integer from 0 to 100.")
        if self.comparison not in ("literal", "nfc-casefold"):
            raise ValueError("Choose literal or NFC + casefold comparison.")

    def compare_text(self, text: str) -> str:
        return (
            text if self.comparison == "literal" else unicodedata.normalize("NFC", text).casefold()
        )


@dataclass(frozen=True)
class SpellingCandidate:
    text: str
    score: float
    count: int
    first_row: int


@dataclass(frozen=True)
class SpellingSuggestions:
    snapshot_id: str
    parent_id: str | None
    column: int
    corpus_id: str
    query: str
    settings: SpellingSettings
    distinct_count: int
    eligible_count: int
    candidates: tuple[SpellingCandidate, ...]

    def page(self, offset: int = 0, limit: int = MAX_PAGE_SIZE) -> tuple[SpellingCandidate, ...]:
        if (
            type(offset) is not int
            or offset < 0
            or type(limit) is not int
            or not 1 <= limit <= MAX_PAGE_SIZE
        ):
            raise ValueError("Use a nonnegative offset and up to 200 suggestions per page.")
        return self.candidates[offset : offset + limit]

    def rule(self, index: int) -> ExactRule:
        if type(index) is not int or not 0 <= index < len(self.candidates):
            raise ValueError("Select one displayed spelling candidate.")
        candidate = self.candidates[index]
        return ExactRule(
            self.query,
            candidate.text,
            SpellingEvidence(
                self.snapshot_id,
                self.parent_id,
                self.column,
                self.corpus_id,
                candidate.score,
                self.settings.threshold,
                self.settings.comparison,
                unicodedata.unidata_version,
            ),
        )


def suggest_spellings(
    snapshot: TransformationSnapshot,
    column: int,
    query: str,
    settings: SpellingSettings,
    *,
    parent: TransformationRevision | None = None,
    cancelled: Event | None = None,
) -> SpellingSuggestions:
    check_cancelled(cancelled)
    literal(query)
    if version("rapidfuzz") != RAPIDFUZZ_VERSION or rapidfuzz.__version__ != RAPIDFUZZ_VERSION:
        raise ValueError(f"Spelling suggestions require reviewed RapidFuzz {RAPIDFUZZ_VERSION}.")
    fields = snapshot.to_dict()["fields"]
    field = next(
        (item["definition"]["field"] for item in fields if item["definition"]["column"] == column),
        None,
    )
    if field is None or not free_text(field):
        raise ValueError(
            "Spelling suggestions require mapped free text; categories use exact rules only."
        )
    baseline = preview_exact_rules(
        snapshot, column, ExactRulesSettings(), parent=parent, cancelled=cancelled
    )
    counts: Counter[str] = Counter()
    first_rows: dict[str, int] = {}
    for item in baseline.to_dict()["decisions"]:
        check_cancelled(cancelled)
        if item["column"] == column and item["outcome"] == "unchanged":
            text = item["input_text"]
            counts[text] += 1
            first_rows.setdefault(text, item["row"])
            if len(counts) > MAX_DISTINCT:
                raise ValueError(
                    "Spelling comparison exceeds 10,000 distinct values; choose a narrower saved data set."
                )
    if query not in counts:
        raise ValueError("The exact source text is not an eligible current value in this column.")
    choices = sorted(counts)
    corpus_id = hashlib.sha256(
        canonical([(s, counts[s], first_rows[s]) for s in choices]).encode("utf-8")
    ).hexdigest()
    compared_query = settings.compare_text(query)
    candidates = []
    for text in choices:
        check_cancelled(cancelled)
        if text == query:
            continue
        score = float(
            ratio(
                compared_query,
                settings.compare_text(text),
                processor=None,
                score_cutoff=settings.threshold,
            )
        )
        if score >= settings.threshold:
            candidates.append(SpellingCandidate(text, score, counts[text], first_rows[text]))
    candidates.sort(key=lambda candidate: (-candidate.score, candidate.text))
    result = SpellingSuggestions(
        snapshot.id,
        parent.id if parent else None,
        column,
        corpus_id,
        query,
        settings,
        len(counts),
        counts.total(),
        tuple(candidates),
    )
    if len(canonical(asdict(result)).encode("utf-8")) > MAX_RESULT_BYTES:
        raise ValueError("Spelling evidence exceeds the 128 MiB result limit.")
    check_cancelled(cancelled)
    return result
