"""One immutable computer-clock reference for each desktop session."""

from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class AnalysisSession:
    id: str
    started_at: datetime

    def __post_init__(self) -> None:
        if self.started_at.utcoffset() is None:
            raise ValueError("The session start time must include a time-zone offset.")

    @property
    def reference_date(self) -> date:
        """Use the startup local date, even when UTC is on another calendar day."""
        return self.started_at.date()

    @property
    def date_label(self) -> str:
        return f"Reference date: {self.reference_date.isoformat()}"

    @property
    def startup_label(self) -> str:
        offset = self.started_at.strftime("%z")
        offset = offset[:3] + ":" + offset[3:]
        return f"{self.date_label} · Started {self.started_at:%H:%M:%S} (UTC{offset})"


def start_session(directory: Path | None = None) -> AnalysisSession:
    """Capture local time once and record it without touching source workbooks."""
    session = AnalysisSession(uuid4().hex, datetime.now(UTC).astimezone())
    directory = directory if directory is not None else Path.cwd() / ".artifacts" / "sessions"
    target = directory / (session.id + ".json")
    temporary = target.with_suffix(".tmp")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "session_id": session.id,
                    "clock_source": "computer",
                    "started_at_local": session.started_at.isoformat(),
                    "started_at_utc": session.started_at.astimezone(UTC).isoformat(),
                    "timezone_name": session.started_at.tzname(),
                    "reference_date": session.reference_date.isoformat(),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temporary.replace(target)
    except OSError as error:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
        raise OSError(
            f"Could not record the session start time in {directory}. "
            "Check disk space and folder access."
        ) from error
    return session
