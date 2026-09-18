"""Run a development command with the locked environment and project-local storage."""

import subprocess
import sys

from _support import ROOT, executable, run


def main() -> int:
    if len(sys.argv) == 1:
        print("Usage: dev.bat <command> [arguments] (for example: dev.bat pytest -q)")
        return 1
    uv = executable(ROOT / ".tools", "uv")
    if not uv.is_file() or not executable(ROOT / ".venv", "python").is_file():
        print("Development environment is missing. Run setup.bat first.", file=sys.stderr)
        return 1
    run([uv, "run", "--locked", "--no-sync", *sys.argv[1:]])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode) from error
    except OSError as error:
        print(f"Development command failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
