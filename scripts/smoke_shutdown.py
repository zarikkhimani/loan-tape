"""Opt-in native close tests during real Excel and reader startup."""

from __future__ import annotations

import importlib
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import Any
from unittest.mock import patch

from openpyxl import Workbook  # type: ignore[import-untyped]

from loan_tape import excel_compare
from loan_tape.intake import IntakeStore
from loan_tape.ui import LoanTapeApp, create_root


def excel_pids() -> set[int]:
    client = importlib.import_module("win32com.client")
    locator = client.Dispatch("WbemScripting.SWbemLocator")
    service = locator.ConnectServer(".", "root\\cimv2")
    return {
        int(item.ProcessId)
        for item in service.ExecQuery("SELECT ProcessId FROM Win32_Process WHERE Name='EXCEL.EXE'")
    }


def main() -> None:
    existing = excel_pids()
    artifacts = Path.cwd() / ".artifacts"
    artifacts.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="shutdown-smoke-", dir=artifacts) as directory:
        work = Path(directory)
        path = work / "synthetic.xlsx"
        book = Workbook()
        book.active.append(["ID", "Amount"])
        book.active.append(["000123", 0])
        book.save(path)
        book.close()
        original = path.read_bytes()
        for stage in ("Excel startup", "reader startup"):
            root = create_root()
            root.withdraw()
            store = IntakeStore(work / stage / "inputs")
            record = store.save_path(path)
            app = LoanTapeApp(root, store)
            ready, release = Event(), Event()
            target = "start_excel" if stage == "Excel startup" else "start_in_job"
            original_start = getattr(excel_compare, target)

            def paused(
                *args: Any,
                start: Callable[..., tuple[Any, int]] = original_start,
                started: Event = ready,
                finish: Event = release,
            ) -> tuple[Any, int]:
                result = start(*args)
                started.set()
                if not finish.wait(10):
                    raise RuntimeError("Smoke test did not release startup")
                return result

            try:
                with patch.object(excel_compare, target, side_effect=paused):
                    app.inspect_file()
                    assert app.inspector is not None
                    app.root.withdraw()
                    deadline = time.monotonic() + 15
                    while not ready.is_set():
                        root.update()
                        if time.monotonic() > deadline:
                            raise RuntimeError(
                                "Excel startup was not reached during the smoke test"
                            )
                        time.sleep(0.01)
                    app.close()
                    assert app.closing and not app.closed
                    release.set()
                    while not app.closed:
                        root.update()
                        if time.monotonic() > deadline:
                            raise RuntimeError("App did not complete Excel shutdown")
                        time.sleep(0.01)
                assert not app.workers.active_names()
                assert excel_pids() == existing, "Excel process inventory changed"
                assert path.read_bytes() == original
                assert not Path(str(store.describe(record)["saved_path"])).exists()
                assert store.list_files() == []
                print(
                    f"{stage}: closing stopped owned work, reset session files, and left other Excel processes unchanged."
                )
            finally:
                release.set()
                if not app.closed:
                    app.close()
                    deadline = time.monotonic() + 10
                    while not app.closed and time.monotonic() < deadline:
                        root.update()
                        time.sleep(0.01)
        assert not list((artifacts / "excel-comparison").glob("read-*"))
    print("Real Excel shutdown smoke test passed; temporary copies removed.")


if __name__ == "__main__":
    main()
