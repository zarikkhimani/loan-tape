"""Borrower review preserves source rows and refuses ambiguous/stale approvals."""

import hashlib
import json
from dataclasses import replace
from itertools import combinations
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from text_cleanup_support import prepare

from loan_tape import entity_matching as service
from loan_tape.column_definitions import save_column_definition
from loan_tape.entities import (
    EntityRun,
    PairLabel,
    bounded,
    prepare_population,
    review_relationships,
    validate_labels,
    validate_threshold,
)
from loan_tape.entity_matching import (
    entity_scope,
    population_guard,
    publish_bytes,
    read_population,
    train_entities,
)
from loan_tape.selection import TableSelections, save_tables
from loan_tape.text_cleanup import TextCleanupSettings, apply_excel_text, review_excel_text
from loan_tape.transformation_excel import read_transformation_snapshot
from loan_tape.transformations import TransformationApproval

MOMENT = "2026-10-19T00:00:00+00:00"


def test_matching_cleanup_waits_for_descendants_after_launcher_exit(monkeypatch, tmp_path):
    lifecycle = []
    job = SimpleNamespace(Close=lambda: lifecycle.append("close-job"))
    process = SimpleNamespace(Close=lambda: lifecycle.append("close-launcher"))
    remaining = iter((1, 1, 0))

    def query(handle, info):
        assert handle is job
        if info == "limits":
            return {"BasicLimitInformation": {"LimitFlags": 0}}
        assert "terminate-job" in lifecycle and "close-job" not in lifecycle
        active = next(remaining)
        lifecycle.append(f"active-{active}")
        return {"ActiveProcesses": active}

    modules = {
        "win32job": SimpleNamespace(
            CreateJobObject=lambda *args: job,
            QueryInformationJobObject=query,
            SetInformationJobObject=lambda *args: None,
            JobObjectExtendedLimitInformation="limits",
            JobObjectBasicAccountingInformation="counts",
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE=1,
            TerminateJobObject=lambda *args: lifecycle.append("terminate-job"),
        ),
        "win32event": SimpleNamespace(WaitForSingleObject=lambda *args: 0),
        "win32process": SimpleNamespace(GetExitCodeProcess=lambda *args: 0),
    }
    monkeypatch.setattr(service.importlib, "import_module", lambda name: modules[name])
    monkeypatch.setattr(service, "start_in_job", lambda *args: (process, 1))
    monkeypatch.setattr(service.time, "sleep", lambda seconds: lifecycle.append("wait"))
    service.execute_worker(tmp_path, Path("python.exe"), None, 5)
    assert lifecycle == [
        "terminate-job",
        "active-1",
        "wait",
        "active-1",
        "wait",
        "active-0",
        "close-launcher",
        "close-job",
    ]


@pytest.mark.parametrize("winerror", [32, 5])
def test_matching_temporary_cleanup_retries_only_sharing_locks(monkeypatch, tmp_path, winerror):
    calls = []
    temporary = tmp_path / "worker-owned"
    temporary.mkdir()
    failure = PermissionError("locked")
    failure.winerror = winerror

    def cleanup(path):
        assert path == temporary
        calls.append("cleanup")
        if calls.count("cleanup") == 1:
            raise failure
        temporary.rmdir()

    monkeypatch.setattr(service.tempfile, "mkdtemp", lambda **kwargs: str(temporary))
    monkeypatch.setattr(service.shutil, "rmtree", cleanup)
    monkeypatch.setattr(service.time, "sleep", lambda seconds: calls.append("wait"))
    if winerror == 5:
        with pytest.raises(RuntimeError, match="could not be removed"):
            with service.worker_directory(tmp_path):
                pass
        assert calls == ["cleanup"] and temporary.exists()
    else:
        with pytest.raises(ValueError, match="original timeout"):
            with service.worker_directory(tmp_path):
                raise ValueError("original timeout")
        assert calls == ["cleanup", "wait", "cleanup"] and not temporary.exists()


def test_matching_persistent_sharing_lock_reports_retained_files(monkeypatch, tmp_path):
    temporary = tmp_path / "worker-owned"
    temporary.mkdir()
    failure = PermissionError("still locked")
    failure.winerror = 32

    def cleanup(path):
        assert path == temporary
        raise failure

    times = iter((0, 6))
    monkeypatch.setattr(service.tempfile, "mkdtemp", lambda **kwargs: str(temporary))
    monkeypatch.setattr(service.shutil, "rmtree", cleanup)
    monkeypatch.setattr(service.time, "monotonic", lambda: next(times))
    with pytest.raises(RuntimeError, match="could not be removed"):
        with service.worker_directory(tmp_path):
            pass
    assert temporary.exists()


