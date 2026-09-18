"""Exercise the date foundation from an isolated installed wheel."""

import hashlib
import tempfile
from datetime import date
from pathlib import Path

from openpyxl import Workbook  # type: ignore[import-untyped]

from loan_tape.date_analysis import (
    CalendarBinding,
    DateBinding,
    DatePair,
    analyze_standardized_dates,
)
from loan_tape.date_calendar import build_calendar
from loan_tape.date_export import build_export_payload
from loan_tape.date_parser import DateProfile, parse_date
from loan_tape.date_reader import read_excel_date_column
from loan_tape.date_runs import check_run_source, load_date_run, save_date_run
from loan_tape.date_standardization import DateMapping, standardize_excel_dates
from loan_tape.pack_format import load_pack
from loan_tape.packs import Catalog
from loan_tape.ranges import parse_range
from loan_tape.selection import SavedTable, SourceSelection


def main() -> None:
    pack = load_pack(Path(__file__).resolve().parents[1] / "packs" / "loan-dates")
    assert len(pack.fields) == 4 and pack.id == "loan.dates"
    with tempfile.TemporaryDirectory(prefix="date-smoke-", dir=Path.cwd()) as temporary:
        path = Path(temporary) / "synthetic-dates.xlsx"
        book = Workbook()
        sheet = book.active
        sheet.title = "Dates"
        sheet["A1"] = "Closing Date"
        sheet["A2"] = "1/8/21"
        sheet["A3"] = 60
        sheet["A3"].number_format = "yyyy-mm-dd"
        sheet["A4"] = "=TODAY()"
        sheet["B1"] = "Current Maturity Date"
        sheet["B2"] = "1/7/21"
        sheet["B3"] = "7/3/26"
        sheet["B4"] = "1/1/27"
        book.save(path)
        book.close()
        original = path.read_bytes()
        selection = SourceSelection(
            hashlib.sha256(original).hexdigest(), "Dates", parse_range("A1:B5"), 1
        )
        column = read_excel_date_column(path, selection, 1)
        profile = DateProfile(
            text_formats=("M/D/YY",), two_digit_year_start=2000, numeric_dates="excel_serial"
        )
        profile = DateProfile.from_json(profile.to_json())
        results = tuple(parse_date(cell, profile) for cell in column.cells)
        parsed = results[0].parsed_date
        assert parsed is not None and parsed.isoformat() == "2021-01-08"
        assert results[1].code == "excel_fictitious_1900_02_29"
        assert results[2].code == "formula_not_evaluated"
        assert results[3].missing_kind == "absent"
        calendar = build_calendar("us.sifma_fixed_income")
        table = SavedTable("a" * 32, "Synthetic smoke", selection)
        catalog = Catalog("dates", (pack,))
        standardized = standardize_excel_dates(
            path,
            table,
            (
                DateMapping(1, "loan.dates:closing_date", profile),
                DateMapping(2, "loan.dates:current_maturity_date", profile),
            ),
            catalog,
        )
        assert standardized.cell_count == 8
        analysis = analyze_standardized_dates(
            standardized,
            (
                DateBinding(1, "loan.dates:closing_date", profile),
                DateBinding(
                    2,
                    "loan.dates:current_maturity_date",
                    profile,
                    calendar=CalendarBinding(calendar.id, "maturity"),
                ),
            ),
            reference_date=date(2026, 9, 17),
            pairs=(DatePair(1, 2),),
            calendars=(calendar,),
        )
        output = analysis.to_dict()["results"]
        assert output["row_count"] == 4 and output["cell_count"] == 8
        assert output["pairs"][0]["not_evaluable_count"] == 3
        assert any(f["rule_id"] == "date.pair_order" for f in output["findings"])
        saved = save_date_run(analysis, Path(temporary) / "runs")
        assert load_date_run(saved.path).analysis.fingerprint == analysis.fingerprint
        payload = build_export_payload(saved, path)
        assert [sheet["name"] for sheet in payload["sheets"]] == [
            "Loan Tape",
            "Summary",
            "Findings",
            "Date Results",
            "Pair Results",
            "Audit",
        ]
        loan_tape = payload["sheets"][0]
        assert len(loan_tape["rows"]) == 5 and len(loan_tape["rows"][0]) == 2
        assert loan_tape["refined_date_count"] == 4
        assert payload["analysis_fingerprint"] == analysis.fingerprint
        assert check_run_source(saved, path) == "unchanged"
        assert path.read_bytes() == original
    print("Installed-wheel date standardization, red flags, calendars and saved-run replay passed.")


if __name__ == "__main__":
    main()
