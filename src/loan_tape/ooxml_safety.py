"""Shared package-level limits for untrusted OOXML workbooks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from zipfile import ZipFile, ZipInfo


@dataclass(frozen=True)
class OoxmlLimits:
    max_members: int = 5_000
    max_part_bytes: int = 64 * 1024 * 1024
    max_total_bytes: int = 256 * 1024 * 1024
    max_compression_ratio: int = 1_000


DEFAULT_LIMITS = OoxmlLimits()


def validate_ooxml_archive(
    archive: ZipFile,
    *,
    error_type: type[Exception] = ValueError,
    cancelled: Callable[[], None] = lambda: None,
    limits: OoxmlLimits | None = None,
) -> tuple[ZipInfo, ...]:
    """Reject unsafe or amplified package metadata before any XML part is parsed."""
    policy = DEFAULT_LIMITS if limits is None else limits
    members = tuple(item for item in archive.infolist() if not item.is_dir())
    if len(members) > policy.max_members:
        raise error_type("Workbook package contains too many parts.")

    names: set[str] = set()
    expanded = 0
    for item in members:
        cancelled()
        name = item.filename
        path = PurePosixPath(name)
        if (
            not name
            or "\\" in name
            or "\0" in name
            or path.is_absolute()
            or path.as_posix() != name
            or any(part in {"", ".", ".."} or ":" in part for part in path.parts)
        ):
            raise error_type("Workbook package contains an unsafe part name.")
        if name in names:
            raise error_type("Duplicate workbook package entries.")
        names.add(name)
        if item.flag_bits & 0x1:
            raise error_type("Encrypted workbook package parts are unsupported.")
        if item.file_size > policy.max_part_bytes:
            raise error_type("Workbook package part exceeds the expanded-size limit.")
        expanded += item.file_size
        if expanded > policy.max_total_bytes:
            raise error_type("Workbook package exceeds the aggregate expanded-size limit.")
        if item.file_size and (
            item.compress_size == 0
            or item.file_size > item.compress_size * policy.max_compression_ratio
        ):
            raise error_type("Workbook package part exceeds the compression-ratio limit.")
    return members
