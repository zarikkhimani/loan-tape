"""Small strict serialization helpers shared by versioned date artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any


def _default(value: Any) -> str:
    if type(value) is date:
        return value.isoformat()
    raise TypeError(f"Unsupported date artifact value: {type(value).__name__}")


def canonical(value: Any) -> str:
    return json.dumps(
        value,
        default=_default,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def iso_date(value: Any) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Expected an ISO calendar date (YYYY-MM-DD).")
    return date.fromisoformat(value)


def integer(value: Any, low: int, high: int, name: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer between {low} and {high}.")
    return value


def text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} requires non-empty text.")
    return value
