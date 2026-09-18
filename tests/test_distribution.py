"""Release guards examine real archives, including accidentally packaged local data."""

import importlib
import io
import tarfile
import zipfile
from pathlib import Path

import pytest


@pytest.fixture
def guard(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("_distribution")


def archives(tmp_path, guard, *, wheel_extra=None, source_extra=None, missing=None, changed=None):
    root = tmp_path / "project"
    root.mkdir()
    documents = {}
    for name in guard.REQUIRED_SOURCE_GUIDES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"Reviewed synthetic guide: {name}\n", encoding="utf-8")
        if name != missing:
            documents[name] = b"Unreviewed content" if name == changed else path.read_bytes()
    documents.update(source_extra or {})
    wheel = tmp_path / "loan_tape-0.1-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as output:
        output.writestr("loan_tape/__init__.py", "")
        output.writestr("loan_tape/guidance/SIFMA_CALENDAR.md", "Synthetic guidance")
        output.writestr("loan_tape-0.1.dist-info/licenses/LICENSE", (root / "LICENSE").read_bytes())
        for name, content in (wheel_extra or {}).items():
            output.writestr(name, content)
    source = tmp_path / "loan_tape-0.1.tar.gz"
    with tarfile.open(source, "w:gz") as output:
        for name, content in documents.items():
            member = tarfile.TarInfo("loan_tape-0.1/" + name)
            member.size = len(content)
            output.addfile(member, io.BytesIO(content))
    return wheel, source, root


def test_clean_archives_retain_guides_and_synthetic_source_fixtures(tmp_path, guard):
    paths = archives(
        tmp_path,
        guard,
        source_extra={"tests/fixtures/example.xml": b"<loans/>", "src/loan_tape/main.py": b""},
    )
    guard.check_distribution_contents(*paths)


@pytest.mark.parametrize(
    "where,name",
    [
        ("wheel", "loan_tape/.env.production"),
        ("wheel", "loan_tape/private.PFX"),
        ("wheel", "loan_tape/runtime.log"),
        ("wheel", "loan_tape/portfolio.XML"),
        ("wheel", "loan_tape/inputs/manifest.json"),
        ("source", ".local/review.md"),
        ("source", "packs/.history/example-old/fields.json"),
        ("source", "packs/.draft-interrupted/fields.json"),
        ("source", "docs/reference/research.md"),
        ("source", "inputs/manifest.json"),
        ("source", "outputs/portfolio.xlsx"),
        ("source", "loans.csv"),
        ("source", "src/loan_tape/.env"),
    ],
)
def test_actual_archive_rejects_private_contents(tmp_path, guard, where, name):
    paths = archives(tmp_path, guard, **{f"{where}_extra": {name: b"SYNTHETIC ONLY"}})
    with pytest.raises(RuntimeError, match="Private/local|Source-data"):
        guard.check_distribution_contents(*paths)


@pytest.mark.parametrize("name", ["../outside", "/absolute", "C:/drive", "dir\\file", "bad\nname"])
@pytest.mark.parametrize("source", [False, True])
def test_unsafe_member_paths_are_rejected(guard, name, source):
    with pytest.raises(RuntimeError, match="Unsafe"):
        guard.check_member_path(name, source=source)


@pytest.mark.parametrize("option", ["missing", "changed"])
def test_source_guides_must_match_reviewed_files(tmp_path, guard, option):
    paths = archives(tmp_path, guard, **{option: "SECURITY.md"})
    with pytest.raises(RuntimeError, match="required guide"):
        guard.check_distribution_contents(*paths)


def test_source_archive_links_are_rejected(tmp_path, guard):
    wheel, source, root = archives(tmp_path, guard)
    with tarfile.open(source, "w:gz") as output:
        member = tarfile.TarInfo("loan_tape-0.1/link")
        member.type = tarfile.SYMTYPE
        member.linkname = "../../outside"
        output.addfile(member)
    with pytest.raises(RuntimeError, match="Unsupported source archive member"):
        guard.check_distribution_contents(wheel, source, root)


def test_wheel_license_must_match_reviewed_file(tmp_path, guard):
    wheel, source, root = archives(tmp_path, guard)
    with zipfile.ZipFile(wheel, "w") as output:
        output.writestr("loan_tape/__init__.py", "")
        output.writestr("loan_tape-0.1.dist-info/licenses/LICENSE", "changed")
    with pytest.raises(RuntimeError, match="reviewed MIT LICENSE"):
        guard.check_distribution_contents(wheel, source, root)
