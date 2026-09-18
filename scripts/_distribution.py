"""Inspect release archive paths without extracting or executing their contents."""

import tarfile
import zipfile
from pathlib import Path, PurePosixPath

PRIVATE_DIRECTORIES = frozenset(
    {
        ".git",
        ".agents",
        ".codex",
        ".cache",
        ".tools",
        ".venv",
        ".artifacts",
        ".history",
        ".local",
        "inputs",
        "outputs",
        "data",
        "corpus",
        "runs",
        "__pycache__",
    }
)
PRIVATE_SUFFIXES = frozenset({".log", ".pem", ".key", ".pfx", ".p12", ".pyc", ".pyo"})
SOURCE_SUFFIXES = frozenset(
    {".csv", ".tsv", ".xml", ".parquet", ".xlsx", ".xlsm", ".xlsb", ".xls", ".pdf"}
)
REQUIRED_SOURCE_GUIDES = (
    "LICENSE",
    "SECURITY.md",
    "docs/OPERATIONS.md",
    "docs/RELEASING.md",
)


def check_member_path(name: str, *, source: bool) -> str:
    """Return an archive-relative name after rejecting private or unsafe paths."""
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or "\\" in name
        or ":" in name
        or any(part == ".." for part in path.parts)
        or any(ord(character) < 32 for character in name)
    ):
        raise RuntimeError(f"Unsafe distribution member: {name!r}")
    parts = path.parts[1:] if source else path.parts
    lowered = tuple(part.lower() for part in parts)
    if not parts:
        return ""
    leaf = lowered[-1]
    if (
        PRIVATE_DIRECTORIES.intersection(lowered)
        or any(part.startswith(".draft-") for part in lowered)
        or any(lowered[i : i + 2] == ("docs", "reference") for i in range(len(lowered) - 1))
        or leaf == ".env"
        or leaf.startswith(".env.")
        or PurePosixPath(leaf).suffix in PRIVATE_SUFFIXES
    ):
        raise RuntimeError(f"Private/local content in distribution: {name!r}")
    synthetic = source and lowered[:2] == ("tests", "fixtures")
    if PurePosixPath(leaf).suffix in SOURCE_SUFFIXES and not synthetic:
        raise RuntimeError(f"Source-data file outside synthetic fixtures: {name!r}")
    return PurePosixPath(*parts).as_posix()


def check_distribution_contents(wheel: Path, source_archive: Path, root: Path) -> None:
    """Check actual built archives and require the reviewed source-release guides."""
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(set(names)) != len(names):
            raise RuntimeError("Duplicate wheel archive members")
        for name in names:
            check_member_path(name, source=False)
        licenses = [
            name for name in names if PurePosixPath(name).parts[-2:] == ("licenses", "LICENSE")
        ]
        if len(licenses) != 1 or archive.read(licenses[0]) != (root / "LICENSE").read_bytes():
            raise RuntimeError("Wheel is missing the reviewed MIT LICENSE")
    with tarfile.open(source_archive, "r:gz") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if not names or len(set(names)) != len(names):
            raise RuntimeError("Empty source archive or duplicate members")
        if len({PurePosixPath(name).parts[0] for name in names if name}) != 1:
            raise RuntimeError("Source archive must have one top-level directory")
        guides = {}
        for member in members:
            relative = check_member_path(member.name, source=True)
            if not (member.isfile() or member.isdir()):
                raise RuntimeError(f"Unsupported source archive member: {member.name!r}")
            if relative in REQUIRED_SOURCE_GUIDES:
                guides[relative] = member
        for guide in REQUIRED_SOURCE_GUIDES:
            guide_member = guides.get(guide)
            if guide_member is None or not guide_member.isfile():
                raise RuntimeError(f"Source archive is missing required guide: {guide}")
            stream = archive.extractfile(guide_member)
            if stream is None or stream.read() != (root / guide).read_bytes():
                raise RuntimeError(f"Source archive has changed required guide: {guide}")
    print("Verified distribution paths, license, and source-release guides.", flush=True)
