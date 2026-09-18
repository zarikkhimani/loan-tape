"""Command-line entry point and launcher for desktop file intake."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from loan_tape import __version__


def main(argv: Sequence[str] | None = None) -> int:
    arguments_list = list(sys.argv[1:] if argv is None else argv)
    if arguments_list and arguments_list[0] == "packs":
        from loan_tape.pack_cli import main as packs_main

        return packs_main(arguments_list[1:])
    parser = argparse.ArgumentParser(
        prog="loan-tape",
        description="Source-preserving loan-tape normalization and validation.",
        epilog=(
            "File intake preserves sources. Column inspection and checks are available for saved Excel data sets; "
            "cleaning and financial validation are not implemented yet. "
            "Use 'loan-tape packs --help' for the independent dictionary pack catalog. "
            "See docs/ROADMAP.md for planned milestones."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--ui", action="store_true", help="Open the desktop drag-and-drop window.")
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=Path("inputs"),
        help="Keep session working copies here until Exit (default: ./inputs).",
    )
    arguments = parser.parse_args(argv)
    if arguments.ui:
        try:
            # Help/version and the core service work without loading a graphical display.
            from loan_tape.ui import launch

            return launch(arguments.storage_dir)
        except Exception as error:
            message = (
                f"Could not open Loan Tape: {error}\n\n"
                "Run setup.bat with Python 3.12 including Tcl/Tk, then try again."
            )
            if sys.stderr is not None:
                print(message, file=sys.stderr)
            if sys.platform == "win32":
                import ctypes

                ctypes.windll.user32.MessageBoxW(None, message, "Loan Tape", 0x10)
            return 1
    parser.print_help()
    return 0
