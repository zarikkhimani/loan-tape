"""A fixed local reference date and durable, independent startup records."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from loan_tape.session import AnalysisSession, start_session


@pytest.mark.parametrize(
    "local_time, utc_time",
    [
        ("2026-09-16T23:59:59-05:00", "2026-09-17T04:59:59+00:00"),
        ("2026-09-17T00:00:01+14:00", "2026-09-16T10:00:01+00:00"),
        ("2026-11-01T01:30:00-05:00", "2026-11-01T06:30:00+00:00"),
        ("2026-11-01T01:30:00-06:00", "2026-11-01T07:30:00+00:00"),
    ],
)
def test_local_date_and_offset_survive_utc_day_changes_and_dst(tmp_path, local_time, utc_time):
    moment = datetime.fromisoformat(local_time)
    with patch("loan_tape.session.datetime") as clock:
        clock.now.return_value.astimezone.return_value = moment
        session = start_session(tmp_path)
        clock.now.assert_called_once_with(UTC)
        # Moving the computer clock later cannot change an existing session.
        clock.now.return_value.astimezone.return_value = datetime(2030, 1, 1, tzinfo=UTC)
        assert session.started_at == moment
        assert session.reference_date == moment.date()
    record = json.loads((tmp_path / (session.id + ".json")).read_text(encoding="utf-8"))
    assert record["started_at_local"] == local_time
    assert record["started_at_utc"] == utc_time
    assert record["reference_date"] == local_time[:10]
    assert record["clock_source"] == "computer"
    assert record["timezone_name"] == moment.tzname()
    assert (
        session.startup_label
        == f"Reference date: {local_time[:10]} · Started {local_time[11:19]} (UTC{local_time[19:]})"
    )
    assert list(tmp_path.glob("*.tmp")) == []


def test_each_launch_gets_a_new_record_even_with_the_same_clock_time(tmp_path):
    with patch("loan_tape.session.datetime") as clock:
        clock.now.return_value.astimezone.return_value = datetime.fromisoformat(
            "2026-09-16T12:00:00-05:00"
        )
        first = start_session(tmp_path)
        original = (tmp_path / (first.id + ".json")).read_bytes()
        second = start_session(tmp_path)
    assert first.id != second.id
    assert first.reference_date == second.reference_date
    assert len(list(tmp_path.glob("*.json"))) == 2
    assert (tmp_path / (first.id + ".json")).read_bytes() == original


def test_record_failure_is_explicit_and_removes_partial_file(tmp_path):
    with patch.object(Path, "replace", side_effect=OSError("Disk unavailable")):
        with pytest.raises(OSError, match="Could not record the session start time"):
            start_session(tmp_path)
    assert list(tmp_path.iterdir()) == []
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("keep me", encoding="utf-8")
    with pytest.raises(OSError, match="Check disk space and folder access"):
        start_session(blocked)
    assert blocked.read_text(encoding="utf-8") == "keep me"


def test_reference_requires_timezone_aware_time():
    with pytest.raises(ValueError, match="time-zone offset"):
        AnalysisSession("test", datetime(2026, 9, 16))
