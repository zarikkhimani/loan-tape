"""Versioned data-only recipes and explicit, immutable local persistence."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import asdict, dataclass, replace
from importlib.metadata import version
from pathlib import Path
from threading import Event
from typing import Any
from uuid import uuid4

from loan_tape._date_json import canonical
from loan_tape.column_definitions import _definition_from_dict
from loan_tape.pack_format import VERSION_PATTERN, object_keys, parse_json, read_text
from loan_tape.recipe_context import validate_recipe_context
from loan_tape.text_cleanup import CLEANUP_VERSION, FTFY_VERSION, TextCleanupSettings
from loan_tape.text_rule_types import (
    EXACT_OPERATION,
    ExactRule,
    ExactRulesSettings,
    free_text,
    read_rule_parameters,
    validate_rule_field,
)
from loan_tape.text_rules import rule_operation
from loan_tape.transformations import (
    MAX_STEPS,
    TransformationOperation,
    TransformationRevision,
    TransformationSnapshot,
    replay_revision,
)
from loan_tape.workbook_index import check_cancelled

MAX_RECIPE_BYTES = 16 * 1024 * 1024
MAX_RECIPES = 500
Settings = TextCleanupSettings | ExactRulesSettings


def required_text(value: Any, label: str, limit: int = 200) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > limit:
        raise ValueError(f"{label} requires nonblank text of at most {limit} UTF-8 bytes.")
    return value


def operation_settings(operation: TransformationOperation) -> tuple[int, Settings]:
    """Only implemented, fully pinned operations can become executable recipe data."""
    parameters = parse_json(operation.parameters_json, "recipe operation")
    if "recipe" in parameters:
        validate_recipe_context(parameters.pop("recipe"))
    if operation.id == EXACT_OPERATION:
        return read_rule_parameters(canonical(parameters))
    if (operation.id, operation.version, operation.engine, operation.engine_version) != (
        "text-cleanup",
        CLEANUP_VERSION,
        "ftfy",
        FTFY_VERSION,
    ):
        raise ValueError("Recipe contains an unsupported operation or engine version.")
    parameters = object_keys(
        parameters, {"selected_column", "settings", "wcwidth_version"}, set(), "text recipe step"
    )
    config = parameters["settings"]
    if not isinstance(config, dict):
        raise ValueError("Recipe text settings require an explicit configuration.")
    if "fix_encoding" not in config:
        raise ValueError("Recipe text settings omit the encoding choice.")
    settings = TextCleanupSettings(config["fix_encoding"], config.get("normalization"))
    if config != settings.config()._asdict() or parameters["wcwidth_version"] != version("wcwidth"):
        raise ValueError("Recipe text settings or dependency version are unsupported.")
    column = parameters["selected_column"]
    if type(column) is not int or not 1 <= column <= 16_384:
        raise ValueError("Recipe requires an explicit source column.")
    return column, settings


def relocate_operation(
    operation: TransformationOperation, column: int, *, portable: bool = False
) -> TransformationOperation:
    _, settings = operation_settings(operation)
    if isinstance(settings, ExactRulesSettings):
        if portable:
            # A recipe stores literal rules, not old source matches or old similarity claims.
            settings = ExactRulesSettings(
                tuple(ExactRule(r.source, r.target) for r in settings.rules)
            )
        return rule_operation(column, settings)
    data = parse_json(operation.parameters_json, "operation")
    data.pop("recipe", None)
    data["selected_column"] = column
    return replace(operation, parameters_json=canonical(data))


def snapshot_schema(snapshot: TransformationSnapshot) -> dict[str, Any]:
    data = snapshot.to_dict()
    selection = data["dataset"]["selection"]
    start = selection["area"]["min_column"]
    return {
        "column_count": data["population"]["selected_column_count"],
        "has_header": selection["header_row"] is not None,
        "fields": [
            {
                "definition": {
                    **item["definition"],
                    "column": item["definition"]["column"] - start + 1,
                },
                "header_occurrence": item["header"]["occurrence"] if item["header"] else None,
            }
            for item in data["fields"]
        ],
    }


@dataclass(frozen=True)
class Recipe:
    document_json: str

    def __post_init__(self) -> None:
        try:
            self._validate()
        except (TypeError, KeyError, AttributeError, OverflowError) as error:
            raise ValueError(
                "Recipe contains malformed typed data; no operation was loaded."
            ) from error

    def _validate(self) -> None:
        if len(self.document_json.encode("utf-8")) > MAX_RECIPE_BYTES:
            raise ValueError("Recipe exceeds the 16 MiB file limit.")
        data = object_keys(
            parse_json(self.document_json, "recipe"),
            {
                "format_version",
                "id",
                "version",
                "name",
                "profile",
                "applicability",
                "schema",
                "steps",
            },
            set(),
            "recipe",
        )
        if type(data["format_version"]) is not int or data["format_version"] != 1:
            raise ValueError("Unsupported recipe format.")
        if not isinstance(data["id"], str) or re.fullmatch(r"[0-9a-f]{32}", data["id"]) is None:
            raise ValueError("Invalid recipe ID.")
        if (
            not isinstance(data["version"], str)
            or len(data["version"]) > 80
            or not VERSION_PATTERN.fullmatch(data["version"])
        ):
            raise ValueError("Use a major.minor.patch recipe version.")
        for key in ("name", "profile"):
            required_text(data[key], key)
        required_text(data["applicability"], "Applicability / reporting context", 2000)
        schema = object_keys(
            data["schema"], {"column_count", "has_header", "fields"}, set(), "recipe schema"
        )
        if (
            type(schema["column_count"]) is not int
            or not 1 <= schema["column_count"] <= 16_384
            or type(schema["has_header"]) is not bool
        ):
            raise ValueError("Invalid recipe input schema.")
        if not isinstance(schema["fields"], list) or not 1 <= len(schema["fields"]) <= 2048:
            raise ValueError("Recipe requires bounded explicit field mappings.")
        definitions = {}
        for item in schema["fields"]:
            item = object_keys(item, {"definition", "header_occurrence"}, set(), "recipe field")
            definition = _definition_from_dict(item["definition"])
            if definition.column in definitions or definition.column > schema["column_count"]:
                raise ValueError("Duplicate or out-of-range recipe field binding.")
            definitions[definition.column] = item["definition"]
            occurrence = item["header_occurrence"]
            if schema["has_header"]:
                if type(occurrence) is not int or not 1 <= occurrence <= definition.column:
                    raise ValueError("Invalid duplicate-header occurrence.")
            elif occurrence is not None or definition.source_header:
                raise ValueError("Headerless recipe cannot claim a header.")
        if list(definitions) != sorted(definitions):
            raise ValueError("Recipe field mappings must retain source order.")
        if not isinstance(data["steps"], list) or not 1 <= len(data["steps"]) <= MAX_STEPS:
            raise ValueError("A recipe requires 1 to 12 ordered steps.")
        for item in data["steps"]:
            operation = TransformationOperation(
                **object_keys(
                    item,
                    {"id", "version", "engine", "engine_version", "parameters_json"},
                    set(),
                    "recipe step",
                )
            )
            column, settings = operation_settings(operation)
            if column not in definitions:
                raise ValueError("Recipe operation has no explicit field binding.")
            if relocate_operation(operation, column, portable=True) != operation:
                raise ValueError("Portable recipe steps cannot retain run-specific evidence.")
            if isinstance(settings, ExactRulesSettings):
                validate_rule_field(definitions[column], settings)
            elif not free_text(definitions[column]["field"]):
                raise ValueError("Text repair recipe requires a free-text field.")
        object.__setattr__(self, "document_json", canonical(data))

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.document_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return parse_json(self.document_json, "recipe")  # type: ignore[no-any-return]

    @property
    def steps(self) -> tuple[TransformationOperation, ...]:
        return tuple(TransformationOperation(**item) for item in self.to_dict()["steps"])


def recipe_from_revision(
    revision: TransformationRevision,
    *,
    name: str,
    profile: str,
    applicability: str,
    recipe_id: str | None = None,
    recipe_version: str = "1.0.0",
    cancelled: Event | None = None,
) -> Recipe:
    check_cancelled(cancelled)
    snapshot = TransformationSnapshot(canonical(revision.to_dict()["snapshot"]))
    revision = replay_revision(snapshot, revision.document_json, cancelled=cancelled)
    data = revision.to_dict()
    start = data["snapshot"]["dataset"]["selection"]["area"]["min_column"]
    operations = []
    for step in data["steps"]:
        check_cancelled(cancelled)
        operation = TransformationOperation(**step["preview"]["operation"])
        column, _ = operation_settings(operation)
        operations.append(asdict(relocate_operation(operation, column - start + 1, portable=True)))
    return Recipe(
        canonical(
            {
                "format_version": 1,
                "id": recipe_id or uuid4().hex,
                "version": recipe_version,
                "name": name,
                "profile": profile,
                "applicability": applicability,
                "schema": snapshot_schema(snapshot),
                "steps": operations,
            }
        )
    )


def recipe_directory() -> Path:
    return Path.cwd() / ".artifacts" / "recipes"


def load_recipe(path: Path, *, cancelled: Event | None = None) -> Recipe:
    check_cancelled(cancelled)
    if path.is_symlink():
        raise ValueError("Recipe files must be regular local files, not links.")
    envelope = object_keys(
        parse_json(read_text(path, limit=MAX_RECIPE_BYTES), "saved recipe"),
        {"format_version", "fingerprint", "recipe"},
        set(),
        "saved recipe",
    )
    if type(envelope["format_version"]) is not int or envelope["format_version"] != 1:
        raise ValueError("Unsupported saved recipe format.")
    recipe = Recipe(canonical(envelope["recipe"]))
    if recipe.fingerprint != envelope["fingerprint"]:
        raise ValueError("Recipe fingerprint does not match its contents.")
    check_cancelled(cancelled)
    return recipe


def save_recipe(
    recipe: Recipe, *, directory: Path | None = None, cancelled: Event | None = None
) -> Path:
    """Explicit save only; immutable ID/version files survive normal session reset."""
    check_cancelled(cancelled)
    recipe = Recipe(recipe.document_json)
    folder = directory if directory is not None else recipe_directory()
    folder.mkdir(parents=True, exist_ok=True)
    data = recipe.to_dict()
    target = folder / f"{data['id']}-{data['version']}.json"
    if target.exists():
        raise ValueError("This recipe ID/version already exists. Choose a new version or copy ID.")
    if sum(1 for _ in folder.glob("*.json")) >= MAX_RECIPES:
        raise ValueError("Recipe library exceeds 500 files; manage retained recipes before saving.")
    encoded = canonical(
        {"format_version": 1, "fingerprint": recipe.fingerprint, "recipe": data}
    ).encode("utf-8")
    if len(encoded) > MAX_RECIPE_BYTES:
        raise ValueError("Saved recipe exceeds the 16 MiB file limit.")
    temporary = folder / (".recipe-" + uuid4().hex + ".tmp")
    owns = False
    try:
        with temporary.open("xb") as stream:
            owns = True
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        check_cancelled(cancelled)
        os.link(temporary, target)
    finally:
        if owns:
            temporary.unlink(missing_ok=True)
    return target


def list_recipes(
    directory: Path | None = None, *, cancelled: Event | None = None
) -> tuple[tuple[Path, str], ...]:
    check_cancelled(cancelled)
    folder = directory if directory is not None else recipe_directory()
    paths = []
    for path in folder.glob("*.json"):
        check_cancelled(cancelled)
        paths.append(path)
        if len(paths) > MAX_RECIPES:
            raise ValueError("Recipe library exceeds 500 files.")
    results = []
    size = 0
    for path in sorted(paths):
        check_cancelled(cancelled)
        try:
            size += path.stat().st_size
            if size > 64 * 1024 * 1024:
                raise ValueError(
                    "Recipe inventory exceeds 64 MiB; manage the library before loading."
                )
            data = load_recipe(path, cancelled=cancelled).to_dict()
            label = f"{data['name']} | {data['version']} | {data['profile']}"
        except (ValueError, OSError) as error:
            label = f"Invalid: {path.name} | {error}"
        results.append((path, label))
    check_cancelled(cancelled)
    return tuple(results)
