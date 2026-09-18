"""Validated source, citation, and allowed-value edits on independent pack drafts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from loan_tape.pack_authoring import (
    LOCAL_CODES_URI,
    LOCAL_URI,
    Documents,
    _unique_source,
    validate_draft,
)
from loan_tape.pack_format import Pack, PackError

ContentKind = Literal["fields.json", "code_lists.json"]


def managed_source(source: dict[str, Any]) -> bool:
    """Application authorship and copied-pack evidence are retained automatically."""
    uri = source.get("uri")
    return isinstance(uri, str) and (
        uri in {LOCAL_URI, LOCAL_CODES_URI} or uri.startswith("urn:loan-tape:pack:")
    )


def managed_ids(documents: Documents) -> set[str]:
    return {source["id"] for source in documents["sources.json"] if managed_source(source)}


def update_source(documents: Documents, index: int | None, values: dict[str, Any]) -> Documents:
    result = deepcopy(documents)
    if index is not None:
        old = result["sources.json"][index]
        if old == values:
            return result
        if managed_source(old):
            raise PackError("Automatic authorship and copied-pack sources cannot be edited.")
        if old["id"] != values.get("id"):
            raise PackError("An existing source keeps its ID. Add a new source instead.")
    if managed_source(values):
        raise PackError("This source location is reserved for automatic authorship records.")
    if index is None:
        result["sources.json"].append(deepcopy(values))
    else:
        result["sources.json"][index] = deepcopy(values)
    validate_draft(result)
    return result


def source_uses(documents: Documents, source_id: str) -> list[str]:
    return [
        f"{label} {item['id']}"
        for name, label in (("fields.json", "field"), ("code_lists.json", "allowed-value list"))
        for item in documents[name]
        if any(ref["source"] == source_id for ref in item["references"])
    ]


def remove_source(documents: Documents, index: int) -> Documents:
    source = documents["sources.json"][index]
    if managed_source(source):
        raise PackError("Automatic authorship and copied-pack sources are retained for provenance.")
    uses = source_uses(documents, source["id"])
    if uses:
        raise PackError(f"Source is still cited by {', '.join(uses)}. Edit those citations first.")
    result = deepcopy(documents)
    result["sources.json"].pop(index)
    validate_draft(result)
    return result


def _retain_managed(
    documents: Documents, old: list[dict[str, str]], references: list[dict[str, str]]
) -> None:
    protected = managed_ids(documents)
    if [ref for ref in old if ref["source"] in protected] != [
        ref for ref in references if ref["source"] in protected
    ]:
        raise PackError("Automatic authorship citations must be retained unchanged.")


def update_citations(
    documents: Documents, kind: ContentKind, index: int, references: list[dict[str, str]]
) -> Documents:
    result = deepcopy(documents)
    item = result[kind][index]
    _retain_managed(result, item["references"], references)
    item["references"] = deepcopy(references)
    validate_draft(result)
    return result


def update_code_list(
    documents: Documents, index: int | None, values: dict[str, Any], base: Pack | None
) -> Documents:
    """Keep exact code strings and mark new/changed definitions as locally authored."""
    result = deepcopy(documents)
    old = result["code_lists.json"][index] if index is not None else {}
    if old and old["id"] != values.get("id"):
        raise PackError("An existing allowed-value list keeps its ID. Add a new list instead.")
    item = deepcopy(values)
    references = item.get("references", [])
    _retain_managed(result, old.get("references", []), references)
    if old.get("codes") != item.get("codes"):
        source = next(
            (source for source in result["sources.json"] if source["uri"] == LOCAL_CODES_URI),
            None,
        )
        if source is None:
            source = {
                "id": _unique_source("local.codes", {s["id"] for s in result["sources.json"]}),
                "title": "Local allowed-value definitions edited in Loan Tape",
                "version": result["pack.json"]["version"] or "draft",
                "uri": LOCAL_CODES_URI,
            }
            result["sources.json"].append(source)
        background = []
        for ref in references:
            if ref["source"] != source["id"]:
                locator = ref["locator"]
                if ref in old.get("references", []) and not locator.startswith(
                    "Background for earlier definition: "
                ):
                    locator = "Background for earlier definition: " + locator
                background.append({"source": ref["source"], "locator": locator})
        locator = f"Locally authored allowed-value list {item.get('id', '')}"
        if base and old and any(previous.id == old["id"] for previous in base.code_lists):
            locator += (
                f"; earlier list {base.id}:{old['id']} v{base.version}, content {base.fingerprint}"
            )
        item["references"] = [*background, {"source": source["id"], "locator": locator}]
    if index is None:
        result["code_lists.json"].append(item)
    else:
        result["code_lists.json"][index] = item
    # In particular, removing/renaming a code must not invalidate a field's missing_codes.
    validate_draft(result)
    return result


def remove_code_list(documents: Documents, index: int) -> Documents:
    key = documents["code_lists.json"][index]["id"]
    uses = [
        field["id"]
        for field in documents["fields.json"]
        if key in (field.get("code_list"), field.get("missing_code_list"))
    ]
    if uses:
        raise PackError(
            f"Allowed-value list is still used by fields {', '.join(uses)}. "
            "Change those field selections first."
        )
    result = deepcopy(documents)
    result["code_lists.json"].pop(index)
    validate_draft(result)
    return result