@pytest.fixture
def sample(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    values = [f"Fictional borrower {i // 2} {'Holdings' if i % 2 else 'Hldgs'}" for i in range(24)]
    original, source, intake, table, store = prepare(tmp_path, values)
    population = read_population(source, table, entity_scope(table), store.catalog(), (1,))
    pairs = [(r, r + 1) for r in range(2, 26, 2)]
    labels = tuple(
        PairLabel(a, b, "match", "Reviewer", "Synthetic same entity", MOMENT) for a, b in pairs
    )
    labels += tuple(
        PairLabel(a[0], b[0], "distinct", "Reviewer", "Synthetic different entities", MOMENT)
        for a, b in combinations(pairs, 2)
    )
    return original, source, intake, table, store, population, labels


def fake_engine(population):
    rows = [row["row"] for row in population.to_dict()["rows"] if not row["exclusions"]]
    return {
        "name": "dedupe",
        "version": "3.0.3",
        "model_sha256": hashlib.sha256(b"synthetic model").hexdigest(),
        "groups": [{"rows": [2, 3], "scores": [0.8, 0.8]}],
        "pairs": [{"rows": [2, 3], "score": 0.8}],
        "unclustered_rows": rows[2:],
    }


def test_complete_population_raw_states_and_borrower_only_fields(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _, source, _, table, store = prepare(
        tmp_path, ["00123", "N/A", 0, "", " ", "=1+1", "#N/A", "Bad\ufffd", "Other borrower"]
    )
    population = read_population(source, table, entity_scope(table), store.catalog(), (1,))
    data = population.to_dict()
    assert data["population"] == {"total": 10, "eligible": 2, "excluded": 8}
    assert data["rows"][0]["values"] == {"1": "00123"}
    assert {item["state"] for row in data["rows"] for item in row["exclusions"]} >= {
        "missing_token",
        "number",
        "whitespace_text",
        "formula",
        "error",
        "unreadable_or_unretained_text",
        "absent",
    }
    with pytest.raises(ValueError, match="borrower"):
        read_population(source, table, entity_scope(table), store.catalog(), (1, 2))


def test_reviewed_parent_is_explicit_and_preserves_raw(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _, source, _, table, store = prepare(tmp_path, ["CafÃ© Holdings", "Second borrower"])
    review = review_excel_text(source, table, 1, TextCleanupSettings(), store)
    approval = TransformationApproval(
        review.preview.id, ((2, 1),), "Reviewer", "Encoding repair", MOMENT
    )
    revision, _ = apply_excel_text(source, table, 1, TextCleanupSettings(), store, review, approval)
    original = read_population(source, table, review.scope, store.catalog(), (1,))
    cleaned = read_population(source, table, review.scope, store.catalog(), (1,), revision)
    assert original.to_dict()["rows"][0]["values"]["1"] == "CafÃ© Holdings"
    assert cleaned.to_dict()["rows"][0]["values"]["1"] == "Café Holdings"
    assert cleaned.to_dict()["snapshot"] == original.to_dict()["snapshot"]
    assert cleaned.to_dict()["parent_id"] == revision.id


@pytest.mark.parametrize("columns", [(), (1, 1), (True,), (2,), (3,)])
def test_feature_selections_are_explicit_and_typed(sample, columns):
    _, source, _, table, store, _, _ = sample
    snapshot = read_transformation_snapshot(source, table, entity_scope(table), store.catalog())
    with pytest.raises(ValueError):
        prepare_population(snapshot, columns)


def test_large_population_fails_before_read(sample, monkeypatch):
    _, source, _, table, store, _, _ = sample
    from loan_tape.ranges import parse_range

    table = replace(table, selection=replace(table.selection, area=parse_range("A1:B502")))
    monkeypatch.setattr(
        service,
        "read_transformation_snapshot",
        lambda *a, **kw: pytest.fail("Should fail before read"),
    )
    with pytest.raises(ValueError, match="500"):
        read_population(source, table, entity_scope(table), store.catalog(), (1,))


def test_labels_need_both_classes_current_rows_and_consistent_chains(sample):
    *_, population, labels = sample
    validate_labels(population, labels)
    for invalid in (
        labels[:12],
        labels + (labels[0],),
        labels + (PairLabel(100, 101, "match", "R", "Reason", MOMENT),),
        labels + (PairLabel(2, 5, "match", "R", "Reason", MOMENT),),
    ):
        with pytest.raises(ValueError):
            validate_labels(population, invalid)


@pytest.mark.parametrize("threshold", [0, 1, float("nan"), float("inf"), True, "0.5"])
def test_thresholds_are_explicit_finite_and_interior(threshold):
    with pytest.raises(ValueError):
        validate_threshold(threshold)


@pytest.mark.parametrize("change", ["source", "table", "mapping", "catalog"])
def test_guard_rejects_stale_source_meanings_or_scope(sample, change):
    _, source, _, table, store, population, _ = sample
    guard = population_guard(source, table, store, population, (1,), None)
    guard()
    if change == "source":
        source.write_bytes(source.read_bytes() + b"changed")
    elif change == "table":
        save_tables(
            TableSelections(
                table.selection.workbook_sha256, (replace(table, name="Changed"),), table.id
            )
        )
    elif change == "mapping":
        definition = entity_scope(table).definitions[0]
        save_column_definition(table, replace(definition, source_header="Changed"))
    else:
        store.deactivate("loan.text")
    with pytest.raises((ValueError, OSError)):
        guard()


def test_group_review_requires_every_decision_and_rejects_conflicting_labels(sample):
    *_, population, labels = sample
    engine = fake_engine(population)
    service.validate_engine(engine, set(range(2, 26)))
    run = EntityRun(bounded({"engine": engine, "labels": []}))
    group_id = engine["groups"][0]["id"]
    with pytest.raises(ValueError, match="each"):
        review_relationships(run, {}, "R", "Reason", MOMENT)
    output = json.loads(review_relationships(run, {group_id: "approve"}, "R", "Reason", MOMENT))
    assert output["relationships"][0]["source_rows"] == [2, 3]
    assert output["loan_rows_modified"] == 0
    run = EntityRun(
        bounded({"engine": engine, "labels": [{"left": 2, "right": 3, "label": "distinct"}]})
    )
    with pytest.raises(ValueError, match="contradicts"):
        review_relationships(run, {group_id: "approve"}, "R", "Reason", MOMENT)
    assert not json.loads(review_relationships(run, {group_id: "reject"}, "R", "Reason", MOMENT))[
        "relationships"
    ]


def test_atomic_publication_preserves_racing_output_and_rolls_back_own_output(tmp_path):
    target = tmp_path / "result.json"

    def competing():
        target.write_bytes(b"other result")

    with pytest.raises(FileExistsError):
        publish_bytes(target, b"new result", competing)
    assert target.read_bytes() == b"other result"
    second = tmp_path / "second.json"
    calls = 0

    def stale():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("stale")

    with pytest.raises(ValueError, match="stale"):
        publish_bytes(second, b"new result", stale)
    assert not second.exists() and not list(tmp_path.glob("*.tmp"))


def test_entity_staging_collision_preserves_existing_evidence(tmp_path, monkeypatch):
    target = tmp_path / "result.json"
    identity = SimpleNamespace(hex="a" * 32)
    staging = target.with_name(target.name + "." + identity.hex + ".tmp")
    staging.write_bytes(b"another writer's evidence")
    monkeypatch.setattr(service, "uuid4", lambda: identity)

    with pytest.raises(FileExistsError):
        publish_bytes(target, b"new result", lambda: None)

    assert staging.read_bytes() == b"another writer's evidence"
    assert not target.exists()


def test_failed_worker_or_final_guard_leaves_no_published_model(sample, monkeypatch, tmp_path):
    *_, population, labels = sample
    runtime = tmp_path / "runtime"
    (runtime / "Scripts").mkdir(parents=True)
    (runtime / "loan-tape-runtime.json").write_text('{"packages": []}')
    monkeypatch.setattr(service, "runtime_python", lambda _: runtime / "Scripts/python.exe")

    def worker(folder, *_):
        (folder / "model.bin").write_bytes(b"synthetic model")
        (folder / "result.json").write_text(json.dumps(fake_engine(population)))

    monkeypatch.setattr(service, "execute_worker", worker)
    calls = 0

    def guard():
        nonlocal calls
        calls += 1
        if calls == 5:
            raise ValueError("stale publication")

    with pytest.raises(ValueError, match="stale publication"):
        train_entities(population, labels, 0.5, True, guard)
    assert not list((tmp_path / ".artifacts/entity-matching").iterdir())
    event = Event()
    event.set()
    with pytest.raises((ValueError, OSError), match="cancel"):
        train_entities(population, labels, 0.5, True, lambda: None, cancelled=event)


def test_no_representative_attestation_or_runtime_does_not_run(sample, monkeypatch, tmp_path):
    *_, population, labels = sample
    monkeypatch.setattr(service, "execute_worker", lambda *a: pytest.fail("Do not start worker"))
    with pytest.raises(ValueError, match="Confirm"):
        train_entities(population, labels, 0.5, False, lambda: None)
    with pytest.raises(ValueError, match="Set up|Windows runtime"):
        service.runtime_python(tmp_path)


def test_changed_runtime_inventory_fails_before_import():
    from loan_tape.entity_worker import execute

    with pytest.raises(RuntimeError, match="packages changed"):
        execute({"runtime_packages": []}, Path.cwd())


def test_unreturned_pair_score_is_unknown_not_invented_zero(sample):
    *_, population, _ = sample
    engine = fake_engine(population)
    engine["pairs"][0].update(score=None, scoring_status="not_returned_by_dedupe")
    service.validate_engine(engine, set(range(2, 26)))
    assert engine["pairs"][0]["score"] is None
    engine["pairs"][0]["scoring_status"] = "scored"
    with pytest.raises(ValueError, match="score"):
        service.validate_engine(engine, set(range(2, 26)))
