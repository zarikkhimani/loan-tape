"""Optional XSD validation through the existing XML preview."""

import sys
import time
from pathlib import Path
from threading import Event
from unittest.mock import patch

from desktop_scenarios import wait_for_copy, wait_for_preview

from loan_tape import xml_schema
from loan_tape.intake import IntakeStore
from loan_tape.ui import LoanTapeApp, create_root


def wait_xsd(app: LoanTapeApp) -> None:
    child = app.inspector.xsd_validator
    assert child is not None
    child.window.withdraw()
    deadline = time.monotonic() + 15
    while child.busy and not child.closed:
        app.root.update()
        assert time.monotonic() < deadline, "XSD validation did not finish"
        time.sleep(0.01)
    app.root.update()


def clean_results() -> None:
    path = Path(".artifacts/xsd-validation")
    assert not path.exists() or not list(path.iterdir())


def run(scenario: str, work: Path) -> None:
    schema_folder = work / "schemas"
    schema_folder.mkdir()
    schema = schema_folder / "loans.xsd"
    schema.write_text(
        """<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
        <xs:element name="loans"><xs:complexType><xs:sequence>
        <xs:element name="loan" maxOccurs="unbounded"><xs:complexType><xs:sequence>
        <xs:element name="amount"><xs:simpleType><xs:restriction base="xs:decimal">
        <xs:minInclusive value="0"/></xs:restriction></xs:simpleType></xs:element>
        </xs:sequence><xs:attribute name="id" type="xs:string" use="required"/>
        </xs:complexType></xs:element>
        </xs:sequence></xs:complexType></xs:element></xs:schema>""",
        encoding="utf-8",
    )
    source = work / "loans.xml"
    invalid = scenario != "valid"
    source.write_text(
        "<loans>"
        + "".join(
            f'<loan id="{row:06}"><amount>{"-" if invalid else ""}{row}</amount></loan>'
            for row in range(1, 71)
        )
        + "</loans>",
        encoding="utf-8",
    )
    source_before, schema_before = source.read_bytes(), schema.read_bytes()
    root = create_root()
    root.withdraw()
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    app = LoanTapeApp(root, IntakeStore(work / "inputs"))
    try:
        app.add_file(source)
        wait_for_copy(app)
        app.inspect_file()
        wait_for_preview(app)
        panel = app.inspector
        assert panel.xsd_button is not None
        assert panel.xsd_button.cget("text") == "Validate XSD…"
        assert panel.xsd_button.instate(["!disabled"])

        if scenario in {"invalid", "valid"}:
            with patch("loan_tape.preview_ui.filedialog.askopenfilename", return_value=str(schema)):
                panel.xsd_button.invoke()
            wait_xsd(app)
            child = panel.xsd_validator
            report = child.report
            assert report is not None
            assert report.schema.path == schema.resolve()
            assert report.schema_version == "XSD 1.0"
            assert "local schema file" in child.summary.get()
            if scenario == "valid":
                assert report.finding_count == 0
                assert child.grid.get_children() == ()
                assert "Valid:" in child.status.get()
            else:
                assert report.finding_count == 70
                assert len(child.grid.get_children()) == 50
                assert child.page_label.get() == "1–50 of 70"
                child.next.invoke()
                assert len(child.grid.get_children()) == 20
                assert child.page_label.get() == "51–70 of 70"
                child.grid.selection_set("70")
                child._selected()
                assert "/loans/loan[70]/amount" in child.detail.get("1.0", "end")
                assert "greater or equal" in child.detail.get("1.0", "end")
            child.close()
            assert report._closed
            clean_results()
        elif scenario == "error":
            outside = work / "outside.xsd"
            outside.write_text(
                '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"/>',
                encoding="utf-8",
            )
            schema.write_text(
                """<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
                <xs:include schemaLocation="../outside.xsd"/></xs:schema>""",
                encoding="utf-8",
            )
            schema_before = schema.read_bytes()
            with patch("loan_tape.preview_ui.filedialog.askopenfilename", return_value=str(schema)):
                panel.xsd_button.invoke()
            wait_xsd(app)
            child = panel.xsd_validator
            assert child.report is None
            assert "outside-folder imports are blocked" in child.status.get()
            child.close()
            clean_results()
        elif scenario in {"cancel", "shutdown"}:
            started = Event()
            original = xml_schema._hash_file

            def slow(path, cancelled):
                result = original(path, cancelled)
                if path == panel.path and not started.is_set():
                    started.set()
                    assert cancelled is not None and cancelled.wait(5)
                return result

            with (
                patch.object(xml_schema, "_hash_file", slow),
                patch("loan_tape.preview_ui.filedialog.askopenfilename", return_value=str(schema)),
            ):
                panel.xsd_button.invoke()
                child = panel.xsd_validator
                child.window.withdraw()
                deadline = time.monotonic() + 7
                while not started.is_set():
                    root.update()
                    time.sleep(0.01)
                    assert time.monotonic() < deadline
                app.close() if scenario == "shutdown" else child.close()
                while app.workers.active_names():
                    root.update()
                    time.sleep(0.01)
                    assert time.monotonic() < deadline
                clean_results()
        else:
            raise AssertionError(scenario)
        assert not errors, errors
        assert source.read_bytes() == source_before
        assert schema.read_bytes() == schema_before
        saved = Path(app.saved_path.get())
        if scenario == "shutdown":
            assert not saved.exists()
        else:
            assert saved.read_bytes() == source_before
    finally:
        if not app.closed:
            app.close()
            deadline = time.monotonic() + 5
            while not app.closed:
                root.update()
                time.sleep(0.01)
                assert time.monotonic() < deadline


if __name__ == "__main__":
    run(sys.argv[1], Path(sys.argv[2]))
