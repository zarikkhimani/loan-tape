"""Native Tk borrower review scenarios with controlled engine timing."""

import json
import os
import sys
import time
import tkinter as tk
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path

from text_cleanup_support import prepare

from loan_tape import entity_ui
from loan_tape.column_definitions import remove_column_definition
from loan_tape.entities import EntityRun, PairLabel, bounded, labels_payload, validate_labels
from loan_tape.entity_ui import EntityWindow
from loan_tape.workers import WorkerGroup


def main():
    scenario, work = sys.argv[1], Path(sys.argv[2])
    os.chdir(work)
    _, source, _, table, store = prepare(work, [f"Borrower {i // 2}" for i in range(24)])
    root = tk.Tk()
    root.withdraw()
    workers = WorkerGroup()
    jumps = []
    window = EntityWindow(
        root, source, table, store, lambda: table, lambda *args: jumps.append(args), workers
    )
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)

    def pump(until, limit=15):
        deadline = time.monotonic() + limit
        while not until():
            root.update()
            assert time.monotonic() < deadline, window.status.get()
            time.sleep(0.01)
        root.update()
        assert not errors, errors

    window.feature_list.selection_set(0)
    window.prepare_button.invoke()
    pump(lambda: not window.busy)
    assert window.population is not None
    assert len(window.pairs) == 276
    assert len(window.grid.get_children()) == 50 and not window.labels
    window.next.invoke()
    assert window.offset == 50
    window.previous.invoke()
    window.grid.selection_set("0")
    root.update()
    window.reviewer.set("Synthetic UI reviewer")
    window.reason.set("Reviewed fictional borrower pair")
    window.same_button.invoke()
    assert window.labels[(2, 3)].label == "match"
    window.grid.selection_set("0")
    root.update()
    window.jump_selected()
    assert jumps[-1] == (table, 1, 2)
    window.view.set("Excluded rows")
    window.change_page(0)
    assert len(window.grid.get_children()) == 1

    if scenario == "mapping-change":
        remove_column_definition(table, 1)
        pump(lambda: window.invalid)
        assert str(window.train_button["state"]) == "disabled"
    else:
        pairs = [(row, row + 1) for row in range(2, 26, 2)]
        now = datetime.now(UTC).isoformat()
        window.labels = {(a, b): PairLabel(a, b, "match", "R", "Fixture", now) for a, b in pairs}
        window.labels.update(
            {
                (a[0], b[0]): PairLabel(a[0], b[0], "distinct", "R", "Fixture", now)
                for a, b in combinations(pairs, 2)
            }
        )
        window.representative.set(True)
        entity_ui.runtime_python = lambda: Path(sys.executable)

        def train(population, labels, threshold, representative, guard, *, cancelled):
            validate_labels(population, labels)
            guard()
            if scenario == "shutdown":
                assert cancelled.wait(10)
                raise ValueError("Cancelled")
            return EntityRun(
                bounded(
                    {
                        "population": population.to_dict(),
                        "labels": labels_payload(labels),
                        "engine": {
                            "groups": [{"id": "group-1", "rows": [2, 3], "scores": [0.9, 0.9]}],
                            "unclustered_rows": list(range(4, 26)),
                        },
                    }
                )
            ), work / "run.json"

        entity_ui.train_entities = train
        window.train()
        if scenario == "shutdown":
            assert window.busy
            window.close()
            workers.cancel_reads()
            pump(lambda: not workers.active_names())
        else:
            pump(lambda: not window.busy)
            assert window.run is not None and not window.decisions
            window.grid.selection_set("0")
            root.update()
            window.approve_button.invoke()
            assert window.decisions == {"group-1": "approve"}
            output = work / "review.json"
            entity_ui.filedialog.asksaveasfilename = lambda **_: str(output)
            window.save()
            pump(lambda: not window.busy)
            assert json.loads(output.read_text())["relationships"][0]["source_rows"] == [2, 3]
            window.threshold.set("0.7")
            assert window.run is None and not window.decisions
            window.feature_list.selection_clear(0, "end")
            window.features_changed()
            assert window.population is None and not window.labels
    window.close()
    pump(lambda: not workers.active_names())
    root.destroy()
    print(f"Entity native scenario passed: {scenario}")


if __name__ == "__main__":
    main()
