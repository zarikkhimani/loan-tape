"""Run local quality checks and smoke-test a built wheel outside the source checkout."""

import argparse
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

from _distribution import check_distribution_contents
from _support import ROOT, executable, run


def check_packaged_resources(distributions: Path, wheel: Path) -> None:
    """Require exact reviewed runtime resources in both distribution artifacts."""
    sources = list(distributions.glob("*.tar.gz"))
    if len(sources) != 1:
        raise RuntimeError(f"Expected one source distribution, found {len(sources)}")
    resources = (
        "loan_tape/guidance/SIFMA_CALENDAR.md",
        "loan_tape/calendar_data/sifma_us_fixed_income.json",
        "loan_tape/profile_data/warehouse_model.json",
    )
    with zipfile.ZipFile(wheel) as archive, tarfile.open(sources[0], "r:gz") as source_archive:
        for relative in resources:
            expected = (ROOT / "src" / relative).read_bytes()
            if relative not in archive.namelist() or archive.read(relative) != expected:
                raise RuntimeError(f"Wheel is missing or has changed runtime resource: {relative}")
            matches = [
                name for name in source_archive.getnames() if name.endswith(f"/src/{relative}")
            ]
            if len(matches) != 1:
                raise RuntimeError(f"Source distribution is missing runtime resource: {relative}")
            content = source_archive.extractfile(matches[0])
            if content is None or content.read() != expected:
                raise RuntimeError(f"Source distribution has changed runtime resource: {relative}")
    print("Verified calendar and mapping-profile resources in both distributions.", flush=True)


def check_distributions(distributions: Path) -> Path:
    """Require an unambiguous artifact pair and inspect their actual saved contents."""
    wheels = list(distributions.glob("*.whl"))
    sources = list(distributions.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise RuntimeError(
            f"Expected one wheel and one source distribution, found {len(wheels)} and {len(sources)}"
        )
    check_distribution_contents(wheels[0], sources[0], ROOT)
    check_packaged_resources(distributions, wheels[0])
    return wheels[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--distributions",
        type=Path,
        help="Check one retained wheel/source archive pair only, without rerunning source checks.",
    )
    options = parser.parse_args()
    if options.distributions is not None:
        check_distributions(options.distributions.resolve())
        print("Retained distribution checks passed; source tests were not rerun.")
        return 0
    uv = executable(ROOT / ".tools", "uv")
    python = executable(ROOT / ".venv", "python")
    if not uv.is_file() or not python.is_file():
        print("Development environment is missing. Run setup.bat first.", file=sys.stderr)
        return 1

    run([uv, "lock", "--check", "--python", python])
    run([uv, "pip", "check", "--python", python])
    for arguments in (
        ["ruff", "format", "--check", "."],
        ["ruff", "check", "."],
        ["mypy"],
        ["pytest"],
        ["loan-tape", "--help"],
    ):
        run([uv, "run", "--locked", "--no-sync", *arguments])

    artifacts = ROOT / ".artifacts"
    artifacts.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wheel-check-", dir=artifacts) as temporary:
        work = Path(temporary)
        distributions = work / "dist"
        run([uv, "build", "--python", python, "--out-dir", distributions])
        wheel = check_distributions(distributions)
        smoke_environment = work / "installed"
        run([uv, "venv", "--python", python, smoke_environment])
        smoke_python = executable(smoke_environment, "python")
        runtime_requirements = work / "runtime-requirements.txt"
        run(
            [
                uv,
                "export",
                "--locked",
                "--no-dev",
                "--no-emit-project",
                "--output-file",
                runtime_requirements,
            ]
        )
        run(
            [
                uv,
                "pip",
                "install",
                "--python",
                smoke_python,
                "--require-hashes",
                "-r",
                runtime_requirements,
            ]
        )
        run([uv, "pip", "install", "--python", smoke_python, "--no-deps", wheel])
        run([uv, "pip", "check", "--python", smoke_python])
        run([smoke_python, "-I", "-m", "loan_tape", "--version"], cwd=work)
        run([executable(smoke_environment, "loan-tape"), "--help"], cwd=work)
        run([smoke_python, "-I", ROOT / "scripts" / "smoke_ui.py"], cwd=work)
        run([smoke_python, "-I", ROOT / "scripts" / "smoke_packs.py"], cwd=work)
        run([smoke_python, "-I", ROOT / "scripts" / "smoke_dates.py"], cwd=work)
        run([smoke_python, "-I", ROOT / "scripts" / "smoke_rates.py"], cwd=work)

    print("All checks passed, including the isolated installed-wheel smoke test.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        OSError,
        RuntimeError,
        subprocess.CalledProcessError,
        tarfile.TarError,
        zipfile.BadZipFile,
    ) as error:
        print(f"Validation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
