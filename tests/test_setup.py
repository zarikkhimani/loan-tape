"""Setup must repair bootstrap certificate trust before using a package index."""

import importlib
import subprocess
import tomllib
from pathlib import Path

import pytest


@pytest.fixture
def setup_module(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    module = importlib.import_module("setup")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "configure_process_environment", lambda: None)
    return module


@pytest.mark.parametrize("existing", [False, True])
def test_secure_bootstrap_precedes_index_downloads(setup_module, monkeypatch, existing):
    module = setup_module
    tools = module.ROOT / ".tools"
    python = module.executable(tools, "python")
    created = []
    commands = []

    def create_environment(path):
        created.append(path)
        python.parent.mkdir(parents=True)
        python.touch()

    if existing:
        create_environment(tools)
        created.clear()

    class Builder:
        def __init__(self, *, with_pip):
            assert with_pip is True

        def create(self, path):
            create_environment(path)

    monkeypatch.setattr(module.venv, "EnvBuilder", Builder)
    monkeypatch.setattr(module, "run", lambda command: commands.append(command))
    assert module.main() == 0
    assert created == ([] if existing else [tools])
    assert len(commands) == 3
    bootstrap, uv_install, sync = commands
    assert bootstrap[:3] == [python, "-m", "pip"]
    assert {
        "--isolated",
        "--disable-pip-version-check",
        "--no-index",
        "--no-deps",
        "--no-cache-dir",
        "--only-binary=:all:",
        "--require-hashes",
    }.issubset(bootstrap)
    assert bootstrap[-1].startswith("pip @ https://files.pythonhosted.org/")
    assert bootstrap[-1].endswith(
        "#sha256=fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70"
    )
    assert uv_install[:3] == [python, "-m", "pip"]
    assert f"uv=={module.UV_VERSION}" in uv_install
    assert sync[:3] == [module.executable(tools, "uv"), "sync", "--locked"]


def test_failed_bootstrap_stops_before_uv_or_sync(setup_module, monkeypatch):
    module = setup_module
    python = module.executable(module.ROOT / ".tools", "python")
    python.parent.mkdir(parents=True)
    python.touch()
    commands = []

    def reject_download(command):
        commands.append(command)
        raise subprocess.CalledProcessError(1, command, stderr="Hash mismatch")

    monkeypatch.setattr(module, "run", reject_download)
    with pytest.raises(subprocess.CalledProcessError):
        module.main()
    assert len(commands) == 1
    assert commands[0][-1] == module.PIP_BOOTSTRAP


def test_uv_tool_and_build_backend_pins_agree():
    root = Path(__file__).resolve().parents[1]
    version = (root / ".uv-version").read_text(encoding="utf-8").strip()
    with (root / "pyproject.toml").open("rb") as source:
        project = tomllib.load(source)
    assert project["tool"]["uv"]["required-version"] == f"=={version}"
    assert project["build-system"]["requires"] == [f"uv_build=={version}"]
