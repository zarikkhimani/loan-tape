"""Synthetic native pack manager exercises; all writes stay in the test directory."""

import json
import shutil
import sys
import time
from pathlib import Path
from threading import Event
from unittest.mock import patch

from loan_tape.intake import IntakeStore
from loan_tape.packs import PackStore
from loan_tape.ui import LoanTapeApp, create_root


def wait(root, predicate):
    deadline = time.monotonic() + 10
    while predicate():
        root.update()
        assert time.monotonic() < deadline, "Pack worker timed out"
        time.sleep(0.01)
    root.update()


def select(manager, pack_id):
    row = next(row for row in manager.rows.values() if row.pack_id == pack_id)
    manager.tree.selection_set(row.key)
    manager.window.update()
    return row


def run(scenario):
    shutil.copytree(Path(__file__).resolve().parents[1] / "packs", Path("packs"))
    root = create_root()
    root.withdraw()
    app = LoanTapeApp(root, IntakeStore(Path("inputs")))
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    app.packs_button.invoke()
    manager = app.pack_manager
    store = manager.store
    wait(root, lambda: manager.busy)
    try:
        assert manager.ready
        assert not store.state_dir.exists()
        app.packs_button.invoke()
        assert app.pack_manager is manager
        if scenario == "lifecycle":
            source = Path("synthetic.csv")
            payload = b"loan_id,balance\n000123,0\n"
            source.write_bytes(payload)
            app.add_file(source)
            wait(root, lambda: app.worker is not None)
            app.inspect_file()
            wait(root, lambda: app.inspector.busy)
            preview = app.inspector
            select(manager, "example.loans")
            assert len(manager.fields.get_children()) == 4
            manager.search.set("principal")
            assert manager.fields.get_children() == ("principal_balance",)
            assert "Expected type: decimal" in manager.field_detail.get("1.0", "end")
            manager.search.set("")
            manager.activate_button.invoke()
            wait(root, lambda: manager.busy)
            pin = store.pins()[0]
            assert manager.version.get() == "Active version"
            assert manager.activate_button.instate(["disabled"])
            path = Path("packs/example-loans/fields.json")
            fields = json.loads(path.read_text(encoding="utf-8"))
            fields[0]["label"] = "Edited identifier"
            path.write_text(json.dumps(fields), encoding="utf-8")
            manager.load_button.invoke()
            wait(root, lambda: manager.busy)
            assert manager._selected().status == "Active — edits available"
            assert manager.shown_pack.fields[0].label == "Loan identifier"
            manager.version.set("Editable files")
            manager.version_box.event_generate("<<ComboboxSelected>>")
            root.update()
            assert manager.shown_pack.fields[0].label == "Edited identifier"
            manager.activate_button.invoke()
            wait(root, lambda: manager.busy)
            assert store.pins()[0] != pin
            assert store.snapshot(pin).fields[0].label == "Loan identifier"
            manager.profile_input.set("research")
            assert manager.deactivate_button.instate(["disabled"])
            manager.load_button.invoke()
            wait(root, lambda: manager.busy)
            assert not store.pins("research")
            select(manager, "example.loans")
            manager.activate_button.invoke()
            wait(root, lambda: manager.busy)
            manager.close()
            app.packs_button.invoke()
            manager = app.pack_manager
            wait(root, lambda: manager.busy)
            assert "research" in manager.profile_box.cget("values")
            select(manager, "example.loans")
            assert manager._selected().pin
            manager.deactivate_button.invoke()
            wait(root, lambda: manager.busy)
            assert not PackStore(store.packs_dir, store.state_dir).pins()
            assert store.pins("research")
            assert source.read_bytes() == payload
            assert Path(app.saved_path.get()).read_bytes() == payload
            assert app.inspector is preview
            assert preview.table.item("2", "values") == ("000123", "0")
        elif scenario == "errors":
            select(manager, "example.loans")
            path = Path("packs/example-loans/fields.json")
            original = path.read_bytes()
            fields = json.loads(original)
            fields[0]["label"] = "Changed after review"
            path.write_text(json.dumps(fields), encoding="utf-8")
            manager.activate_button.invoke()
            wait(root, lambda: manager.busy)
            assert "changed since they were displayed" in manager.status.get()
            assert not store.pins()
            assert manager.activate_button.instate(["disabled"])
            manager.load_button.invoke()
            wait(root, lambda: manager.busy)
            select(manager, "example.loans")
            manager.activate_button.invoke()
            wait(root, lambda: manager.busy)
            pin = store.pins()[0]
            (store.state_dir / "snapshots" / f"{pin.fingerprint}.json").unlink()
            path.write_text("{", encoding="utf-8")
            manager.load_button.invoke()
            wait(root, lambda: manager.busy)
            select(manager, "example.loans")
            assert manager.shown_pack is None
            assert not manager.fields.get_children()
            assert manager.activate_button.instate(["disabled"])
            assert not manager.deactivate_button.instate(["disabled"])
            manager.deactivate_button.invoke()
            wait(root, lambda: manager.busy)
            assert not store.pins()
            profile = store.state_dir / "profiles/default.json"
            profile.write_text("{}", encoding="utf-8")
            manager.load_button.invoke()
            wait(root, lambda: manager.busy)
            assert not manager.ready
            assert not manager.tree.get_children()
            assert manager.deactivate_button.instate(["disabled"])
            assert "Could not load packs" in manager.status.get()
            assert profile.read_text(encoding="utf-8") == "{}"
        elif scenario == "closing":
            select(manager, "example.loans")
            release = Event()
            original = store.activate

            def delayed(*args, **kwargs):
                assert release.wait(8)
                return original(*args, **kwargs)

            with patch.object(store, "activate", side_effect=delayed):
                manager.activate_button.invoke()
                manager.close()
                assert manager.closing and not manager.closed
                assert "Closing" in manager.status.get()
                app.close()
                assert app.closing and not app.closed
                release.set()
                deadline = time.monotonic() + 10
                while not app.closed:
                    root.update()
                    assert time.monotonic() < deadline
                    time.sleep(0.01)
            assert store.pins()
            assert not app.workers.active_names()
        elif scenario == "layout":
            root.deiconify()
            root.geometry("760x720")
            manager.window.deiconify()
            manager.window.geometry("900x600")
            root.update()
            assert manager.field_detail.winfo_height() >= 90
            for widget in (app.packs_button, app.exit_button):
                assert (
                    widget.winfo_rootx() + widget.winfo_width()
                    <= root.winfo_rootx() + root.winfo_width()
                )
            for widget in (
                manager.activate_button,
                manager.deactivate_button,
                manager.status_label,
                manager.fields,
            ):
                assert widget.winfo_width() > 20
                assert widget.winfo_height() > 10
                assert (
                    widget.winfo_rootx() + widget.winfo_width()
                    <= manager.window.winfo_rootx() + manager.window.winfo_width()
                )
                assert (
                    widget.winfo_rooty() + widget.winfo_height()
                    <= manager.window.winfo_rooty() + manager.window.winfo_height()
                )
    finally:
        if not app.closed:
            app.close()
            deadline = time.monotonic() + 10
            while not app.closed:
                root.update()
                assert time.monotonic() < deadline
                time.sleep(0.01)
    assert not errors, errors


if __name__ == "__main__":
    run(sys.argv[1])
