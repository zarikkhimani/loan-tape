"""Run the optional Phase 1 probes in an isolated, locked Python 3.12 environment."""

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from _support import ROOT, executable, project_environment

INVENTORY_CODE = (
    "import importlib.metadata as m,json; "
    "print(json.dumps(sorted((d.metadata['Name'].lower(),d.version) for d in m.distributions())))"
)


def inventory(python: Path, environment: dict[str, str]) -> object:
    result = subprocess.run(
        [str(python), "-I", "-c", INVENTORY_CODE],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return json.loads(result.stdout)


def run_step(command: list[str], label: str, folder: Path, environment: dict[str, str]) -> None:
    print(f"Canonicalization probe: {label}", flush=True)
    with (folder / f"{label}.log").open("w", encoding="utf-8") as log:
        subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=300,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dedupe-source-build",
        action="store_true",
        help="Explicitly attempt Dedupe source builds using existing tools; installs no host tools.",
    )
    options = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("The compatibility probe requires the project's Python 3.12.")
    uv = executable(ROOT / ".tools", "uv")
    primary = executable(ROOT / ".venv", "python")
    if not uv.is_file() or not primary.is_file():
        raise RuntimeError("Run setup.bat before running this probe.")

    environment = project_environment()
    environment.pop("VIRTUAL_ENV", None)
    environment["PYTHONUTF8"] = "1"
    environment["OMP_NUM_THREADS"] = "1"
    environment["OPENBLAS_NUM_THREADS"] = "1"
    environment["MKL_NUM_THREADS"] = "1"
    # Probe model artifacts and caches stay under the repository, even in child libraries.
    folder = (
        ROOT
        / ".artifacts"
        / "canonicalization-phase1"
        / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    )
    folder.mkdir(parents=True)
    baseline = inventory(primary, environment)
    fingerprints = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in (
            "pyproject.toml",
            "uv.lock",
            "scripts/probe_canonicalization.py",
            "scripts/_canonicalization_cases.py",
        )
    }
    report: dict[str, object] = {
        "schema_version": 1,
        "started_at_utc": datetime.now(UTC).isoformat(),
        "source_fingerprints": fingerprints,
        "dedupe_source_build": options.dedupe_source_build,
        "primary_packages_before": baseline,
        "status": "failed",
    }
    try:
        run_step(
            [str(uv), "lock", "--check", "--python", str(primary)],
            "lock-check",
            folder,
            environment,
        )
        profiles: list[dict[str, object]] = []
        report["profiles"] = profiles
        for profile, group in (
            ("base", "canonicalization-probe"),
            ("dedupe", "canonicalization-dedupe-probe"),
        ):
            probe_environment = ROOT / ".tools" / group
            environment["UV_PROJECT_ENVIRONMENT"] = str(probe_environment)
            work = folder / profile
            work.mkdir()
            outcome: dict[str, object] = {
                "profile": profile,
                "dependency_group": group,
                "environment": probe_environment.relative_to(ROOT).as_posix(),
                "status": "failed",
            }
            profiles.append(outcome)
            stage = "install"
            try:
                command = [
                    str(uv),
                    "sync",
                    "--locked",
                    "--no-default-groups",
                    "--group",
                    group,
                    "--no-install-project",
                    "--python",
                    str(primary),
                ]
                if profile != "dedupe" or not options.dedupe_source_build:
                    command.append("--no-build")
                run_step(command, stage, work, environment)
                probe_python = executable(probe_environment, "python")
                stage = "dependency-check"
                run_step(
                    [str(uv), "pip", "check", "--python", str(probe_python)],
                    stage,
                    work,
                    environment,
                )
                stage = "synthetic-cases"
                run_step(
                    [
                        str(probe_python),
                        "-I",
                        str(ROOT / "scripts" / "_canonicalization_cases.py"),
                        str(work),
                        profile,
                    ],
                    stage,
                    work,
                    environment,
                )
                outcome["status"] = "passed"
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                outcome["failed_stage"] = stage
                outcome["error"] = f"{type(error).__name__}: {error}"
                log = work / f"{stage}.log"
                outcome["log"] = log.relative_to(folder).as_posix()
                if log.is_file():
                    with log.open("rb") as stream:
                        stream.seek(max(0, log.stat().st_size - 8192))
                        outcome["log_tail"] = stream.read().decode("utf-8", errors="replace")
            cases = work / "cases.json"
            if cases.is_file():
                outcome["cases"] = json.loads(cases.read_text(encoding="utf-8"))
            print(f"{profile}: {outcome['status']}", flush=True)
        if all(profile["status"] == "passed" for profile in profiles):
            report["status"] = "passed"
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        after = inventory(primary, environment)
        report["primary_packages_after"] = after
        report["primary_environment_unchanged"] = after == baseline
        report["inputs_unchanged"] = all(
            hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == fingerprint
            for name, fingerprint in fingerprints.items()
        )
        if not report["primary_environment_unchanged"] or not report["inputs_unchanged"]:
            report["status"] = "failed"
        report["finished_at_utc"] = datetime.now(UTC).isoformat()
        (folder / "report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"Report: {folder / 'report.json'}", flush=True)
        print(f"Result: {report['status']}", flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Compatibility probe failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
