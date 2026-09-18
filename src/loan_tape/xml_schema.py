"""Optional, read-only XML Schema validation with local-only dependencies."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

import xmlschema
from defusedxml import ElementTree  # type: ignore[import-untyped]
from xmlschema import XMLResource

from loan_tape.inspection import CancellableReader, InspectionError, check_read_cancelled
from loan_tape.intake import MAX_FILE_BYTES

FINDINGS_PAGE_SIZE = 50
MAX_SCHEMA_FILE_BYTES = 25 * 1024 * 1024
MAX_SCHEMA_TOTAL_BYTES = 100 * 1024 * 1024
MAX_SCHEMA_FILES = 128
MAX_SCHEMA_DEPTH = 32
MAX_FINDING_TEXT = 32_768
RESULT_MAX_BYTES = 512 * 1024 * 1024
XSD_NAMESPACE = "http://www.w3.org/2001/XMLSchema"
VERSIONING_NAMESPACE = "http://www.w3.org/2007/XMLSchema-versioning"


@dataclass(frozen=True)
class SchemaResource:
    path: Path
    sha256: str
    size: int


@dataclass(frozen=True)
class XsdFinding:
    number: int
    source_path: str
    line: int | None
    reason: str
    category: str


@dataclass
class XsdValidation:
    source_sha256: str
    schema: SchemaResource
    schema_version: str
    resources: tuple[SchemaResource, ...]
    finding_count: int
    _temporary: tempfile.TemporaryDirectory[str]
    _closed: bool = False

    def page(self, offset: int = 0) -> tuple[XsdFinding, ...]:
        if self._closed:
            raise InspectionError("XSD validation results are closed. Run validation again.")
        if type(offset) is not int or offset < 0:
            raise InspectionError("Finding offset must be a non-negative whole number.")
        db = sqlite3.connect(Path(self._temporary.name) / "findings.sqlite")
        try:
            return tuple(
                XsdFinding(number, path, line, reason, category)
                for number, path, line, reason, category in db.execute(
                    "SELECT id, source_path, line, reason, category FROM findings "
                    "WHERE id > ? ORDER BY id LIMIT ?",
                    (offset, FINDINGS_PAGE_SIZE),
                )
            )
        finally:
            db.close()

    def close(self) -> None:
        if not self._closed:
            self._temporary.cleanup()
            self._closed = True


def _hash_file(path: Path, cancelled: Event | None) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with CancellableReader(path, cancelled) as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def _schema_language(
    path: Path, cancelled: Event | None
) -> tuple[type[xmlschema.XMLSchemaBase], str]:
    try:
        with CancellableReader(path, cancelled) as source:
            root = ElementTree.parse(source, forbid_dtd=True).getroot()
    except (ElementTree.ParseError, ValueError) as error:
        raise InspectionError(f"The selected XSD could not be parsed safely. {error}") from error
    if root.tag != f"{{{XSD_NAMESPACE}}}schema":
        raise InspectionError("The selected file is not an XML Schema document.")
    minimum = root.attrib.get(f"{{{VERSIONING_NAMESPACE}}}minVersion", "")
    version = root.attrib.get("version", "")
    if minimum.startswith("1.1") or version == "1.1":
        return xmlschema.XMLSchema11, "XSD 1.1"
    return xmlschema.XMLSchema10, "XSD 1.0"


def _schema_closure(main: Path, cancelled: Event | None) -> tuple[SchemaResource, ...]:
    """Approve and budget the complete local dependency graph before compilation."""
    root = main.parent.resolve(strict=True)
    pending = [(main, 0)]
    resources: dict[Path, SchemaResource] = {}
    total = 0
    dependency_tags = {
        f"{{{XSD_NAMESPACE}}}include",
        f"{{{XSD_NAMESPACE}}}import",
        f"{{{XSD_NAMESPACE}}}redefine",
        f"{{{XSD_NAMESPACE}}}override",
    }
    while pending:
        check_read_cancelled(cancelled)
        path, depth = pending.pop()
        if path in resources:
            continue
        if depth > MAX_SCHEMA_DEPTH:
            raise InspectionError(
                f"Local schema dependencies exceed the depth limit of {MAX_SCHEMA_DEPTH}."
            )
        if len(resources) >= MAX_SCHEMA_FILES:
            raise InspectionError(
                f"Local schema dependencies exceed the file limit of {MAX_SCHEMA_FILES}."
            )
        digest, size = _hash_file(path, cancelled)
        if size > MAX_SCHEMA_FILE_BYTES:
            subject = "The selected XSD" if path == main else f"Schema dependency {path.name}"
            raise InspectionError(
                f"{subject} exceeds the {MAX_SCHEMA_FILE_BYTES // 1024 // 1024} MiB limit."
            )
        total += size
        if total > MAX_SCHEMA_TOTAL_BYTES:
            raise InspectionError(
                f"Local schema dependencies exceed the {MAX_SCHEMA_TOTAL_BYTES // 1024 // 1024} MiB total limit."
            )
        try:
            with CancellableReader(path, cancelled) as source:
                document = ElementTree.parse(source, forbid_dtd=True).getroot()
        except (ElementTree.ParseError, ValueError) as error:
            raise InspectionError(
                f"The selected XSD could not be parsed safely. {error}"
            ) from error
        if document.tag != f"{{{XSD_NAMESPACE}}}schema":
            raise InspectionError(f"Schema dependency {path.name} is not an XML Schema document.")
        resources[path] = SchemaResource(path, digest, size)
        children: list[Path] = []
        for item in document:
            if item.tag not in dependency_tags:
                continue
            location = item.attrib.get("schemaLocation")
            if location is None and item.tag == f"{{{XSD_NAMESPACE}}}import":
                continue
            if not location:
                raise InspectionError("An XSD dependency has no schemaLocation.")
            parsed = urlsplit(location)
            relative = unquote(parsed.path)
            if (
                parsed.scheme
                or parsed.netloc
                or parsed.query
                or parsed.fragment
                or "\\" in relative
                or Path(relative).is_absolute()
            ):
                raise InspectionError(
                    "The XSD could not be compiled from its local folder. "
                    "Remote and outside-folder imports are blocked."
                )
            try:
                target = (path.parent / relative).resolve(strict=True)
            except OSError as error:
                raise InspectionError(
                    "The XSD could not be compiled from its local folder. "
                    f"Remote and outside-folder imports are blocked. {error}"
                ) from error
            if not target.is_file() or not target.is_relative_to(root):
                raise InspectionError(
                    "The XSD could not be compiled from its local folder. "
                    "Remote and outside-folder imports are blocked."
                )
            children.append(target)
        pending.extend((child, depth + 1) for child in reversed(children))
    return tuple(
        resources[path] for path in sorted(resources, key=lambda item: str(item).casefold())
    )


def _url_path(url: str | None) -> Path | None:
    if not url:
        return None
    parsed = urlsplit(url)
    if parsed.scheme not in {"", "file"}:
        return None
    raw = url2pathname(unquote(parsed.path if parsed.scheme else url))
    if os.name == "nt" and re.match(r"^[\\/]?[A-Za-z]:", raw):
        raw = raw.lstrip("\\/")
    try:
        return Path(raw).resolve(strict=True)
    except OSError:
        return None


def _schema_resources(
    schema: xmlschema.XMLSchemaBase, root: Path, cancelled: Event | None
) -> tuple[SchemaResource, ...]:
    paths: set[Path] = set()
    for item in schema.maps.iter_schemas():
        path = _url_path(getattr(getattr(item, "source", None), "url", None))
        if path is not None and path.is_relative_to(root):
            paths.add(path)
    resources: list[SchemaResource] = []
    total = 0
    for path in sorted(paths, key=lambda item: str(item).casefold()):
        digest, size = _hash_file(path, cancelled)
        if size > MAX_SCHEMA_FILE_BYTES:
            raise InspectionError(
                f"Schema dependency {path.name} exceeds the {MAX_SCHEMA_FILE_BYTES // 1024 // 1024} MiB limit."
            )
        total += size
        if total > MAX_SCHEMA_TOTAL_BYTES:
            raise InspectionError(
                f"Local schema dependencies exceed the {MAX_SCHEMA_TOTAL_BYTES // 1024 // 1024} MiB total limit."
            )
        resources.append(SchemaResource(path, digest, size))
    if not resources:
        raise InspectionError("The selected XSD could not be identified after compilation.")
    return tuple(resources)


def _same_resources(resources: tuple[SchemaResource, ...], cancelled: Event | None) -> bool:
    for resource in resources:
        try:
            digest, size = _hash_file(resource.path, cancelled)
        except OSError:
            return False
        if digest != resource.sha256 or size != resource.size:
            return False
    return True


def _limit_storage(db: sqlite3.Connection) -> None:
    db.execute("PRAGMA page_size = 4096")
    db.execute(f"PRAGMA max_page_count = {max(1, RESULT_MAX_BYTES // 4096)}")
    db.execute("PRAGMA cache_size = -2048")
    db.execute("PRAGMA temp_store = FILE")


def _finding_text(value: object, fallback: str) -> str:
    text = str(value or fallback).strip()
    if len(text) <= MAX_FINDING_TEXT:
        return text
    return text[: MAX_FINDING_TEXT - 28] + " … [finding text truncated]"


def validate_xml_schema(
    xml_path: Path,
    xsd_path: Path,
    expected_source_sha256: str,
    *,
    cancelled: Event | None = None,
    progress: Callable[[str], None] = lambda message: None,
) -> XsdValidation:
    """Validate one complete XML file against an explicitly selected local XSD."""
    if xml_path.suffix.lower() != ".xml":
        raise InspectionError("XSD validation requires an XML source file.")
    if xsd_path.suffix.lower() != ".xsd":
        raise InspectionError("Choose an .xsd schema file.")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_source_sha256):
        raise InspectionError("The XML preview has no valid source identity.")
    try:
        schema_path = xsd_path.resolve(strict=True)
    except OSError as error:
        raise InspectionError("The selected XSD could not be found or opened.") from error
    if not schema_path.is_file():
        raise InspectionError("Choose an .xsd schema file.")
    check_read_cancelled(cancelled)
    progress("Checking the XML and selected schema identities…")
    source_hash, source_size = _hash_file(xml_path, cancelled)
    if source_size > MAX_FILE_BYTES:
        raise InspectionError(
            f"XML files larger than {MAX_FILE_BYTES // 1024 // 1024} MiB are not supported."
        )
    if source_hash != expected_source_sha256:
        raise InspectionError("The XML source changed. Reopen its preview before validating it.")
    approved_resources = _schema_closure(schema_path, cancelled)
    approved_main = next(item for item in approved_resources if item.path == schema_path)
    main_hash, main_size = approved_main.sha256, approved_main.size
    schema_class, schema_version = _schema_language(schema_path, cancelled)
    progress(f"Compiling {schema_version} from the selected local schema folder…")
    try:
        schema = schema_class(
            str(schema_path),
            validation="strict",
            allow="sandbox",
            defuse="always",
            use_fallback=False,
            use_location_hints=False,
        )
        resources = _schema_resources(schema, schema_path.parent, cancelled)
        if resources != approved_resources:
            raise InspectionError(
                "The XSD dependencies changed while the schema was being compiled. Try again."
            )
    except InspectionError:
        raise
    except (xmlschema.XMLSchemaException, OSError, ValueError) as error:
        raise InspectionError(
            "The XSD could not be compiled from its local folder. "
            f"Remote and outside-folder imports are blocked. {error}"
        ) from error
    main = next((item for item in resources if item.path == schema_path), None)
    if main is None or main.sha256 != main_hash or main.size != main_size:
        raise InspectionError("The selected XSD changed while it was being compiled. Try again.")

    work = Path.cwd() / ".artifacts" / "xsd-validation"
    work.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix="result-", dir=work)
    db: sqlite3.Connection | None = None
    try:
        db = sqlite3.connect(Path(temporary.name) / "findings.sqlite")
        _limit_storage(db)
        db.execute(
            "CREATE TABLE findings (id INTEGER PRIMARY KEY, source_path TEXT, "
            "line INTEGER, reason TEXT, category TEXT)"
        )
        progress("Validating the complete XML document…")

        def validation_hook(*args: object) -> bool:
            check_read_cancelled(cancelled)
            return False

        count = 0
        with CancellableReader(xml_path, cancelled) as source:
            resource = XMLResource(source, allow="none", defuse="always", lazy=True)
            for finding in schema.iter_errors(
                resource,
                use_defaults=False,
                validation_hook=validation_hook,
                use_location_hints=False,
            ):
                check_read_cancelled(cancelled)
                count += 1
                path = _finding_text(finding.path, "/")
                reason = _finding_text(finding.reason, "The XML does not match this schema.")
                category = type(finding).__name__.removeprefix("XMLSchema")
                line = finding.sourceline if isinstance(finding.sourceline, int) else None
                db.execute(
                    "INSERT INTO findings VALUES (?, ?, ?, ?, ?)",
                    (count, path, line, reason, category),
                )
                if count % 1000 == 0:
                    progress(f"Recorded {count:,} XSD findings…")
        db.commit()
        check_read_cancelled(cancelled)
        final_source_hash, final_source_size = _hash_file(xml_path, cancelled)
        if final_source_hash != source_hash or final_source_size != source_size:
            raise InspectionError("The XML source changed during XSD validation. Run it again.")
        if not _same_resources(resources, cancelled):
            raise InspectionError(
                "The XSD or one of its local dependencies changed during validation."
            )
        return XsdValidation(
            source_hash,
            main,
            schema_version,
            resources,
            count,
            temporary,
        )
    except sqlite3.Error as error:
        if db is not None:
            db.close()
            db = None
        temporary.cleanup()
        raise InspectionError(
            f"XSD finding storage failed; no complete result ({RESULT_MAX_BYTES // 1024 // 1024} MiB limit). {error}"
        ) from error
    except (xmlschema.XMLSchemaException, ElementTree.ParseError, OSError, ValueError) as error:
        if db is not None:
            db.close()
            db = None
        temporary.cleanup()
        raise InspectionError(f"The complete XML could not be validated. {error}") from error
    except BaseException:
        if db is not None:
            db.close()
            db = None
        temporary.cleanup()
        raise
    finally:
        if db is not None:
            db.close()
