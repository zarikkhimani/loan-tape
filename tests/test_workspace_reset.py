"""Normal application exit removes only its source-bound session state."""

import json
from pathlib import Path

import pytest

from loan_tape.intake import IntakeStore
from loan_tape.workspace_reset import SOURCE_BOUND_ARTIFACTS, reset_file_session

SESSION_ID = "1" * 32


def test_reset_preserves_original_exports_packs_and_other_sessions(tmp_path: Path) -> None:
    source = tmp_path / "source.xlsx"
    source.write_bytes(b"source bytes")
    store = IntakeStore(tmp_path / "inputs")
    record = store.save_path(source)
    saved = Path(str(store.describe(record)["saved_path"]))
    artifacts = tmp_path / ".artifacts"
    for name in SOURCE_BOUND_ARTIFACTS:
        folder = artifacts / name
        folder.mkdir(parents=True)
        (folder / f"{record['sha256']}.json").write_text("{}", encoding="utf-8")
        (folder / ("f" * 64 + ".json")).write_text("{}", encoding="utf-8")
    sessions = artifacts / "sessions"
    sessions.mkdir()
    (sessions / f"{SESSION_ID}.json").write_text("{}", encoding="utf-8")
    other_session = sessions / ("2" * 32 + ".json")
    other_session.write_text("{}", encoding="utf-8")
    runs = artifacts / "date-runs"
    runs.mkdir()
    matching_run = runs / ("3" * 32 + ".json")
    matching_run.write_text(
        json.dumps(
            {"run": {"analysis": {"inputs": {"dataset": {"source_sha256": record["sha256"]}}}}}
        ),
        encoding="utf-8",
    )
    other_run = runs / ("4" * 32 + ".json")
    other_run.write_text(
        json.dumps({"run": {"analysis": {"inputs": {"dataset": {"source_sha256": "e" * 64}}}}}),
        encoding="utf-8",
    )
    pack = artifacts / "packs" / "profile.json"
    pack.parent.mkdir(parents=True)
    pack.write_text("{}", encoding="utf-8")
    unrelated = artifacts / "review-notes" / "note.txt"
    unrelated.parent.mkdir()
    unrelated.write_text("keep", encoding="utf-8")
    exported = tmp_path / "outputs" / "review.xlsx"
    exported.parent.mkdir()
    exported.write_bytes(b"explicit export")

    assert reset_file_session(store, SESSION_ID, artifacts) == (
        1,
        len(SOURCE_BOUND_ARTIFACTS) + 2,
    )
    assert not saved.exists()
    assert store.list_files() == []
    assert all(
        not (artifacts / name / f"{record['sha256']}.json").exists()
        for name in SOURCE_BOUND_ARTIFACTS
    )
    assert all(
        (artifacts / name / ("f" * 64 + ".json")).exists() for name in SOURCE_BOUND_ARTIFACTS
    )
    assert not matching_run.exists() and other_run.exists()
    assert not (sessions / f"{SESSION_ID}.json").exists() and other_session.exists()
    assert source.read_bytes() == b"source bytes"
    assert pack.read_text(encoding="utf-8") == "{}"
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert exported.read_bytes() == b"explicit export"


def test_reset_rejects_an_unsafe_artifact_target(tmp_path: Path) -> None:
    store = IntakeStore(tmp_path / "inputs")
    artifacts = tmp_path / ".artifacts"
    artifacts.mkdir()
    (artifacts / "sessions").write_text("not a directory", encoding="utf-8")

    with pytest.raises(OSError, match="not a safe directory"):
        reset_file_session(store, SESSION_ID, artifacts)
