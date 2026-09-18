"""Locate desktop Excel and launch manual windows or owned background readers."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from loan_tape.inspection import InspectionError


def start_in_job(executable: str, arguments: list[str], job: Any) -> tuple[Any, int]:
    api = importlib.import_module("win32process")
    jobs = importlib.import_module("win32job")
    events = importlib.import_module("win32event")
    startup = api.STARTUPINFO()
    startup.dwFlags = 1  # STARTF_USESHOWWINDOW
    startup.wShowWindow = 0  # SW_HIDE
    process, thread, pid, _ = api.CreateProcess(
        executable,
        subprocess.list2cmdline([executable, *arguments]),
        None,
        None,
        False,
        0x00000004 | 0x08000000,  # CREATE_SUSPENDED | CREATE_NO_WINDOW
        None,
        None,
        startup,
    )
    try:
        jobs.AssignProcessToJobObject(job, process)
        api.ResumeThread(thread)
        return process, int(pid)
    except BaseException:
        api.TerminateProcess(process, 1)
        events.WaitForSingleObject(process, 5000)
        process.Close()
        raise
    finally:
        thread.Close()


def excel_executable() -> str:
    registry = importlib.import_module("winreg")
    key_name = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe"
    for hive in (registry.HKEY_CURRENT_USER, registry.HKEY_LOCAL_MACHINE):
        for view in (registry.KEY_WOW64_64KEY, registry.KEY_WOW64_32KEY):
            try:
                with registry.OpenKey(hive, key_name, 0, registry.KEY_READ | view) as key:
                    value, _ = registry.QueryValueEx(key, None)
                path = Path(str(value).strip('"'))
                if path.is_file() and path.name.lower() == "excel.exe":
                    return str(path)
            except FileNotFoundError:
                continue
    raise InspectionError("Desktop Excel is not registered on this computer.")


def start_excel(job: Any) -> tuple[Any, int]:
    # No workbook is passed here. The reader establishes inspection settings first.
    return start_in_job(excel_executable(), ["/x", "/automation"], job)


def open_in_excel(path: Path) -> None:
    """Hand this saved file to visible Excel; ownership stays with the user."""
    if sys.platform != "win32":
        raise OSError("Open in Excel requires Windows and desktop Microsoft Excel.")
    if not path.is_file():
        raise FileNotFoundError("The saved data file could not be found. Add the file again.")
    # Launch Excel explicitly, including for CSV files with a different default app.
    # ShellExecute opens the normal application without a terminal or a reader job.
    os.startfile(excel_executable(), "open", subprocess.list2cmdline([str(path.resolve())]))
