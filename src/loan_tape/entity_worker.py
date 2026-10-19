"""Isolated optional matcher. Invoked by file path; imports no Loan Tape environment."""

import hashlib
import importlib
import importlib.metadata
import io
import json
import os
import random
import sys
import tempfile
from pathlib import Path
from typing import Any


def execute(request: dict[str, Any], folder: Path) -> dict[str, Any]:
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("Entity matching requires Python 3.12.")
    packages = sorted(
        (d.metadata["Name"].lower(), d.version) for d in importlib.metadata.distributions()
    )
    if packages != [tuple(pair) for pair in request["runtime_packages"]]:
        raise RuntimeError(
            "Optional runtime packages changed after validation. Rerun runtime setup."
        )
    for name, version in (("dedupe", "3.0.3"), ("BTrees", "6.4")):
        if importlib.metadata.version(name) != version:
            raise RuntimeError(f"Expected {name} {version}; rerun optional runtime setup.")
    dedupe = importlib.import_module("dedupe")
    numpy = importlib.import_module("numpy")
    random.seed(42)
    numpy.random.seed(42)
    records = {int(key): value for key, value in request["records"].items()}
    before = json.dumps(records, sort_keys=True)
    variables = [
        getattr(dedupe.variables, f["comparator"])(str(f["column"])) for f in request["features"]
    ]
    labels = {
        kind: [
            (records[p["left"]], records[p["right"]])
            for p in request["labels"]
            if p["label"] == kind
        ]
        for kind in ("match", "distinct")
    }
    training = io.StringIO()
    dedupe.serializer.write_training(labels, training)
    training.seek(0)
    matcher = dedupe.Dedupe(variables, num_cores=1, in_memory=True)
    matcher.classifier.set_params(n_jobs=1)
    matcher.prepare_training(
        records, training_file=training, sample_size=1500, blocked_proportion=0.9
    )
    matcher.train(recall=1.0, index_predicates=True)
    pairs = list(matcher.pairs(records))
    candidates = []
    groups = []
    # No blocked pairs is an explicit zero-candidate outcome, not an engine fallback.
    if pairs:
        scores = matcher.score(iter(pairs))
        scored = {
            tuple(sorted(int(v) for v in item["pairs"])): float(item["score"]) for item in scores
        }
        for left, right in pairs:
            key = tuple(sorted((left[0], right[0])))
            candidates.append(
                {
                    "rows": list(key),
                    "score": scored.get(key),
                    "scoring_status": "scored" if key in scored else "not_returned_by_dedupe",
                }
            )
        groups = [
            {"rows": [int(row) for row in ids], "scores": [float(v) for v in values]}
            for ids, values in matcher.cluster(scores, request["threshold"])
        ]
        del scores  # The isolated worker temp directory owns any Dedupe memmap.
    model = folder / "model.bin"
    with model.open("xb") as stream:
        matcher.write_settings(stream)
    if json.dumps(records, sort_keys=True) != before:
        raise RuntimeError("Matching mutated source-derived records.")
    return {
        "name": "dedupe",
        "version": "3.0.3",
        "python": sys.version,
        "packages": sorted(
            (d.metadata["Name"], d.version) for d in importlib.metadata.distributions()
        ),
        "settings": {
            "seed": 42,
            "num_cores": 1,
            "classifier_n_jobs": 1,
            "recall": 1.0,
            "index_predicates": True,
            "sample_size": 1500,
            "blocked_proportion": 0.9,
            "threshold": request["threshold"],
            "automatic_text_preprocessing": False,
        },
        "model_sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
        "pairs": sorted(candidates, key=lambda p: p["rows"]),
        "groups": groups,
    }


def main() -> None:
    folder = Path(sys.argv[1]).resolve()
    for key in ("TEMP", "TMP", "TMPDIR"):
        os.environ[key] = str(folder)
    tempfile.tempdir = str(folder)
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[key] = "1"
    try:
        request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
        result = execute(request, folder)
    except Exception as error:
        result = {"error": f"{type(error).__name__}: {error}"}
    (folder / "result.json").write_text(json.dumps(result, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main()
