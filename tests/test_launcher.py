"""Windows shortcut, launcher, and owned-process exit integration."""

import importlib
import runpy
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest

from loan_tape.excel_process import start_in_job

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows desktop integration")


def test_shortcut_target_and_non_overwrite_policy(tmp_path):
    create = runpy.run_path(str(ROOT / "scripts/create_launcher.py"))["create_shortcut"]
    path = tmp_path / "Loan Tape.lnk"
    assert create(path) == path
    client = importlib.import_module("win32com.client")
    shortcut = client.Dispatch("WScript.Shell").CreateShortcut(str(path))
    assert Path(shortcut.TargetPath) == ROOT / ".venv/Scripts/pythonw.exe"
    assert shortcut.Arguments == subprocess.list2cmdline(
        ["-I", str(ROOT / "scripts/launch_desktop.py")]
    )
    assert Path(shortcut.WorkingDirectory) == ROOT
    create(path)  # Recreating this project's own shortcut is allowed.
    shortcut.TargetPath = str(ROOT / "start-ui.bat")
    shortcut.Save()
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="unrelated"):
        create(path)
    assert path.read_bytes() == before


def test_windowless_launcher_from_another_folder_exits_all_its_processes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    jobs = importlib.import_module("win32job")
    gui = importlib.import_module("win32gui")
    processes = importlib.import_module("win32process")
    events = importlib.import_module("win32event")
    job = jobs.CreateJobObject(None, "LoanTapeLauncherTest-" + uuid4().hex)
    before = set((ROOT / ".artifacts/sessions").glob("*.json"))
    process = None
    try:
        process, _ = start_in_job(
            str(ROOT / ".venv/Scripts/pythonw.exe"),
            [
                "-I",
                str(ROOT / "scripts/launch_desktop.py"),
                "--storage-dir",
                str(tmp_path / "inputs"),
            ],
            job,
        )
        deadline = time.monotonic() + 10
        windows = []
        while not windows:
            owned = set(jobs.QueryInformationJobObject(job, jobs.JobObjectBasicProcessIdList))

            def find(hwnd, unused, owned=owned):
                if (
                    processes.GetWindowThreadProcessId(hwnd)[1] in owned
                    and gui.GetWindowText(hwnd) == "Loan Tape"
                    and gui.GetClassName(hwnd) == "TkTopLevel"
                ):
                    windows.append(hwnd)

            gui.EnumWindows(find, None)
            assert time.monotonic() < deadline, "Launcher did not open its desktop window"
            time.sleep(0.05)
        gui.PostMessage(windows[0], 0x0010, 0, 0)  # WM_CLOSE, only our job's main window.
        assert events.WaitForSingleObject(process, 10000) == 0, (
            "Launcher process remained after close"
        )
        assert processes.GetExitCodeProcess(process) == 0
        assert (
            jobs.QueryInformationJobObject(job, jobs.JobObjectBasicAccountingInformation)[
                "ActiveProcesses"
            ]
            == 0
        )
        assert set((ROOT / ".artifacts/sessions").glob("*.json")) == before
        assert not (tmp_path / ".artifacts").exists(), (
            "Launcher used the caller's working directory"
        )
    finally:
        jobs.TerminateJobObject(job, 1)
        if process is not None:
            events.WaitForSingleObject(process, 5000)
            process.Close()
        job.Close()


def test_process_cannot_run_before_job_assignment(tmp_path, monkeypatch):
    jobs = importlib.import_module("win32job")
    job = jobs.CreateJobObject(None, "LoanTapeFailedAssign-" + uuid4().hex)
    marker = tmp_path / "must-not-exist.txt"

    def refuse(*args):
        raise RuntimeError("Simulated assignment failure")

    monkeypatch.setattr(jobs, "AssignProcessToJobObject", refuse)
    try:
        with pytest.raises(RuntimeError, match="assignment failure"):
            start_in_job(
                sys.executable,
                [
                    "-c",
                    "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('ran')",
                    str(marker),
                ],
                job,
            )
        assert not marker.exists()
    finally:
        job.Close()
