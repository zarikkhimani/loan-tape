"""Optional probes must isolate installs and report failures without hiding them."""

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def probe(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    module = importlib.import_module("probe_canonicalization")
    root = tmp_path / "project"
    root.mkdir()
    for name in (
        "pyproject.toml",
        "uv.lock",
        "scripts/probe_canonicalization.py",
        "scripts/_canonicalization_cases.py",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic input\n", encoding="utf-8")
    for environment, name in ((".tools", "uv"), (".venv", "python")):
        path = module.executable(root / environment, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "project_environment", lambda: {"VIRTUAL_ENV": str(root / ".venv")})
    monkeypatch.setattr(module, "inventory", lambda *_: [["synthetic", "1.0"]])
    monkeypatch.setattr(sys, "argv", ["probe_canonicalization.py"])
    return module, root


def report(root):
    paths = list((root / ".artifacts" / "canonicalization-phase1").glob("*/report.json"))
    assert len(paths) == 1
    return json.loads(paths[0].read_text(encoding="utf-8"))


def test_probe_installs_only_in_separate_environments_and_checks_locked_inputs(probe, monkeypatch):
    module, root = probe
    commands = []

    def run(command, label, folder, environment):
        commands.append((command, label, dict(environment)))

    monkeypatch.setattr(module, "run_step", run)
    assert module.main() == 0
    installs = [
        (command, environment) for command, label, environment in commands if label == "install"
    ]
    assert len(installs) == 2
    for command, environment in installs:
        assert "--locked" in command and "--no-default-groups" in command
        assert "--no-install-project" in command and "--no-build" in command
        assert "VIRTUAL_ENV" not in environment
        target = Path(environment["UV_PROJECT_ENVIRONMENT"])
        assert target.parent == root / ".tools"
        assert target != root / ".venv"
    outcome = report(root)
    assert outcome["primary_environment_unchanged"] is True
    assert outcome["inputs_unchanged"] is True


@pytest.mark.parametrize("failed_profile", ["base", "dedupe"])
def test_profile_install_failure_is_nonzero_visible_and_does_not_stop_other_profile(
    probe, monkeypatch, failed_profile
):
    module, root = probe
    executed = []

    def run(command, label, folder, environment):
        executed.append((folder.name, label))
        if folder.name == failed_profile and label == "install":
            (folder / "install.log").write_text("Synthetic native compiler unavailable\n")
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(module, "run_step", run)
    assert module.main() == 1
    profiles = report(root)["profiles"]
    failed = next(profile for profile in profiles if profile["profile"] == failed_profile)
    passed = next(profile for profile in profiles if profile["profile"] != failed_profile)
    assert failed["status"] == "failed" and failed["failed_stage"] == "install"
    assert "Synthetic native compiler unavailable" in failed["log_tail"]
    assert passed["status"] == "passed"
    assert (passed["profile"], "synthetic-cases") in executed


def test_source_builds_are_explicit_and_apply_only_to_dedupe(probe, monkeypatch):
    module, _ = probe
    monkeypatch.setattr(sys, "argv", ["probe_canonicalization.py", "--dedupe-source-build"])
    installs = {}

    def run(command, label, folder, environment):
        if label == "install":
            installs[folder.name] = command

    monkeypatch.setattr(module, "run_step", run)
    assert module.main() == 0
    assert "--no-build" in installs["base"]
    assert "--no-build" not in installs["dedupe"]


@pytest.mark.parametrize("changed", ["primary", "inputs"])
def test_environment_or_input_change_invalidates_an_otherwise_successful_probe(
    probe, monkeypatch, changed
):
    module, root = probe
    inventories = iter([[["synthetic", "1.0"]], [["synthetic", "2.0"]]])
    if changed == "primary":
        monkeypatch.setattr(module, "inventory", lambda *_: next(inventories))

    def run(command, label, folder, environment):
        if changed == "inputs" and label == "lock-check":
            (root / "uv.lock").write_text("changed input\n")

    monkeypatch.setattr(module, "run_step", run)
    assert module.main() == 1
    outcome = report(root)
    assert outcome["status"] == "failed"
    key = "primary_environment_unchanged" if changed == "primary" else "inputs_unchanged"
    assert outcome[key] is False
