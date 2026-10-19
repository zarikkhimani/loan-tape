"""Borrower relationship review contracts; no source rows are merged or rewritten."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from loan_tape._date_json import canonical, fingerprint
from loan_tape.recipe_context import validate_complete_recipe_history
from loan_tape.transformations import (
    TransformationRevision,
    TransformationSnapshot,
    derived_text_values,
    replay_revision,
)

MAX_ROWS = 500
MAX_FEATURES = 6
MAX_LABELS = 2000
MAX_BYTES = 64 * 1024 * 1024
VERSION = "1.0.0"


def bounded(value: Any) -> str:
    result = canonical(value)
    if len(result.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Entity review exceeds the 64 MiB evidence limit.")
    return result


def review_metadata(reviewer: str, reason: str, moment: str) -> None:
    for value in (reviewer, reason):
        if not isinstance(value, str) or not value.strip() or len(value) > 2000:
            raise ValueError("Provide a reviewer and reason of at most 2,000 characters.")
    parsed = datetime.fromisoformat(moment)
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("Review decisions require a UTC timestamp.")


def eligible_field(field: dict[str, Any]) -> bool:
    return (
        field["entity"] == "borrower"
        and field["data_type"] in {"text", "identifier"}
        and field["code_list"] is None
        and field["canonical_unit"] is None
        and not {"currency", "unit"}.intersection(field["context"])
    )


@dataclass(frozen=True)
class EntityPopulation:
    document_json: str

    @property
    def id(self) -> str:
        return fingerprint(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.document_json)  # type: ignore[no-any-return]


def prepare_population(
    snapshot: TransformationSnapshot,
    columns: tuple[int, ...],
    parent: TransformationRevision | None = None,
) -> EntityPopulation:
    """Use only explicitly selected borrower fields with complete literal text evidence."""
    if (
        not isinstance(columns, tuple)
        or not 1 <= len(columns) <= MAX_FEATURES
        or any(type(c) is not int or c < 1 for c in columns)
        or len(set(columns)) != len(columns)
    ):
        raise ValueError("Choose one to six distinct mapped borrower columns.")
    original = snapshot.to_dict()
    if not 2 <= original["population"]["row_count"] <= MAX_ROWS:
        raise ValueError("Entity matching supports saved selections of 2 to 500 data rows.")
    definitions = {f["definition"]["column"]: f["definition"] for f in original["fields"]}
    features = []
    for column in sorted(columns):
        definition = definitions.get(column)
        if definition is None or not eligible_field(definition["field"]):
            raise ValueError("Select mapped borrower text or borrower identifiers only.")
        features.append(
            {
                "column": column,
                "field_id": definition["field"]["id"],
                "comparator": "Exact"
                if definition["field"]["data_type"] == "identifier"
                else "String",
            }
        )
    if not any(f["comparator"] == "String" for f in features):
        raise ValueError("Select at least one borrower text field for Dedupe blocking.")
    overlay = {}
    if parent is not None:
        replay_revision(snapshot, parent.document_json)
        validate_complete_recipe_history(parent.to_dict()["steps"], snapshot.id)
        overlay = {(r, c): value for r, c, value in derived_text_values(parent)}
    cells = {(c["row"], c["column"]): c for c in original["cells"]}
    first = original["population"]["first_row"]
    rows = []
    for row in range(first, first + original["population"]["row_count"]):
        values: dict[str, str] = {}
        exclusions = []
        for feature in features:
            column = feature["column"]
            cell = cells[row, column]
            value = overlay.get((row, column), cell["evidence"]["raw"])
            if cell["state"] != "text":
                exclusions.append({"column": column, "state": cell["state"]})
            elif not isinstance(value, str) or not value.strip() or "\ufffd" in value:
                exclusions.append({"column": column, "state": "unreadable_or_unretained_text"})
            elif len(value.encode("utf-8")) > 4096:
                exclusions.append({"column": column, "state": "text_exceeds_4_KiB"})
            else:
                values[str(column)] = value
        rows.append({"row": row, "values": values, "exclusions": exclusions})
    if sum(not r["exclusions"] for r in rows) < 2:
        raise ValueError("At least two rows need usable literal text in every selected feature.")
    return EntityPopulation(
        bounded(
            {
                "version": VERSION,
                "snapshot_id": snapshot.id,
                "snapshot": original,
                "parent_id": parent.id if parent else None,
                "parent": parent.to_dict() if parent else None,
                "features": features,
                "rows": rows,
                "population": {
                    "total": len(rows),
                    "eligible": sum(not r["exclusions"] for r in rows),
                    "excluded": sum(bool(r["exclusions"]) for r in rows),
                },
            }
        )
    )


@dataclass(frozen=True)
class PairLabel:
    left: int
    right: int
    label: str
    reviewer: str
    reason: str
    decided_at_utc: str

    def __post_init__(self) -> None:
        if (
            type(self.left) is not int
            or type(self.right) is not int
            or not 0 < self.left < self.right
        ):
            raise ValueError("Choose two different source rows in ascending order.")
        if self.label not in {"match", "distinct"}:
            raise ValueError("Label the pair as same borrower or different borrowers.")
        review_metadata(self.reviewer, self.reason, self.decided_at_utc)


def validate_labels(population: EntityPopulation, labels: tuple[PairLabel, ...]) -> None:
    if not isinstance(labels, tuple) or not 20 <= len(labels) <= MAX_LABELS:
        raise ValueError(
            "Provide 10 same-borrower and 10 different-borrower pairs (maximum 2,000)."
        )
    if any(not isinstance(label, PairLabel) for label in labels):
        raise ValueError("Invalid pair label.")
    if min(sum(label.label == kind for label in labels) for kind in ("match", "distinct")) < 10:
        raise ValueError("Provide at least 10 reviewed pairs of each class before training.")
    records = {r["row"]: r["values"] for r in population.to_dict()["rows"] if not r["exclusions"]}
    keys = {(label.left, label.right) for label in labels}
    if len(keys) != len(labels) or any(a not in records or b not in records for a, b in keys):
        raise ValueError("Labels must refer to distinct eligible source pairs, once per pair.")
    roots = {row: row for row in records}

    def find(row: int) -> int:
        while row != roots[row]:
            row = roots[row]
        return row

    for label in labels:
        if label.label == "match":
            roots[find(label.right)] = find(label.left)
    evidence: dict[str, str] = {}
    for label in labels:
        if label.label == "distinct" and find(label.left) == find(label.right):
            raise ValueError("Pair labels contradict an approved same-borrower chain.")
        key = canonical(sorted((canonical(records[label.left]), canonical(records[label.right]))))
        if key in evidence and evidence[key] != label.label:
            raise ValueError("Identical feature comparisons have contradictory labels.")
        evidence[key] = label.label


def validate_threshold(threshold: float) -> None:
    if type(threshold) not in {int, float} or not math.isfinite(threshold) or not 0 < threshold < 1:
        raise ValueError("Choose an explicit grouping threshold strictly between 0 and 1.")


@dataclass(frozen=True)
class EntityRun:
    document_json: str

    @property
    def id(self) -> str:
        return fingerprint(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.document_json)  # type: ignore[no-any-return]


def review_relationships(
    run: EntityRun,
    decisions: dict[str, str],
    reviewer: str,
    reason: str,
    moment: str,
) -> str:
    """Record a decision on every proposed group, retaining each source row separately."""
    review_metadata(reviewer, reason, moment)
    data = run.to_dict()
    groups = data["engine"]["groups"]
    if set(decisions) != {g["id"] for g in groups} or any(
        value not in {"approve", "reject"} for value in decisions.values()
    ):
        raise ValueError("Explicitly approve or reject each proposed group.")
    accepted = []
    for group in groups:
        if decisions[group["id"]] == "approve":
            members = set(group["rows"])
            if any(
                label["label"] == "distinct" and {label["left"], label["right"]} <= members
                for label in data["labels"]
            ):
                raise ValueError(
                    "This group contradicts a distinct-borrower label. Correct labels and retrain."
                )
            accepted.append(
                {
                    "relationship": "same_borrower",
                    "group_id": group["id"],
                    "source_rows": group["rows"],
                }
            )
    return bounded(
        {
            "format_version": 1,
            "run_id": run.id,
            "run": data,
            "review": {
                "reviewer": reviewer,
                "reason": reason,
                "decided_at_utc": moment,
                "decisions": decisions,
            },
            "relationships": accepted,
            "loan_rows_modified": 0,
            "limitation": "Borrower relationships only. Facilities, tranches, positions and reporting dates remain separate. No independent matching accuracy has been established.",
        }
    )


def labels_payload(labels: tuple[PairLabel, ...]) -> list[dict[str, Any]]:
    return [asdict(label) for label in sorted(labels, key=lambda item: (item.left, item.right))]
