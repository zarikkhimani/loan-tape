"""Install pinned tooling and the locked development environment inside this repository."""

import subprocess
import sys
import venv

from _support import ROOT, UV_VERSION, configure_process_environment, executable, run

# Reviewed wheel/hash from the Python security notice and PyPI release metadata:
# https://discuss.python.org/t/109576
# https://pypi.org/pypi/pip/26.2.2/json
# Python's ensurepip may seed an older pip with compromised CA trust. Its first
# download must verify this independent hash before installing or executing code.
PIP_BOOTSTRAP = (
    "pip @ https://files.pythonhosted.org/packages/3f/06/"
    "3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/"
    "pip-26.2.2-py3-none-any.whl"
    "#sha256=fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70"
)


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
            "--isolated",
            "--disable-pip-version-check",
            "install",
            "--no-index",
            "--no-deps",
            "--no-cache-dir",
            "--only-binary=:all:",
            "--require-hashes",
            PIP_BOOTSTRAP,
        ]
    )
    run(
        [
            tools_python,
            "-m",
            "pip",
            "--isolated",
            "--disable-pip-version-check",
            "install",
            "--no-cache-dir",
            "--index-url",
            "https://pypi.org/simple",
            "--only-binary=:all:",
            "--no-deps",
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
