"""Synthetic library probes, executed only by the isolated Phase 1 runner.

These exercise candidate APIs and expose adaptation requirements. They are not an
application transformation engine or an entity-matching accuracy benchmark.
"""

import copy
import hashlib
import importlib
import io
import json
import platform
import random
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from importlib.metadata import distributions
from itertools import combinations
from pathlib import Path


def require(condition: object, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def text_repair(_folder: Path) -> dict[str, object]:
    ftfy = importlib.import_module("ftfy")
    settings = {
        "unescape_html": False,
        "remove_terminal_escapes": False,
        "fix_latin_ligatures": False,
        "fix_character_width": False,
        "uncurl_quotes": False,
        "fix_line_breaks": False,
        "fix_surrogates": False,
        "remove_control_chars": False,
        "normalization": None,
    }
    source = [
        "Caf\u00c3\u00a9 Holdings",
        "\u201cAcme\u201d &amp; Co\r\nUnit 1",
        "00001234567890123456",
    ]
    before = list(source)
    result = [ftfy.fix_text(value, **settings) for value in source]
    require(result[0] == "Caf\u00e9 Holdings", "Encoding repair failed.")
    require(result[1:] == source[1:], "Unselected text conventions changed.")
    require(source == before, "Text probe mutated its input.")
    return {
        "before": source,
        "after": result,
        "settings": settings,
        "constraint": "Repair is a reviewed proposal; pin every effective ftfy setting.",
    }


def fuzzy_suggestions(_folder: Path) -> dict[str, object]:
    process = importlib.import_module("rapidfuzz.process")
    scorer = importlib.import_module("rapidfuzz.fuzz_cpp")
    choices = ["Caf\u00e9 Industrial Supply", "Caf\u00e9 Ind Supply", "Canyon Mining"]
    before = list(choices)
    ranked = process.extract(choices[0], choices, scorer=scorer.WRatio, processor=None, limit=3)
    require(ranked[0][0] == choices[0] and ranked[0][1] == 100, "Exact ranking failed.")
    require(ranked[1][0] == choices[1], "Expected spelling candidate was not ranked second.")
    require(choices == before, "Suggestions mutated the source choices.")
    return {
        "scorer": "rapidfuzz.fuzz_cpp.WRatio",
        "processor": None,
        "ranked": ranked,
        "constraint": "Similarity is not entity confidence; replacements need literal approval.",
    }


def rule_matching(_folder: Path) -> dict[str, object]:
    datapatch = importlib.import_module("datapatch")
    config = {
        "borrower": {
            "normalize": False,
            "lowercase": False,
            "asciify": False,
            "options": [{"match": "Acme", "value": "ACME"}],
        }
    }
    lookup = datapatch.get_lookups(copy.deepcopy(config))["borrower"]
    require(lookup.get_value("Acme", default="Acme") == "ACME", "Approved mapping failed.")
    observed = lookup.get_value(" Acme ", default=" Acme ")
    require(observed == "ACME", "Recheck DataPatch whitespace semantics before selecting it.")
    values = ["Acme", " Acme ", "000001", "0", "", "N/A", "=1+1"]
    approved = {"Acme": "ACME"}
    exact = [approved.get(value, value) for value in values]
    require(exact[1:] == values[1:], "Literal rule sketch changed unapproved values.")
    return {
        "library_whitespace_result": observed,
        "literal_rule_example": exact,
        "constraint": "DataPatch trims even with normalize=False. Use an exact application-owned map.",
    }


def date_parsing(_folder: Path) -> dict[str, object]:
    dateparser = importlib.import_module("dateparser")
    settings = {
        "STRICT_PARSING": True,
        "PARSERS": ["absolute-time"],
        "PREFER_LOCALE_DATE_ORDER": False,
        "RELATIVE_BASE": datetime(2026, 1, 1, tzinfo=UTC),
    }
    dmy = dateparser.parse("03/04/2026", settings={**settings, "DATE_ORDER": "DMY"})
    mdy = dateparser.parse("03/04/2026", settings={**settings, "DATE_ORDER": "MDY"})
    require(dmy == datetime(2026, 4, 3), "Explicit DMY parse failed.")
    require(mdy == datetime(2026, 3, 4), "Explicit MDY parse failed.")
    require(dateparser.parse("March", settings=settings) is None, "Incomplete date was filled.")
    require(dateparser.parse("yesterday", settings=settings) is None, "Relative date was enabled.")
    return {
        "same_token_dmy": str(dmy),
        "same_token_mdy": str(mdy),
        "constraint": "Explicit conventions remain necessary; retain Loan Tape's date parser.",
    }


def header_aliases(_folder: Path) -> dict[str, object]:
    pandas = importlib.import_module("pandas")
    importlib.import_module("janitor")
    headers = ["Borrower Name", "Borrower-Name", "", "Loan ID"]
    rows = [["Caf\u00e9", "N/A", "0", "00001234567890123456"]]
    frame = pandas.DataFrame(rows, columns=headers, dtype=str)
    candidate = frame.clean_names(remove_special=True, strip_underscores="both")
    require(candidate.columns[0] == candidate.columns[1], "Expected header collision was absent.")
    require(candidate.columns[2] == "", "Expected empty-header candidate was absent.")
    require(frame.columns.tolist() == headers, "Source headers changed.")
    require(candidate.values.tolist() == rows, "Header cleanup coerced cell values.")
    return {
        "original_headers": headers,
        "candidate_headers": candidate.columns.tolist(),
        "constraint": "Use reviewed aliases only; preserve source positions, duplicates and blanks.",
    }


def entity_matching(folder: Path) -> dict[str, object]:
    dedupe = importlib.import_module("dedupe")
    numpy = importlib.import_module("numpy")
    btrees = importlib.import_module("BTrees.IFBTree")
    require(hasattr(btrees.IFBucket, "byValue"), "Dedupe requires the removed BTrees byValue API.")
    random.seed(42)
    numpy.random.seed(42)
    companies = [
        "Alpine",
        "Birch",
        "Canyon",
        "Delta",
        "Elm",
        "Falcon",
        "Granite",
        "Harbor",
        "Iris",
        "Juniper",
        "Kestrel",
        "Linden",
    ]
    records = {}
    groups = []
    for number, name in enumerate(companies):
        first, second = f"{number * 2 + 1:04}", f"{number * 2 + 2:04}"
        records[first] = {
            "name": f"{name} Industrial Holdings",
            "address": f"{number + 10} {name} Road",
        }
        records[second] = {
            "name": f"{name} Industrial Hldgs",
            "address": f"{number + 10} {name} Road",
        }
        groups.append((first, second))
    original = copy.deepcopy(records)
    labels = {
        "match": [(records[a], records[b]) for a, b in groups],
        "distinct": [(records[a[0]], records[b[0]]) for a, b in combinations(groups, 2)],
    }
    training = io.StringIO()
    dedupe.serializer.write_training(labels, training)
    training.seek(0)
    matcher = dedupe.Dedupe(
        [dedupe.variables.String("name"), dedupe.variables.String("address")],
        num_cores=1,
        in_memory=True,
    )
    matcher.classifier.set_params(n_jobs=1)
    matcher.prepare_training(records, training_file=training)
    matcher.train()
    clusters = list(matcher.partition(records, threshold=0.5))
    expected = {frozenset(pair) for pair in groups}
    require(
        {frozenset(ids) for ids, _ in clusters} == expected, "Unexpected synthetic entity groups."
    )
    model = folder / "synthetic-model.bin"
    with model.open("wb") as stream:
        matcher.write_settings(stream)
    with model.open("rb") as stream:
        restored = dedupe.StaticDedupe(stream, num_cores=1, in_memory=True)
    replayed = list(restored.partition(records, threshold=0.5))
    require({frozenset(ids) for ids, _ in replayed} == expected, "Model replay changed groups.")
    require(records == original, "Matching changed or deleted source records.")
    return {
        "input_records": len(records),
        "candidate_groups": len(clusters),
        "matching_labels": len(labels["match"]),
        "distinct_labels": len(labels["distinct"]),
        "model_replay": True,
        "model_sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
        "constraint": "Training-fixture smoke only, not independent accuracy; no loan merging.",
    }


CASES: tuple[tuple[str, Callable[[Path], dict[str, object]]], ...] = (
    ("ftfy", text_repair),
    ("rapidfuzz", fuzzy_suggestions),
    ("datapatch", rule_matching),
    ("dateparser", date_parsing),
    ("pyjanitor", header_aliases),
    ("dedupe", entity_matching),
)


def main(folder: Path, profile: str) -> int:
    require(sys.version_info[:2] == (3, 12), "Probe interpreter must be Python 3.12.")
    require(profile in {"base", "dedupe"}, "Unknown compatibility profile.")
    package_inventory = []
    for dist in sorted(distributions(), key=lambda item: item.metadata["Name"].lower()):
        metadata = dist.metadata
        licenses = []
        for file in dist.files or ():
            if "license" in file.name.lower() or file.name.upper() == "NOTICE":
                path = Path(str(dist.locate_file(file)))
                if path.is_file():
                    licenses.append(
                        {"file": str(file), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                    )
        package_inventory.append(
            {
                "name": metadata["Name"],
                "version": dist.version,
                "license_expression": metadata.get("License-Expression"),
                "license": metadata.get("License"),
                "license_classifiers": [
                    value
                    for value in metadata.get_all("Classifier", [])
                    if value.startswith("License ::")
                ],
                "license_files": licenses,
            }
        )
    cases: list[dict[str, object]] = []
    for name, case in CASES:
        if (name == "dedupe") != (profile == "dedupe"):
            continue
        try:
            evidence = case(folder)
            cases.append({"engine": name, "status": "passed", "evidence": evidence})
        except Exception as error:
            cases.append(
                {"engine": name, "status": "failed", "error": f"{type(error).__name__}: {error}"}
            )
        print(f"{name}: {cases[-1]['status']}", flush=True)
    report = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "packages": package_inventory,
        "checks": cases,
    }
    (folder / "cases.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return 0 if all(case["status"] == "passed" for case in cases) else 1


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), sys.argv[2]))
