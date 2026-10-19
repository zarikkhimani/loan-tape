"""Prepare the optional Windows/Python 3.12 matcher without installing host tools."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import UTC, datetime

from _support import ROOT, executable, project_environment
from probe_canonicalization import inventory

TOOLCHAIN = "llvm-mingw-20260616-ucrt-x86_64"
SHA256 = "b9b68a4d276e16fa25802aaba458e4638f64b3884c290aaccdc2d87083b6ca35"
URL = f"https://github.com/mstorsjo/llvm-mingw/releases/download/20260616/{TOOLCHAIN}.zip"


def prepare_compiler(environment: dict[str, str]) -> dict[str, str]:
    folder = ROOT / ".tools" / "phase7-toolchain"
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / f"{TOOLCHAIN}.zip"
    if not archive.exists():
        staging = archive.with_suffix(".download")
        try:
            print("Downloading the pinned portable compiler into .tools...", flush=True)
            with urllib.request.urlopen(URL, timeout=60) as source, staging.open("wb") as output:
                shutil.copyfileobj(source, output)
            staging.rename(archive)
        finally:
            staging.unlink(missing_ok=True)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError("Portable compiler checksum mismatch. Remove the damaged archive.")
    target = folder / TOOLCHAIN
    marker = target / ".loan-tape-complete"
    if not marker.exists():
        with zipfile.ZipFile(archive) as package:
            for member in package.infolist():
                if not (folder / member.filename).resolve().is_relative_to(target.resolve()):
                    raise RuntimeError("Unsafe compiler archive path.")
            package.extractall(folder)
        marker.write_text(SHA256, encoding="ascii")
    elif marker.read_text(encoding="ascii") != SHA256:
        raise RuntimeError("Unexpected portable compiler version.")
    config = folder / "build.cfg"
    config.write_text("[build_ext]\ncompiler=mingw32\n", encoding="utf-8")
    result = dict(environment)
    result.update(
        PATH=str(target / "bin") + os.pathsep + environment.get("PATH", ""),
        DIST_EXTRA_CONFIG=str(config),
        CC="clang",
        CXX="clang++",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--portable-compiler",
        action="store_true",
        help="Download/use the pinned portable compiler inside .tools.",
    )
    options = parser.parse_args()
    if sys.platform != "win32" or sys.version_info[:2] != (3, 12):
        raise RuntimeError("This verified optional runtime requires Windows and Python 3.12.")
    environment = project_environment()
    environment.pop("VIRTUAL_ENV", None)
    primary = executable(ROOT / ".venv", "python")
    before = inventory(primary, environment)
    runtime = ROOT / ".tools" / "entity-matching"
    runtime.mkdir(parents=True, exist_ok=True)
    report_path = runtime / "loan-tape-runtime.json"
    report_path.unlink(missing_ok=True)
    report: dict[str, object] = {
        "status": "failed",
        "started_at_utc": datetime.now(UTC).isoformat(),
    }
    try:
        if options.portable_compiler:
            environment = prepare_compiler(environment)
            report["compiler"] = {"url": URL, "sha256": SHA256, "source_patches": False}
        environment["UV_PROJECT_ENVIRONMENT"] = str(runtime)
        environment["UV_LINK_MODE"] = "copy"
        for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
            environment[key] = "1"
        uv = executable(ROOT / ".tools", "uv")
        if not (runtime / "pyvenv.cfg").exists():
            subprocess.run(
                [str(uv), "venv", "--allow-existing", "--python", str(primary), str(runtime)],
                cwd=ROOT,
                env=environment,
                check=True,
                timeout=60,
            )
        for name, command in (
            (
                "install",
                [
                    str(uv),
                    "sync",
                    "--locked",
                    "--no-default-groups",
                    "--group",
                    "entity-matching",
                    "--no-install-project",
                    "--python",
                    str(primary),
                ],
            ),
            (
                "dependencies",
                [str(uv), "pip", "check", "--python", str(executable(runtime, "python"))],
            ),
            (
                "training",
                [
                    str(executable(runtime, "python")),
                    "-I",
                    str(ROOT / "scripts/_canonicalization_cases.py"),
                    str(runtime),
                    "dedupe",
                ],
            ),
        ):
            print(f"Entity runtime: {name}", flush=True)
            with (runtime / f"setup-{name}.log").open("w", encoding="utf-8") as log:
                subprocess.run(
                    command,
                    cwd=ROOT,
                    env=environment,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=True,
                    timeout=300,
                )
        report["packages"] = inventory(executable(runtime, "python"), environment)
        report["cases"] = json.loads((runtime / "cases.json").read_text(encoding="utf-8"))
        report["lock_sha256"] = hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest()
        report["status"] = "passed"
    finally:
        report["primary_environment_unchanged"] = before == inventory(primary, environment)
        if not report["primary_environment_unchanged"]:
            report["status"] = "failed"
        report["finished_at_utc"] = datetime.now(UTC).isoformat()
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Runtime report: {report_path}", flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Entity runtime setup failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
