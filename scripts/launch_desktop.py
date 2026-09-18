"""Windowless entry point used by the Loan Tape desktop shortcut."""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    try:
        # Keep saved selections, sessions, and temporary work in this project even
        # when Explorer or a shortcut starts us from a different directory.
        os.chdir(ROOT)
        from loan_tape.cli import main as run

        return run(["--ui", "--storage-dir", str(ROOT / "inputs"), *sys.argv[1:]])
    except Exception as error:
        message = f"Could not start Loan Tape: {error}\n\nRun setup.bat in {ROOT}, then try again."
        if sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(None, message, "Loan Tape", 0x10)
        elif sys.stderr is not None:
            print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
