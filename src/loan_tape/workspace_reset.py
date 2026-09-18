"""Remove one file session while preserving sources, exports, and dictionary packs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from loan_tape.date_runs import MAX_RUN_BYTES
from loan_tape.intake import IntakeStore

SOURCE_BOUND_ARTIFACTS = (
    "column-definitions",
    "selections",
    "xml-selections",
)


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _folder(root: Path, name: str) -> Path:
    folder = root / name
    if folder.exists() and (folder.is_symlink() or folder.is_junction() or not folder.is_dir()):
        raise OSError(f"File-session artifact path is not a safe directory: {folder}")
    return folder


def _unlink_regular(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_symlink() or path.is_junction() or not path.is_file():
        raise OSError(f"File-session artifact is not a safe regular file: {path}")
    path.unlink()
    return True


def _date_run_source(path: Path) -> str | None:
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_RUN_BYTES + 1)
        if len(raw) > MAX_RUN_BYTES:
            return None
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_object)
        value = data["run"]["analysis"]["inputs"]["dataset"]["source_sha256"]
        return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) else None
    except OSError:
        raise
    except (ValueError, KeyError, TypeError, RecursionError):
        return None


def reset_file_session(
    store: IntakeStore,
    session_id: str,
    artifact_root: Path | None = None,
) -> tuple[int, int]:
    """Clear records and source-bound state after this session's workers have stopped."""
    if not re.fullmatch(r"[0-9a-f]{32}", session_id):
        raise ValueError("Invalid session identity.")
    records = store.list_files() if store.directory.exists() else []
    source_hashes = {record["sha256"] for record in records}
    root = (artifact_root if artifact_root is not None else Path.cwd() / ".artifacts").resolve()
    removed_artifacts = 0

    for name in SOURCE_BOUND_ARTIFACTS:
        folder = _folder(root, name)
        for source_hash in source_hashes:
            removed_artifacts += _unlink_regular(folder / f"{source_hash}.json")
        try:
            folder.rmdir()
        except OSError:
            pass

    runs = _folder(root, "date-runs")
    if runs.exists():
        for path in runs.glob("*.json"):
            if not re.fullmatch(r"[0-9a-f]{32}\.json", path.name):
                continue
            if path.is_symlink() or path.is_junction() or not path.is_file():
                raise OSError(f"Date-run artifact is not a safe regular file: {path}")
            if _date_run_source(path) in source_hashes:
                path.unlink()
                removed_artifacts += 1
        try:
            runs.rmdir()
        except OSError:
            pass

    sessions = _folder(root, "sessions")
    removed_artifacts += _unlink_regular(sessions / f"{session_id}.json")
    try:
        sessions.rmdir()
    except OSError:
        pass

    removed_files = store.clear()
    try:
        root.rmdir()
    except OSError:
        pass
    return removed_files, removed_artifacts
