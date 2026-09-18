"""Exercise file preservation and desktop startup from an isolated wheel installation."""

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook  # type: ignore[import-untyped]

from loan_tape.intake import IntakeStore
from loan_tape.mapping_profiles import load_builtin_profiles
from loan_tape.ui import LoanTapeApp, create_root


def main() -> None:
    (profile,) = load_builtin_profiles()
    assert profile.id == "warehouse-model" and len(profile.columns) == 94
    with tempfile.TemporaryDirectory(prefix="ui-smoke-", dir=Path.cwd()) as temporary:
        work = Path(temporary)
        source = work / "synthetic.csv"
        payload = b"loan_id,balance\r\n000123,0\r\n"
        source.write_bytes(payload)
        store = IntakeStore(work / "inputs")
        desktop_available = bool(os.name == "nt" or os.environ.get("DISPLAY"))
        if desktop_available:
            root = create_root()
            root.withdraw()
            app = LoanTapeApp(root, store)
            try:
                assert root.tk.call("package", "present", "tkdnd")
                session_record = Path.cwd() / ".artifacts" / "sessions" / (app.session.id + ".json")
                assert (
                    json.loads(session_record.read_text(encoding="utf-8"))["reference_date"]
                    == app.session.reference_date.isoformat()
                )
                app.add_file(source)
                deadline = time.monotonic() + 10
                while app.worker is not None:
                    root.update()
                    if time.monotonic() > deadline:
                        raise RuntimeError("Installed desktop copy did not finish.")
                    time.sleep(0.01)
                record = next(
                    item for item in store.list_files() if item["original_name"] == "synthetic.csv"
                )
                assert record["sha256"] == hashlib.sha256(payload).hexdigest()
                assert record["original_path"] == str(source)
                assert app.original_path.get() == str(source)
                assert Path(app.saved_path.get()).read_bytes() == payload
                app.saved_button.invoke()
                assert root.clipboard_get() == app.saved_path.get()
                app.inspect_button.invoke()
                assert app.inspector is not None
                assert app.inspector.session is app.session
                app.root.withdraw()
                deadline = time.monotonic() + 10
                while app.inspector.busy:
                    root.update()
                    if time.monotonic() > deadline:
                        raise RuntimeError("Installed preview did not finish.")
                    time.sleep(0.01)
                assert app.inspector.table.item("2", "values") == ("000123", "0")
                app.inspector.close()
                workbook = work / "anywhere.xlsx"
                book = Workbook()
                book.active["DZ5000"] = "000123"
                book.active["EA5000"] = 0
                hidden = book.create_sheet("Hidden")
                hidden.sheet_state = "hidden"
                hidden["X9999"] = "=1+1"
                book.save(workbook)
                book.close()
                original = workbook.read_bytes()
                app.add_file(workbook)
                deadline = time.monotonic() + 10
                while app.worker is not None:
                    root.update()
                    assert time.monotonic() < deadline, "Installed workbook copy timed out"
                    time.sleep(0.01)
                app.inspect_button.invoke()
                app.root.withdraw()
                deadline = time.monotonic() + 10
                while app.inspector.busy:
                    root.update()
                    assert time.monotonic() < deadline, "Installed workbook navigation timed out"
                    time.sleep(0.01)
                navigator = app.inspector.navigator
                assert navigator and navigator.index and navigator.index.complete
                assert navigator.area and navigator.area.address == "DZ5000:EA5000"
                assert app.inspector.table.item("5000", "values") == ("000123", "0")
                assert workbook.read_bytes() == original
                navigator.use_button.invoke()
                deadline = time.monotonic() + 10
                while app.inspector.busy:
                    root.update()
                    assert time.monotonic() < deadline, "Installed table save timed out"
                    time.sleep(0.01)
                app.inspector._select_column(0)
                assert app.order_panel is not None
                assert app.tabs.index("end") == 3
                app.tabs.select(app.order_panel.frame)
                root.update()
                deadline = time.monotonic() + 10
                while app.order_panel.busy:
                    root.update()
                    assert time.monotonic() < deadline, "Installed column ordering timed out"
                    time.sleep(0.01)
                assert app.order_panel.result is not None
                assert app.order_panel.result.total_rows == 1
                assert app.order_panel.result.total_columns == 2
                assert app.order_panel.entries["5000"].sort_cell.text == "000123"
                assert app.order_panel.grid.item("5000", "values") == ("000123", "0")
                app.order_panel.grid.selection_set("5000")
                app.order_panel._selected()
                app.order_panel.jump_button.invoke()
                deadline = time.monotonic() + 10
                while app.inspector.busy:
                    root.update()
                    assert time.monotonic() < deadline, "Installed ordered source jump timed out"
                    time.sleep(0.01)
                assert app.tabs.select() == str(app.inspector.frame)
                assert app.inspector.table.selection() == ("5000",)
                assert app.inspector.column_button is not None
                app.inspector.column_button.invoke()
                column_window = app.inspector.column_inspector
                assert column_window is not None
                column_window.window.withdraw()
                deadline = time.monotonic() + 10
                while column_window.busy:
                    root.update()
                    assert time.monotonic() < deadline, "Installed column inspection timed out"
                    time.sleep(0.01)
                assert column_window.profile is not None
                assert column_window.profile.total_rows == 1
                assert column_window.profile.examples[0].text == "000123"
                assert column_window.profile.session is app.session
                column_window.close()
                assert app.inspector.check_button is not None
                app.inspector.check_button.invoke()
                check_window = app.inspector.column_checker
                assert check_window is not None
                check_window.window.withdraw()
                check_window.expected.set("Number")
                check_window.run_button.invoke()
                deadline = time.monotonic() + 10
                while check_window.busy:
                    root.update()
                    assert time.monotonic() < deadline, "Installed column check timed out"
                    time.sleep(0.01)
                assert check_window.report is not None
                assert check_window.report.profile.total_rows == 1
                assert check_window.report.finding_count == 1
                assert check_window.report.page()[0].cell.text == "000123"
                assert check_window.report.profile.session is app.session
                check_window.close()
                assert workbook.read_bytes() == original
                xml_source = work / "synthetic.xml"
                xml_payload = (
                    "<loans>"
                    + "".join(
                        f'<loan id="{row:06}"><balance>0</balance>'
                        + "".join(
                            f"<f{column}>{row}:{column}</f{column}>" for column in range(1, 12)
                        )
                        + "</loan>"
                        for row in range(1, 31)
                    )
                    + "</loans>"
                ).encode()
                xml_source.write_bytes(xml_payload)
                app.add_file(xml_source)
                deadline = time.monotonic() + 10
                while app.worker is not None:
                    root.update()
                    assert time.monotonic() < deadline, "Installed XML copy timed out"
                    time.sleep(0.01)
                app.inspect_button.invoke()
                app.root.withdraw()
                while app.inspector.busy:
                    root.update()
                    assert time.monotonic() < deadline, "Installed XML preview timed out"
                    time.sleep(0.01)
                assert app.inspector.table.item("1", "values")[:2] == ("000001", "0")
                assert app.inspector.xml_group.get() == "/loans/loan"
                assert app.inspector.open_excel_button.instate(["disabled"])
                xml_nav = app.inspector.xml_navigation
                assert xml_nav is not None
                xml_nav.name.set("All loans")
                xml_nav.save_button.invoke()
                xml_nav.buttons["End"].invoke()
                deadline = time.monotonic() + 10
                while app.inspector.busy:
                    root.update()
                    assert time.monotonic() < deadline, "Installed XML paging timed out"
                    time.sleep(0.01)
                assert app.inspector.table.item("30", "values") == ("30:9", "30:10", "30:11")
                app.inspector.close()
                app.inspect_button.invoke()
                app.root.withdraw()
                deadline = time.monotonic() + 10
                while app.inspector.busy:
                    root.update()
                    assert time.monotonic() < deadline, "Installed XML restoration timed out"
                    time.sleep(0.01)
                assert app.inspector.xml_navigation is not None
                assert app.inspector.xml_navigation.saved_name.get() == "All loans"
                assert app.inspector.preview is not None
                assert app.inspector.preview.start_row == 21
                assert app.inspector.preview.start_column == 11
                assert app.inspector.table.item("30", "values") == ("30:9", "30:10", "30:11")
                app.inspector._select_column(1, entire=True)
                assert app.inspector.column_button is not None
                app.inspector.column_button.invoke()
                xml_inspection = app.inspector.column_inspector
                assert xml_inspection is not None
                xml_inspection.window.withdraw()
                deadline = time.monotonic() + 10
                while xml_inspection.busy:
                    root.update()
                    assert time.monotonic() < deadline, "Installed XML column inspection timed out"
                    time.sleep(0.01)
                assert xml_inspection.profile is not None
                assert xml_inspection.profile.total_rows == 30
                assert xml_inspection.profile.column == 12
                assert xml_inspection.profile.examples[0].source_path == "/loans[1]/loan[1]/f10[1]"
                xml_inspection.close()
                assert app.inspector.check_button is not None
                app.inspector.check_button.invoke()
                xml_check = app.inspector.column_checker
                assert xml_check is not None
                xml_check.window.withdraw()
                xml_check.expected.set("Number")
                xml_check.run_button.invoke()
                deadline = time.monotonic() + 10
                while xml_check.busy:
                    root.update()
                    assert time.monotonic() < deadline, "Installed XML column check timed out"
                    time.sleep(0.01)
                assert xml_check.report is not None
                assert xml_check.report.finding_count == 30
                assert xml_check.report.rules.number_format == "Plain decimal text"
                xml_check.next.invoke()
                assert len(xml_check.grid.get_children()) == 10
                xml_check.grid.selection_set("30")
                xml_check._selected()
                xml_check.jump_button.invoke()
                deadline = time.monotonic() + 10
                while app.inspector.busy:
                    root.update()
                    assert time.monotonic() < deadline, "Installed XML source jump timed out"
                    time.sleep(0.01)
                assert app.inspector.table.selection() == ("30",)
                assert app.inspector.preview is not None
                assert app.inspector.preview.start_column == 12
                xsd = work / "synthetic.xsd"
                xsd.write_text(
                    """<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
                    <xs:element name="loans"><xs:complexType><xs:sequence>
                    <xs:element name="loan" maxOccurs="unbounded">
                    <xs:complexType><xs:sequence>
                    <xs:any minOccurs="0" maxOccurs="unbounded" processContents="skip"/>
                    </xs:sequence><xs:anyAttribute processContents="skip"/>
                    </xs:complexType></xs:element>
                    </xs:sequence></xs:complexType></xs:element></xs:schema>""",
                    encoding="utf-8",
                )
                assert app.inspector.xsd_button is not None
                with patch(
                    "loan_tape.preview_ui.filedialog.askopenfilename", return_value=str(xsd)
                ):
                    app.inspector.xsd_button.invoke()
                xsd_window = app.inspector.xsd_validator
                assert xsd_window is not None
                xsd_window.window.withdraw()
                deadline = time.monotonic() + 15
                while xsd_window.busy:
                    root.update()
                    assert time.monotonic() < deadline, "Installed XSD validation timed out"
                    time.sleep(0.01)
                assert xsd_window.report is not None
                assert xsd_window.report.finding_count == 0
                assert xsd_window.report.schema.path == xsd.resolve()
                xsd_window.close()
                assert xml_source.read_bytes() == xml_payload
                assert Path(app.saved_path.get()).read_bytes() == xml_payload
                print(
                    "Installed session recording, desktop intake, CSV/Excel/XML preview, navigation, column ordering, inspection, checks, and XSD validation passed."
                )
            finally:
                app.close()
            assert store.list_files() == []
            assert not session_record.exists()
        else:
            store.save_path(source)
            print("No display: desktop window checks skipped; installed service exercised.")
            record = next(
                item for item in store.list_files() if item["original_name"] == "synthetic.csv"
            )
            assert record["sha256"] == hashlib.sha256(payload).hexdigest()
            assert record["original_path"] == str(source)
        assert source.read_bytes() == payload


if __name__ == "__main__":
    main()
