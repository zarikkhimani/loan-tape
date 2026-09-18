"""Native XML paging, saved setups, source identity, and tab behavior."""

import hashlib
import sys
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from desktop_scenarios import wait_for_copy, wait_for_preview
from test_xml_navigation import matrix

from loan_tape.intake import IntakeStore
from loan_tape.ui import LoanTapeApp, create_root
from loan_tape.xml_selection import (
    XmlSelections,
    load_xml_selections,
    save_xml_selections,
    xml_selection_path,
)


def run(scenario, work):
    source = work / "matrix.xml"
    payload = matrix(source)
    if scenario == "navigation":
        payload = payload.replace(b"</r>", b"<fees><fee>5</fee><fee>6</fee></fees></r>")
        source.write_bytes(payload)
    sha = hashlib.sha256(payload).hexdigest()
    if scenario == "settings_error":
        settings_file = xml_selection_path(sha)
        settings_file.parent.mkdir(parents=True)
        settings_file.write_text("{broken")
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
        nav = panel.xml_navigation
        assert nav is not None
        saved = Path(app.saved_path.get())
        if scenario == "navigation":
            assert not panel.table.get_children()
            assert nav.save_button.instate(["disabled"])
            panel.xml_group.set("/ns1:r/ns1:items/ns1:item")
            panel.xml_group_selector.event_generate("<<ComboboxSelected>>")
            wait_for_preview(app)
            assert panel.preview.record_count == 47 and panel.preview.field_count == 25
            nav.name.set("Loans")
            nav.save_button.invoke()
            assert not nav.has_unsaved_setup()
            assert load_xml_selections(sha).active.name == "Loans"
            nav.buttons["End"].invoke()
            assert panel.busy and nav.save_button.instate(["disabled"])
            wait_for_preview(app)
            assert panel.preview.start_row == 41 and panel.preview.start_column == 21
            assert panel.table.get_children() == tuple(str(i) for i in range(41, 48))
            assert panel.table.item("47", "values")[-1] == "000099"
            assert panel.table.heading("Y", "text").endswith("ns1:late")
            panel.table.selection_set("47")
            panel._select_column(4)
            assert "item[47]/ns1:late[1]" in panel.cell_text.get("1.0", "end")
            nav.buttons["row<"].invoke()
            wait_for_preview(app)
            assert panel.preview.start_row == 21 and panel.preview.start_column == 21
            nav.buttons["column<"].invoke()
            wait_for_preview(app)
            assert panel.preview.start_column == 11
            nav.jump_row.set("47")
            nav.jump_column.set("25")
            nav.buttons["Go"].invoke()
            wait_for_preview(app)
            assert panel.table.item("47", "values") == ("000099",)
            nav.jump_row.set("48")
            nav.jump()
            assert "inside" in nav.message.get() and not panel.busy
            nav.jump_row.set("oops")
            nav.jump()
            assert "whole" in nav.message.get()
            before = panel.preview
            app.tabs.select(app.files_page)
            root.update()
            app.activate_preview()
            root.update()
            assert panel.preview is before
            panel.xml_group.set("/ns1:r/ns1:fees/ns1:fee")
            panel.xml_group_selector.event_generate("<<ComboboxSelected>>")
            wait_for_preview(app)
            assert panel.preview.start_row == 1 and panel.preview.start_column == 1
            nav.name.set("Fees")
            nav.save_button.invoke()
            assert len(load_xml_selections(sha).data_sets) == 2
            nav.saved_name.set("Loans")
            nav.saved_selector.event_generate("<<ComboboxSelected>>")
            wait_for_preview(app)
            assert panel.table.item("47", "values") == ("000099",)
            nav.name.set("Main loans")
            nav.save_button.invoke()
            assert len(load_xml_selections(sha).data_sets) == 2
            nav.name.set("Unsaved name")
            with patch("loan_tape.ui.messagebox.askokcancel", return_value=False) as question:
                app.close_preview()
                assert question.called and not panel.closed
            with patch("loan_tape.xml_navigation_ui.messagebox.askokcancel", return_value=False):
                panel.xml_group.set("/ns1:r/ns1:fees/ns1:fee")
                panel.xml_group_selector.event_generate("<<ComboboxSelected>>")
                assert panel.xml_group.get() == "/ns1:r/ns1:items/ns1:item"
                assert nav.name.get() == "Unsaved name"
            nav.name.set(nav.clean_name)
            nav.saved_name.set("Fees")
            nav.choose_saved()
            wait_for_preview(app)
            nav.remove_button.invoke()
            assert [item.name for item in load_xml_selections(sha).data_sets] == ["Main loans"]
            nav.saved_name.set("Main loans")
            nav.choose_saved()
            wait_for_preview(app)
            panel.close()
            app.inspect_file()
            wait_for_preview(app)
            panel = app.inspector
            nav = panel.xml_navigation
            assert nav.saved_name.get() == "Main loans"
            assert panel.preview.start_row == 47 and panel.preview.start_column == 25
            assert panel.table.item("47", "values") == ("000099",)
            root.geometry("760x720")
            root.deiconify()
            for _ in range(5):
                root.update()
                time.sleep(0.02)
            go = nav.buttons["Go"]
            assert go.winfo_width() >= go.winfo_reqwidth()
            assert go.winfo_x() + go.winfo_width() <= nav.paging.winfo_width()
            assert nav.remove_button.winfo_width() >= nav.remove_button.winfo_reqwidth()
            nav.buttons["Start"].invoke()
            wait_for_preview(app)
            assert panel.table.item("1", "values")[0] == "000001"
            assert load_xml_selections(sha).active.row == 1
        elif scenario == "settings_error":
            assert panel.table.item("1", "values")[0] == "000001"
            assert nav.save_button.instate(["disabled"])
            assert "could not be read" in nav.message.get()
            nav.edge(True)
            wait_for_preview(app)
            assert panel.preview.start_row == 41
            assert "could not be read" in nav.message.get()
            assert settings_file.read_text() == "{broken"
        elif scenario == "save_failure":
            nav.name.set("Loans")
            with patch(
                "loan_tape.xml_navigation_ui.save_xml_selections",
                side_effect=PermissionError("read only"),
            ):
                nav.save()
            assert "not saved" in nav.message.get()
            assert not xml_selection_path(sha).exists()
            assert nav.has_unsaved_setup()
            nav.save()
            initial = load_xml_selections(sha)
            other = replace(initial.active, name="Changed elsewhere")
            save_xml_selections(XmlSelections(sha, (other,), other.id))
            nav.name.set("Overwrite attempt")
            nav.save()
            assert "another window" in nav.message.get()
            assert load_xml_selections(sha).active.name == "Changed elsewhere"
        elif scenario == "changed":
            nav.name.set("Loans")
            nav.save()
            saved.write_bytes(payload.replace(b"000001", b"000009"))
            nav.edge(True)
            wait_for_preview(app)
            assert panel.preview is None and not panel.table.get_children()
            assert "source changed" in panel.status.get()
            assert nav.save_button.instate(["disabled"])
            panel.close()
            app.inspect_file()
            wait_for_preview(app)
            panel = app.inspector
            nav = panel.xml_navigation
            assert nav.settings.data_sets == ()
            assert panel.preview.start_row == 1 and panel.table.item("1", "values")[0] == "000009"
        else:
            raise AssertionError(scenario)
        assert not errors, errors
        assert source.read_bytes() == payload
        if scenario != "changed":
            assert saved.read_bytes() == payload
    finally:
        if app.inspector and app.inspector.xml_navigation:
            app.inspector.xml_navigation.name.set(app.inspector.xml_navigation.clean_name)
        app.close()
        deadline = time.monotonic() + 5
        while not app.closed:
            root.update()
            assert time.monotonic() < deadline
            time.sleep(0.01)


if __name__ == "__main__":
    run(sys.argv[1], Path(sys.argv[2]))
