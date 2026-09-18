"""Development commands must work without access to the caller's temp folders."""

import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def support(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    return importlib.import_module("_support")


def test_child_uses_local_storage_despite_inherited_paths(tmp_path, monkeypatch, support):
    project = tmp_path / "project with spaces"
    monkeypatch.setattr(support, "ROOT", project)
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("Do not touch", encoding="utf-8")
    for key in ("TEMP", "TMP", "TMPDIR", "PYTEST_DEBUG_TEMPROOT", "UV_CACHE_DIR"):
        monkeypatch.setenv(key, str(blocked))
    before = os.environ.copy()
    environment = support.project_environment()
    assert os.environ == before
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, os, tempfile; "
            "from pathlib import Path; "
            "work = tempfile.TemporaryDirectory(); "
            "Path(work.name, 'probe').write_text('ok'); "
            "print(json.dumps({'temporary': work.name, "
            "'cache': {key: os.environ[key] for key in "
            "('UV_CACHE_DIR', 'PIP_CACHE_DIR', 'RUFF_CACHE_DIR', 'MYPY_CACHE_DIR')}})); "
            "work.cleanup()",
        ],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    observed = json.loads(result.stdout)
    assert Path(observed["temporary"]).is_relative_to(project / ".cache")
    assert not Path(observed["temporary"]).exists()
    assert all(
        Path(value).is_relative_to(project / ".cache") for value in observed["cache"].values()
    )
    assert blocked.read_text(encoding="utf-8") == "Do not touch"


def test_invalid_local_storage_fails_without_fallback(tmp_path, monkeypatch, support):
    monkeypatch.setattr(support, "ROOT", tmp_path)
    (tmp_path / ".cache").write_text("Blocked storage", encoding="utf-8")
    with pytest.raises(OSError):
        support.project_environment()


def test_storage_identity_ignores_inherited_username(monkeypatch, support):
    original = support.execution_user_key()
    for key in ("USERNAME", "USER", "LOGNAME"):
        monkeypatch.setenv(key, "another-account")
    assert support.execution_user_key() == original


def test_direct_concurrent_pytest_keeps_cache_and_temp_local(tmp_path):
    project = tmp_path / "isolated project"
    for relative in ("tests/conftest.py", "scripts/_support.py", ".uv-version", "pyproject.toml"):
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    probe = project / "tests/test_storage.py"
    probe.write_text(
        "import json, os, tempfile\n"
        "from pathlib import Path\n"
        "def test_storage(tmp_path, request):\n"
        "    root = Path(__file__).resolve().parents[1]\n"
        "    assert tmp_path.is_relative_to(root / '.cache')\n"
        "    assert Path(tempfile.gettempdir()).is_relative_to(root / '.cache')\n"
        "    key = f'probe/storage-{os.getpid()}'\n"
        "    request.config.cache.set(key, 'kept')\n"
        "    assert request.config.cache.get(key, None) == 'kept'\n"
        "    report = {'tmp': str(tmp_path), 'tempfile': tempfile.gettempdir()}\n"
        "    Path(os.environ['STORAGE_REPORT']).write_text(json.dumps(report))\n",
        encoding="utf-8",
    )
    blocked = tmp_path / "blocked-temp"
    blocked.write_text("Not a directory", encoding="utf-8")
    environment = os.environ.copy()
    for key in ("TEMP", "TMP", "TMPDIR", "PYTEST_DEBUG_TEMPROOT"):
        environment[key] = str(blocked)
    environment.pop("LOAN_TAPE_TEST_USER", None)
    processes = []
    reports = [tmp_path / f"report-{index}.json" for index in range(2)]
    try:
        for report in reports:
            processes.append(
                subprocess.Popen(
                    [sys.executable, "-m", "pytest", str(probe), "-q", "-W", "error"],
                    cwd=tmp_path,
                    env={**environment, "STORAGE_REPORT": str(report)},
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            )
        for process in processes:
            output, _ = process.communicate(timeout=40)
            assert process.returncode == 0, output
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()
    observed = [json.loads(report.read_text(encoding="utf-8")) for report in reports]
    assert observed[0]["tmp"] != observed[1]["tmp"]
    assert all(Path(report["tmp"]).is_relative_to(project / ".cache") for report in observed)
    assert len(list((project / ".cache/pytest").glob("*/v/probe/storage-*"))) == 2
    assert not (project / ".pytest_cache").exists()
