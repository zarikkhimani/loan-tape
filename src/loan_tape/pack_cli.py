"""Explicit pack management commands, separate from the desktop analysis workflow."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from loan_tape.pack_format import PackError, load_pack
from loan_tape.packs import PackStore


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="loan-tape packs",
        description="Manage local dictionary packs. All packs start inactive.",
        epilog="Activation affects the dictionary catalog only. Desktop checks do not use packs yet.",
    )
    parser.add_argument("--packs-dir", type=Path, default=Path("packs"))
    parser.add_argument("--state-dir", type=Path, default=Path(".artifacts/packs"))
    parser.add_argument("--profile", default="default", help="Independent activation profile.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List available and activated packs, including errors.")
    validate = commands.add_parser("validate", help="Validate a folder without activating it.")
    validate.add_argument("directory", type=Path)
    for name in ("show", "activate", "deactivate"):
        command = commands.add_parser(name, help=f"{name.capitalize()} a pack by ID.")
        command.add_argument("pack_id")
    commands.add_parser("catalog", help="Print the exact active pack definitions and fingerprints.")
    search = commands.add_parser("search", help="Search fields in the active profile.")
    search.add_argument("query")
    args = parser.parse_args(argv)
    store = PackStore(args.packs_dir, args.state_dir)
    try:
        if args.command == "validate":
            pack = load_pack(args.directory)
            print(f"Valid: {pack.id} {pack.version}; {len(pack.fields)} fields; {pack.fingerprint}")
        elif args.command == "list":
            pins = {pin.id: pin for pin in store.pins(args.profile)}
            issues = False
            for active_pin in pins.values():
                try:
                    store.snapshot(active_pin)
                except PackError as error:
                    issues = True
                    print(f"ERROR active {active_pin.id}: {error}")
            seen = set()
            for entry in store.available():
                if entry.error:
                    issues = True
                    print(f"INVALID {entry.path.name}: {entry.error}")
                    continue
                assert entry.pack is not None
                pack = entry.pack
                seen.add(pack.id)
                current_pin = pins.get(pack.id)
                status = "inactive" if current_pin is None else "active"
                if current_pin is not None and current_pin.fingerprint != pack.fingerprint:
                    status = f"active snapshot {current_pin.version}; edited on disk - reactivate to update"
                print(f"{pack.id} {pack.version} [{status}] - {pack.name}")
            for pack_id in sorted(pins.keys() - seen):
                print(
                    f"{pack_id} {pins[pack_id].version} [active snapshot; source missing or invalid]"
                )
            if not seen and not pins and not issues:
                print("No packs found. Add pack folders to the packs directory.")
            print(f"Profile: {args.profile}. Current desktop inspection/checks are unaffected.")
            return 1 if issues else 0
        elif args.command == "show":
            pack = store.available_pack(args.pack_id)
            print(
                json.dumps(
                    {
                        "fingerprint": pack.fingerprint,
                        "files": {
                            name: json.loads(text.removeprefix("\ufeff"))
                            for name, text in pack.files
                        },
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
        elif args.command == "activate":
            pin = store.activate(args.pack_id, args.profile)
            print(
                f"Activated {pin.id} {pin.version} in {args.profile}; snapshot {pin.fingerprint}."
            )
            print("Definitions are available in this catalog. Desktop checks are unaffected.")
        elif args.command == "deactivate":
            changed = store.deactivate(args.pack_id, args.profile)
            print(
                f"{args.pack_id}: {'deactivated' if changed else 'already inactive'} in {args.profile}."
            )
        elif args.command == "catalog":
            catalog = store.catalog(args.profile)
            print(
                json.dumps(
                    {
                        "profile": catalog.profile,
                        "packs": [
                            {
                                "id": pack.id,
                                "version": pack.version,
                                "fingerprint": pack.fingerprint,
                                "sources": [asdict(s) for s in pack.sources],
                                "code_lists": [asdict(c) for c in pack.code_lists],
                                "fields": [asdict(f) for f in pack.fields],
                            }
                            for pack in catalog.packs
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
        elif args.command == "search":
            matches = store.catalog(args.profile).search(args.query)
            for match in matches:
                print(
                    f"{match.id} ({match.field.entity}, {match.field.data_type}) - {match.field.label}"
                )
                print(f"  {match.field.definition}")
            if not matches:
                print("No matching fields in this active profile.")
        return 0
    except (PackError, OSError) as error:
        print(f"Pack error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
