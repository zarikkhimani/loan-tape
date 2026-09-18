"""Shared helpers for repository-local setup and validation."""

import ctypes
import hashlib
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UV_VERSION = (ROOT / ".uv-version").read_text(encoding="utf-8").strip()


def executable(environment: Path, name: str) -> Path:
    if os.name == "nt":
        return environment / "Scripts" / f"{name}.exe"
    return environment / "bin" / name


def project_environment() -> dict[str, str]:
    """Keep tool storage local, separating account-private pytest directories."""
    environment = os.environ.copy()
    user_key = execution_user_key()
    temporary = ROOT / ".cache" / "tmp" / user_key
    temporary.mkdir(parents=True, exist_ok=True)
    for name in ("TEMP", "TMP", "TMPDIR", "PYTEST_DEBUG_TEMPROOT"):
        environment[name] = str(temporary)
    environment["LOAN_TAPE_TEST_USER"] = user_key
    environment["UV_CACHE_DIR"] = str(ROOT / ".cache" / "uv")
    environment["PIP_CACHE_DIR"] = str(ROOT / ".cache" / "pip")
    environment["RUFF_CACHE_DIR"] = str(ROOT / ".cache" / "ruff")
    environment["MYPY_CACHE_DIR"] = str(ROOT / ".cache" / "mypy")
    environment["UV_PROJECT_ENVIRONMENT"] = str(ROOT / ".venv")
    environment["UV_PYTHON_DOWNLOADS"] = "never"
    environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return environment


def execution_user_key() -> str:
    """Use the executing account, not a username inherited from another account."""
    if sys.platform != "win32":
        return f"uid-{os.getuid()}"
    # Windows sandboxes may inherit USERNAME/USERPROFILE from the interactive user.
    # GetUserNameW reads the actual thread identity (UNLEN is 256).
    name = ctypes.create_unicode_buffer(257)
    size = ctypes.c_ulong(len(name))
    if not ctypes.windll.advapi32.GetUserNameW(name, ctypes.byref(size)):
        raise ctypes.WinError()
    return hashlib.sha256(name.value.casefold().encode("utf-8")).hexdigest()[:16]


def configure_process_environment() -> None:
    """Apply storage settings before setup or pytest creates in-process temp files."""
    environment = project_environment()
    os.environ.update(environment)
    # tempfile can have cached the original Windows temp path before this runs.
    tempfile.tempdir = environment["TEMP"]


def run(arguments: Sequence[str | Path], *, cwd: Path = ROOT) -> None:
    command = [str(argument) for argument in arguments]
    print(f"Running: {subprocess.list2cmdline(command)}", flush=True)
    subprocess.run(command, cwd=cwd, env=project_environment(), check=True)
