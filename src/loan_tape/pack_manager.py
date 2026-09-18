"""Read-only pack management views, separate from file analysis and activation writes."""

from dataclasses import dataclass
from pathlib import Path
from threading import Event

from loan_tape.pack_format import Field, Pack, PackError, Reference
from loan_tape.packs import PackPin, PackStore


@dataclass(frozen=True)
class ManagedPack:
    key: str
    pack_id: str | None
    name: str
    path: Path | None
    editable: Pack | None
    pin: PackPin | None
    active: Pack | None
    source_error: str | None = None
    active_error: str | None = None

    @property
    def status(self) -> str:
        if self.active_error:
            return "Active — saved version unavailable"
        if self.source_error:
            return "Active — source needs repair" if self.pin else "Invalid pack"
        if self.pin:
            if self.editable is None:
                return "Active — source missing"
            if self.editable.fingerprint != self.pin.fingerprint:
                return "Active — edits available"
            return "Active"
        return "Inactive"

    @property
    def can_activate(self) -> bool:
        return (
            self.editable is not None
            and self.source_error is None
            and (self.pin is None or self.pin.fingerprint != self.editable.fingerprint)
        )


@dataclass(frozen=True)
class PackInventory:
    rows: tuple[ManagedPack, ...]
    profiles: tuple[str, ...]
    source_error: str | None = None


def inspect_packs(store: PackStore, profile: str, cancelled: Event | None = None) -> PackInventory:
    """Retain active selections even when editable folders or snapshots are broken."""
    pins = {pin.id: pin for pin in store.pins(profile, cancelled)}
    active, errors = {}, {}
    for pin in pins.values():
        try:
            active[pin.id] = store.snapshot(pin, cancelled)
        except PackError as error:
            errors[pin.id] = str(error)
    source_error = None
    try:
        entries = store.available(cancelled)
    except (PackError, OSError) as error:
        entries = ()
        source_error = str(error)
    rows = []
    seen = set()
    for entry in entries:
        pack = entry.pack
        pack_id = pack.id if pack else None
        seen.add(pack_id)
        rows.append(
            ManagedPack(
                key=str(entry.path),
                pack_id=pack_id,
                name=pack.name if pack else entry.path.name,
                path=entry.path,
                editable=pack,
                pin=pins.get(pack_id) if pack_id else None,
                active=active.get(pack_id) if pack_id else None,
                source_error=entry.error,
                active_error=errors.get(pack_id) if pack_id else None,
            )
        )
    for pack_id, pin in pins.items():
        if pack_id not in seen:
            saved = active.get(pack_id)
            rows.append(
                ManagedPack(
                    key=f"active:{pack_id}",
                    pack_id=pack_id,
                    name=saved.name if saved else pack_id,
                    path=None,
                    editable=None,
                    pin=pin,
                    active=saved,
                    active_error=errors.get(pack_id),
                )
            )
    profiles = {profile, *store.profiles(cancelled)}
    return PackInventory(tuple(rows), tuple(sorted(profiles)), source_error)


def references_text(pack: Pack, references: tuple[Reference, ...]) -> str:
    sources = {source.id: source for source in pack.sources}
    return "\n\n".join(
        f"{sources[ref.source].title} ({sources[ref.source].version})\n"
        f"{ref.locator}\n{sources[ref.source].uri}"
        for ref in references
    )


def field_text(pack: Pack, field: Field) -> str:
    def choice(value: bool | None) -> str:
        return "Not specified / conditional" if value is None else "Yes" if value else "No"

    lines = [
        field.label,
        f"{pack.id}:{field.id}",
        "",
        field.definition,
        "",
        f"Expected type: {field.data_type}",
        f"Entity: {field.entity}",
        f"Unit: {field.unit or 'Not specified'}",
        f"Required: {choice(field.required)}",
        f"Blank allowed: {choice(field.blank_allowed)}",
        f"Aliases: {', '.join(field.aliases) or 'None'}",
        f"Interpretation needs: {', '.join(field.context) or 'Not specified'}",
    ]
    if field.notes:
        lines.extend(["", field.notes])
    code_lists = {item.id: item for item in pack.code_lists}
    for title, list_id in (
        ("Allowed values", field.code_list),
        ("Permitted missing-data reasons", field.missing_code_list),
    ):
        if list_id:
            codes = code_lists[list_id]
            lines.extend(["", f"{title} ({list_id})"])
            values = [
                code
                for code in codes.codes
                if title == "Allowed values" or code.value in field.missing_codes
            ]
            lines.extend(f"{code.value} — {code.label}: {code.definition}" for code in values)
            if not values:
                lines.append("None permitted for this field.")
            lines.extend(["", references_text(pack, codes.references)])
    lines.extend(["", "Field sources", references_text(pack, field.references)])
    return "\n".join(lines)


def overview_text(row: ManagedPack, pack: Pack | None, view: str) -> str:
    lines = [
        row.name,
        row.status,
        "",
        f"Pack ID: {row.pack_id or 'Unavailable'}",
        f"Editable version: {row.editable.version if row.editable else 'Unavailable'}",
        f"Active version: {row.pin.version if row.pin else 'None'}",
        f"Folder: {row.path or 'No matching readable source folder'}",
    ]
    for error in (row.source_error, row.active_error):
        if error:
            lines.extend(["", error])
    lines.extend(["", f"Viewing: {view}"])
    if pack:
        lines.extend(
            [
                "",
                pack.description,
                "",
                f"Asset classes: {', '.join(pack.asset_classes)}",
                f"{len(pack.fields)} fields · {len(pack.code_lists)} code lists",
                "",
                f"Content fingerprint: {pack.fingerprint}",
                "",
                "Sources",
            ]
        )
        for source in pack.sources:
            lines.extend(
                [
                    "",
                    f"{source.title} ({source.version})",
                    source.uri,
                    f"Source fingerprint: {source.sha256 or 'Not supplied'}",
                ]
            )
    else:
        lines.extend(["", "This version is unavailable. No substitute definitions are shown."])
    return "\n".join(lines)
