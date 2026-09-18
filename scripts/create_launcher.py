"""Create a per-user Loan Tape desktop shortcut without changing system settings."""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def create_shortcut(destination: Path | None = None) -> Path:
    if sys.platform != "win32":
        raise RuntimeError("The desktop shortcut is for Windows. Use --ui on other systems.")
    python = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    launcher = ROOT / "scripts" / "launch_desktop.py"
    if not python.is_file() or not launcher.is_file():
        raise RuntimeError("The project environment or launcher is missing. Run setup.bat first.")
    client = importlib.import_module("win32com.client")
    shell = client.Dispatch("WScript.Shell")
    path = destination or Path(shell.SpecialFolders("Desktop")) / "Loan Tape.lnk"
    if not path.parent.is_dir() or path.suffix.lower() != ".lnk":
        raise RuntimeError("Choose an existing folder and a .lnk shortcut filename.")
    arguments = subprocess.list2cmdline(["-I", str(launcher)])
    shortcut = shell.CreateShortcut(str(path))
    if path.exists() and (
        Path(shortcut.TargetPath).resolve() != python.resolve() or shortcut.Arguments != arguments
    ):
        raise RuntimeError(
            f"An unrelated shortcut already exists at {path}; it was left unchanged."
        )
    shortcut.TargetPath = str(python)
    shortcut.Arguments = arguments
    shortcut.WorkingDirectory = str(ROOT)
    shortcut.Description = "Open Loan Tape - local CSV and Excel inspection"
    shortcut.IconLocation = str(python) + ",0"
    shortcut.WindowStyle = 1
    shortcut.Save()
    return path


if __name__ == "__main__":
    try:
        print(f"Desktop launcher ready: {create_shortcut()}")
    except Exception as error:
        print(f"Could not create the launcher: {error}", file=sys.stderr)
        raise SystemExit(1) from error
