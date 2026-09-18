"""Install pinned tooling and the locked development environment inside this repository."""

import subprocess
import sys
import venv

from _support import ROOT, UV_VERSION, configure_process_environment, executable, run


def main() -> int:
    if sys.version_info[:2] != (3, 12):
        print(
            "Setup requires Python 3.12. Pass an existing Python 3.12 executable.", file=sys.stderr
        )
        return 1

    configure_process_environment()
    tools_directory = ROOT / ".tools"
    tools_python = executable(tools_directory, "python")
    if not tools_python.is_file():
        venv.EnvBuilder(with_pip=True).create(tools_directory)

    run(
        [
            tools_python,
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            f"uv=={UV_VERSION}",
        ]
    )
    run(
        [
            executable(tools_directory, "uv"),
            "sync",
            "--locked",
            "--python",
            sys.executable,
        ]
    )
    print("Setup complete. Run run.bat --help and check.bat on Windows.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"Setup failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
