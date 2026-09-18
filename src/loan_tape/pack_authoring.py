"""Editable dictionary drafts and validated publication, independent of activation."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from loan_tape.pack_format import (
    PACK_FILES,
    Pack,
    PackError,
    load_pack,
    load_pack_files,
    parse_json,
)
from loan_tape.packs import PackStore

Documents = dict[str, Any]
LOCAL_URI = "urn:loan-tape:local-field-definitions"
LOCAL_CODES_URI = "urn:loan-tape:local-code-definitions"


def documents_for(pack: Pack | None = None, *, custom_copy: bool = False) -> Documents:
    if pack:
        documents = {name: parse_json(text, name) for name, text in pack.files}
        if custom_copy:
            documents["pack.json"].update(id="", name=f"Copy of {pack.name}", version="0.1.0")
            record_copy(documents, pack)
        return documents
    return {
        "pack.json": {
            "format_version": 1,
            "id": "",
            "version": "0.1.0",
            "name": "",
            "description": "",
            "asset_classes": ["custom"],
        },
        "sources.json": [],
        "code_lists.json": [],
        "fields.json": [],
    }


def record_copy(documents: Documents, pack: Pack) -> None:
    uri = f"urn:loan-tape:pack:{pack.id}:{pack.fingerprint}"
    sources = documents["sources.json"]
    if any(source["uri"] == uri for source in sources):
        return
    sources.append(
        {
            "id": _unique_source("copied.pack", {source["id"] for source in sources}),
            "title": f"Copied from {pack.name}",
            "version": pack.version,
            "uri": uri,
        }
    )


def _unique_source(prefix: str, used: set[str]) -> str:
    key, number = prefix, 1
    while key in used:
        key = f"{prefix}.{number}"
        number += 1
    return key


def encoded(documents: Documents) -> dict[str, str]:
    if set(documents) != set(PACK_FILES):
        raise PackError("A draft requires exactly the four supported pack documents.")
    return {
        name: json.dumps(documents[name], ensure_ascii=False, indent=2) + "\n"
        for name in PACK_FILES
    }


def update_field(
    documents: Documents, index: int | None, values: dict[str, Any], base: Pack | None
) -> Documents:
    """Validate a field edit and mark its definition as locally authored, retaining background refs."""
    result = deepcopy(documents)
    field = deepcopy(values)
    old = result["fields.json"][index] if index is not None else {}
    if old and all(old.get(key) == value for key, value in values.items()):
        return result
    sources = result["sources.json"]
    source = next((item for item in sources if item["uri"] == LOCAL_URI), None)
    if source is None:
        source = {
            "id": _unique_source("local.definitions", {item["id"] for item in sources}),
            "title": "Local field definitions edited in Loan Tape",
            "version": result["pack.json"]["version"] or "draft",
            "uri": LOCAL_URI,
        }
        sources.append(source)
    references = []
    for ref in old.get("references", []):
        if ref["source"] != source["id"]:
            locator = ref["locator"]
            if not locator.startswith("Background for earlier definition: "):
                locator = "Background for earlier definition: " + locator
            references.append({"source": ref["source"], "locator": locator})
    locator = f"Locally authored field {field.get('id', '')}"
    if base and old:
        locator += f"; earlier definition {base.id}:{old['id']} v{base.version}, content {base.fingerprint}"
    references.append({"source": source["id"], "locator": locator})
    field["references"] = references
    if index is None:
        result["fields.json"].append(field)
    else:
        result["fields.json"][index] = field
    validate_draft(result)
    return result


def validate_draft(documents: Documents) -> None:
    """Check content links while allowing unfinished pack details and empty drafts."""
    validation = deepcopy(documents)
    validation["pack.json"] = {
        "format_version": 1,
        "id": "editor.draft",
        "version": "0.1.0",
        "name": "Draft",
        "description": "Draft content validation",
        "asset_classes": ["custom"],
    }
    if not validation["fields.json"] and not validation["code_lists.json"]:
        source_id = _unique_source(
            "editor.validation", {source["id"] for source in validation["sources.json"]}
        )
        validation["sources.json"].append(
            {"id": source_id, "title": "Validation only", "version": "draft", "uri": "urn:draft"}
        )
        validation["fields.json"].append(
            {
                "id": "validation",
                "label": "Validation only",
                "definition": "Validation only",
                "entity": "report",
                "data_type": "text",
                "references": [{"source": source_id, "locator": "Validation only"}],
            }
        )
    load_pack_files(encoded(validation))


@dataclass(frozen=True)
class SavedPack:
    pack: Pack
    path: Path
    backup: Path | None


def _inside(path: Path, root: Path) -> Path:
    absolute = path.absolute()
    if not absolute.is_relative_to(root) or absolute == root or absolute.resolve() != absolute:
        raise PackError(f"{path}: pack editing requires an ordinary folder inside {root}.")
    return absolute


def save_draft(
    store: PackStore,
    documents: Documents,
    *,
    path: Path | None = None,
    expected_fingerprint: str | None = None,
) -> SavedPack:
    """Publish four validated files; preserve an old folder and restore it on rename failure."""
    documents = deepcopy(documents)
    for source in documents["sources.json"]:
        if source["uri"] in {LOCAL_URI, LOCAL_CODES_URI}:
            source["version"] = documents["pack.json"]["version"]
    pack = load_pack_files(encoded(documents))
    root = store.packs_dir.absolute()
    if root.resolve() != root:
        raise PackError("The editor cannot write through a linked packs folder.")
    target = _inside(path if path is not None else root / pack.id, root)
    if target.parent != root:
        raise PackError("Choose a pack directly inside the packs folder.")
    if path is not None and expected_fingerprint is None:
        raise PackError("Editing an existing pack requires its displayed content fingerprint.")
    stage: Path | None = None
    backup = None
    try:
        with store._lock():
            root.mkdir(parents=True, exist_ok=True)
            for entry in store.available():
                if entry.pack and entry.pack.id == pack.id and entry.path.absolute() != target:
                    raise PackError(f"Pack ID {pack.id!r} already exists. Choose a different ID.")
            if path is None:
                if target.exists():
                    raise PackError(f"{target}: already exists. Choose a different pack ID.")
            else:
                current = load_pack(target)
                if current.fingerprint != expected_fingerprint:
                    raise PackError(
                        "Pack files changed since editing began. Your draft is still open; save a copy or reopen the editor."
                    )
                if pack.id != current.id:
                    raise PackError(
                        "An existing pack ID cannot be changed. Save a custom copy instead."
                    )
                entries = tuple(target.iterdir())
                if {item.name for item in entries} != set(PACK_FILES) or any(
                    not item.is_file() or item.is_symlink() for item in entries
                ):
                    raise PackError(
                        "This folder contains extra files or links. Make a custom copy to edit its dictionary safely."
                    )
            stage = _inside(root / f".draft-{uuid4().hex}", root)
            stage.mkdir()
            for name, content in pack.files:
                (stage / name).write_bytes(content.encode("utf-8"))
            if load_pack(stage).fingerprint != pack.fingerprint:
                raise PackError("Saved draft verification failed; no pack was replaced.")
            if path is not None:
                # All move targets are resolved and checked inside the same packs root.
                history = _inside(root / ".history", root)
                history.mkdir(exist_ok=True)
                backup = _inside(history / f"{pack.id}-{uuid4().hex}", root)
                target.rename(backup)
            try:
                stage.rename(target)
            except OSError as error:
                if backup:
                    try:
                        backup.rename(target)
                    except OSError as restore_error:
                        recovery_stage, stage = stage, None
                        raise PackError(
                            f"Could not publish or restore the pack. Earlier files are preserved at {backup}; "
                            f"draft files at {recovery_stage}. Restore error: {restore_error}"
                        ) from error
                raise
            stage = None
            return SavedPack(pack, target, backup)
    except OSError as error:
        raise PackError(f"Could not save the dictionary pack: {error}") from error
    finally:
        if stage is not None and stage.exists():
            # Remove only this operation's four temporary files, never a recursive tree.
            for name in PACK_FILES:
                (stage / name).unlink(missing_ok=True)
            stage.rmdir()
