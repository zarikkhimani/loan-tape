"""Bounded recipe provenance carried in a transformation operation's parameters."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from loan_tape._date_json import canonical
from loan_tape.pack_format import VERSION_PATTERN, object_keys


def validate_binding(value: Any) -> dict[str, Any]:
    data = object_keys(
        value,
        {
            "format_version",
            "recipe_fingerprint",
            "snapshot_id",
            "profile",
            "context",
            "reviewer",
            "confirmed_at_utc",
        },
        set(),
        "recipe binding",
    )
    if type(data["format_version"]) is not int or data["format_version"] != 1:
        raise ValueError("Unsupported recipe binding format.")
    for key in ("recipe_fingerprint", "snapshot_id"):
        if not isinstance(data[key], str) or re.fullmatch(r"[0-9a-f]{64}", data[key]) is None:
            raise ValueError("Invalid recipe binding identity.")
    for key, limit in (("profile", 200), ("context", 2000), ("reviewer", 200)):
        if (
            not isinstance(data[key], str)
            or not data[key].strip()
            or len(data[key].encode("utf-8")) > limit
        ):
            raise ValueError(
                f"Recipe binding {key} requires nonblank text up to {limit} UTF-8 bytes."
            )
    if not isinstance(data["confirmed_at_utc"], str):
        raise ValueError("Recipe binding requires a UTC confirmation time.")
    moment = datetime.fromisoformat(data["confirmed_at_utc"])
    if moment.tzinfo is None or moment.utcoffset() != UTC.utcoffset(moment):
        raise ValueError("Recipe binding requires a UTC confirmation time.")
    return data


def validate_recipe_context(value: Any) -> dict[str, Any]:
    data = object_keys(
        value,
        {"id", "version", "fingerprint", "binding_id", "binding", "step", "total"},
        set(),
        "recipe context",
    )
    for key, size in (("id", 32), ("fingerprint", 64), ("binding_id", 64)):
        if not isinstance(data[key], str) or re.fullmatch(f"[0-9a-f]{{{size}}}", data[key]) is None:
            raise ValueError("Invalid recipe context identity.")
    if (
        not isinstance(data["version"], str)
        or not VERSION_PATTERN.fullmatch(data["version"])
        or len(data["version"]) > 80
    ):
        raise ValueError("Unsupported recipe version.")
    if (
        any(type(data[key]) is not int for key in ("step", "total"))
        or not 1 <= data["step"] <= data["total"] <= 12
    ):
        raise ValueError("Invalid recipe step context.")
    binding = validate_binding(data["binding"])
    if (
        binding["recipe_fingerprint"] != data["fingerprint"]
        or hashlib.sha256(canonical(binding).encode("utf-8")).hexdigest() != data["binding_id"]
    ):
        raise ValueError("Recipe context does not match its explicit binding.")
    return data


def validate_complete_recipe_history(steps: list[dict[str, Any]], snapshot_id: str) -> None:
    """Require complete, ordered recipe runs before reusing a replayed history.

    Intermediate steps remain valid in memory while a recipe is being reviewed,
    but cannot be saved, exported or supplied as a completed matching input.
    """
    pending: tuple[str, int, int] | None = None
    for step in steps:
        context = json.loads(step["preview"]["operation"]["parameters_json"]).get("recipe")
        if context is None:
            if pending is not None:
                raise ValueError(
                    "An incomplete staged recipe cannot be used as a completed result."
                )
            continue
        expected = pending or (context["binding_id"], 1, context["total"])
        if (context["binding_id"], context["step"], context["total"]) != expected or context[
            "binding"
        ]["snapshot_id"] != snapshot_id:
            raise ValueError("Recipe history or source binding is incomplete or conflicting.")
        pending = (
            None
            if context["step"] == context["total"]
            else (context["binding_id"], context["step"] + 1, context["total"])
        )
    if pending is not None:
        raise ValueError("An incomplete staged recipe cannot be used as a completed result.")
