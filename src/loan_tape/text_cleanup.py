"""Conservative, explicitly configured ftfy proposals and guarded session application."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path
from threading import Event
from typing import Literal

import ftfy

from loan_tape._date_json import canonical
from loan_tape.column_definitions import DefinitionScope, definitions_for_table
from loan_tape.packs import PackStore
from loan_tape.selection import SavedTable, load_tables
from loan_tape.text_rule_types import ExactRulesSettings, exact_field
from loan_tape.text_rules import (
    SpellingSettings,
    SpellingSuggestions,
    preview_exact_rules,
    suggest_spellings,
)
from loan_tape.transformation_excel import publish_transformation, read_transformation_snapshot
from loan_tape.transformations import (
    MAX_TOKEN_BYTES,
    CellProposal,
    TransformationApproval,
    TransformationOperation,
    TransformationPreview,
    TransformationRevision,
    TransformationSnapshot,
    preview_transformation,
)
from loan_tape.workbook_index import check_cancelled

FTFY_VERSION = "6.3.1"
CLEANUP_VERSION = "1.0.0"


@dataclass(frozen=True)
class TextCleanupSettings:
    repair_encoding: bool = True
    normalization: Literal["NFC"] | None = None

    def __post_init__(self) -> None:
        if type(self.repair_encoding) is not bool or self.normalization not in {None, "NFC"}:
            raise ValueError("Choose encoding repair and/or optional NFC normalization.")
        if not self.repair_encoding and self.normalization is None:
            raise ValueError("Choose at least one cleanup operation before previewing.")

    def config(self) -> ftfy.TextFixerConfig:
        return ftfy.TextFixerConfig(
            unescape_html=False,
            remove_terminal_escapes=False,
            fix_encoding=self.repair_encoding,
            restore_byte_a0=False,
            replace_lossy_sequences=False,
            decode_inconsistent_utf8=False,
            fix_c1_controls=False,
            fix_latin_ligatures=False,
            fix_character_width=False,
            uncurl_quotes=False,
            fix_line_breaks=False,
            fix_surrogates=False,
            remove_control_chars=False,
            normalization=self.normalization,
            max_decode_length=MAX_TOKEN_BYTES,
            explain=True,
        )


def cleanup_scope(table: SavedTable, column: int, *, exact: bool = False) -> DefinitionScope:
    """Load current explicit definitions; never infer a field from its header."""
    definitions = definitions_for_table(table)
    definition = next((item for item in definitions if item.column == column), None)
    if definition is None:
        raise ValueError("Use Define column to map this column to an active text field first.")
    field = definition.field
    if exact:
        if not exact_field(asdict(field)):
            raise ValueError(
                "Exact rules require mapped free text or a category with frozen allowed values."
            )
        return DefinitionScope(table.id, table.name, table.selection, definitions)
    if (
        field.data_type != "text"
        or field.code_list is not None
        or field.canonical_unit is not None
        or {"currency", "unit"}.intersection(field.context)
    ):
        raise ValueError(
            "Clean text requires a free-text field. This column's meaning is excluded."
        )
    return DefinitionScope(table.id, table.name, table.selection, definitions)


def preview_text_cleanup(
    snapshot: TransformationSnapshot,
    column: int,
    settings: TextCleanupSettings,
    *,
    parent: TransformationRevision | None = None,
    cancelled: Event | None = None,
) -> TransformationPreview:
    """Generate proposals for one explicitly selected column across its complete data set."""
    check_cancelled(cancelled)
    if version("ftfy") != FTFY_VERSION or ftfy.__version__ != FTFY_VERSION:
        raise ValueError(f"Text cleanup requires the reviewed ftfy {FTFY_VERSION} runtime.")
    config = settings.config()
    operation = TransformationOperation(
        "text-cleanup",
        CLEANUP_VERSION,
        "ftfy",
        FTFY_VERSION,
        canonical(
            {
                "selected_column": column,
                "settings": config._asdict(),
                "wcwidth_version": version("wcwidth"),
            }
        ),
    )
    fields = snapshot.to_dict()["fields"]
    definition = next(
        (item["definition"] for item in fields if item["definition"]["column"] == column), None
    )
    if definition is None or definition["field"]["data_type"] != "text":
        raise ValueError("Choose an explicitly mapped text column.")
    baseline = preview_transformation(snapshot, operation, (), parent=parent, cancelled=cancelled)
    proposals = []
    for decision in baseline.to_dict()["decisions"]:
        check_cancelled(cancelled)
        if decision["column"] != column or decision["outcome"] != "unchanged":
            continue
        raw = decision["input_text"]
        if not isinstance(raw, str):
            raise ValueError("Eligible text evidence has no literal input value.")
        status, proposed, reason = "proposed", None, "No repair suggested by the selected settings."
        if "\ufffd" in raw:
            status, reason = (
                "unresolved",
                "Replacement characters indicate lost text; review the source.",
            )
        else:
            try:
                fixed = ftfy.fix_and_explain(raw, config)
                proposed = fixed.text
                if "\ufffd" in proposed or len(proposed.encode("utf-8")) > MAX_TOKEN_BYTES:
                    status, proposed, reason = (
                        "unresolved",
                        None,
                        "Repair is lossy or exceeds the text limit.",
                    )
                elif proposed != raw:
                    reason = "ftfy proposal: " + "; ".join(
                        f"{step.action} {step.parameter}" for step in (fixed.explanation or [])
                    )
            except Exception as error:
                status, proposed, reason = (
                    "failed",
                    None,
                    f"Text cleanup failed ({type(error).__name__}).",
                )
        proposals.append(
            CellProposal(
                decision["row"], column, raw, proposed, "reviewed-text-cleanup", reason, status
            )
        )
    return preview_transformation(
        snapshot, operation, tuple(proposals), parent=parent, cancelled=cancelled
    )


@dataclass(frozen=True)
class TextCleanupReview:
    snapshot: TransformationSnapshot
    preview: TransformationPreview
    scope: DefinitionScope


def review_excel_text(
    source: Path,
    table: SavedTable,
    column: int,
    settings: TextCleanupSettings | ExactRulesSettings,
    store: PackStore,
    *,
    parent: TransformationRevision | None = None,
    cancelled: Event | None = None,
) -> TextCleanupReview:
    scope = cleanup_scope(table, column, exact=isinstance(settings, ExactRulesSettings))
    snapshot = read_transformation_snapshot(
        source, table, scope, store.catalog(), cancelled=cancelled
    )
    preview = (
        preview_exact_rules(snapshot, column, settings, parent=parent, cancelled=cancelled)
        if isinstance(settings, ExactRulesSettings)
        else preview_text_cleanup(snapshot, column, settings, parent=parent, cancelled=cancelled)
    )
    return TextCleanupReview(snapshot, preview, scope)


def apply_excel_text(
    source: Path,
    table: SavedTable,
    column: int,
    settings: TextCleanupSettings | ExactRulesSettings,
    store: PackStore,
    review: TextCleanupReview,
    approval: TransformationApproval,
    *,
    parent: TransformationRevision | None = None,
    cancelled: Event | None = None,
) -> tuple[TransformationRevision, Path]:
    """Re-run the pinned engine and current metadata before atomic publication."""
    current = review_excel_text(
        source, table, column, settings, store, parent=parent, cancelled=cancelled
    )
    if current != review:
        raise ValueError(
            "Cleanup inputs or settings changed; create a new preview and review it again."
        )
    catalog = store.catalog()

    def guard() -> None:
        check_cancelled(cancelled)
        tables = load_tables(table.selection.workbook_sha256).tables
        if (
            table not in tables
            or cleanup_scope(table, column, exact=isinstance(settings, ExactRulesSettings))
            != current.scope
        ):
            raise ValueError(
                "Saved data set or mappings changed before application; preview again."
            )
        if store.catalog() != catalog:
            raise ValueError("Active dictionary changed before application; preview again.")

    guard()
    return publish_transformation(
        source,
        table,
        current.scope,
        catalog,
        review.preview,
        approval,
        parent=parent,
        cancelled=cancelled,
        before_publish=guard,
    )


def suggest_excel_text(
    source: Path,
    table: SavedTable,
    column: int,
    query: str,
    settings: SpellingSettings,
    store: PackStore,
    *,
    parent: TransformationRevision | None = None,
    cancelled: Event | None = None,
) -> SpellingSuggestions:
    scope = cleanup_scope(table, column)
    snapshot = read_transformation_snapshot(
        source, table, scope, store.catalog(), cancelled=cancelled
    )
    return suggest_spellings(snapshot, column, query, settings, parent=parent, cancelled=cancelled)
