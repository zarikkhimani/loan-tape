# Dictionary packs

Dictionary packs are a separate, local backend for storing, inspecting, and selecting field definitions. All packs start **inactive**. Activation makes a saved copy of a pack available in a named catalog profile. File intake, workbook inspection, ad-hoc column checks, source files, and saved data-set selections remain independent. The explicit Excel **Define column** action consults active fields in the `default` profile.

This release supports definitions, expected data types, code lists, missing-data metadata, source references, search, activation/deactivation, and exact-content snapshots. The desktop manager also supports reviewing and selecting packs. The separate column-definition editor can explicitly map a saved Excel data-set column to one active field. Packs do **not** automatically match labels, run financial checks, interpret source values, or normalize data.

## Desktop manager

Open **Dictionary packs** from the main **Files** tab. Opening, searching, refreshing, and changing the viewed version do not activate anything.

1. Select a pack to search its fields and read expected types, definitions, units, context, permitted codes, missing-data reasons, and source references. **Pack and sources** shows pack metadata, both versions, fingerprints, source information, and any errors.
2. Use **Viewing** to switch between **Editable files** and the saved **Active version**. Active packs initially show their saved version. An unavailable version displays an error and no substitute fields.
3. Choose **Activate pack** to select the displayed editable content. After editing its files, refresh and review **Editable files**, then choose **Update active version**. If the files changed after the last refresh, activation fails and asks you to refresh again.
4. Choose **Deactivate** to remove the pack from the loaded profile. Source files and earlier snapshots remain available. A pack with a missing source or broken saved version can still be deactivated.

The manager opens the `default` profile. To use another selection, choose an existing profile or type a lowercase name (for example, `research`), then select **Load / refresh**. Names permit letters, digits, dots, underscores, and hyphens. Merely typing a name disables activation controls until that profile has loaded; a new profile is saved only when its selection changes. Reopening the manager returns to `default`, with saved selections preserved.

The **Packs folder** location is selectable/copyable. Add or edit the four JSON files in a folder there, then refresh. You can also use the in-app editor described below. Document importing is not implemented. Pack folders are found relative to the working directory, matching the CLI defaults; the project launcher uses the project folder. State stays under `.artifacts/packs/`. Switching a catalog profile has no effect on file checks or saved data set setup.

Loading and saving run in the background. Closing the dialog waits for an active operation; exiting Loan Tape also waits for it. Invalid packs, duplicate IDs, missing sources, damaged snapshots, and invalid profile files remain visible. A failed profile load clears the previous view instead of presenting it as the new profile.

## Create and edit inside the app

- **New pack** starts an empty local dictionary. Fill in its ID, name, version, description, and asset classes, then add fields.
- **Make a copy** copies the version currently shown by **Viewing**. Give it a unique ID and name. Its original definitions, code lists, and source records remain available, and the copied pack identity/fingerprint is recorded.
- **Edit pack** edits the editable files for the selected pack. Its ID stays fixed. Use **Save as a copy** if you need a different identity or want to keep a draft after an external edit conflict.

The **Fields** tab supports adding/removing fields and changing their IDs, names, meanings, expected types, entities, units, required/blank settings, aliases, context, notes, code-list selections, and permitted missing codes. Lists use one value per line. **Not specified / conditional** remains distinct from Yes and No. A category field needs an existing allowed-code list; permitted missing codes must belong to the selected missing-reason list. Create allowed-value lists in the same draft before selecting them for a field.

**Apply field to draft** validates and keeps a field in the open draft. Switching fields or selecting **Save pack** also applies pending field edits. Saving validates the entire dictionary and closes the editor on success; no activation is changed. Review **Editable files** in the manager and activate/update separately when ready. Saving retains exact earlier files in `packs/.history/<pack-id>-<unique-id>/`. These backups are local recovery files, excluded from Git and builds, and are never automatically deleted.

Changed field definitions receive a local-authoring source reference. Earlier field references are marked as background for the earlier definition, so an edited meaning is not presented as a direct definition from the original standard. Unchanged copied fields retain their original references. Changed code-list contents similarly receive a local authorship citation; earlier citations become background. Editing citations alone does not reattribute unchanged code meanings. Automatic authorship and copied-pack source records and citations are displayed but protected from editing/removal in the app.

If files changed while the editor was open, saving fails and leaves the draft available. **Save as a copy** keeps that work under another ID; alternatively close and reopen to edit the latest files. The editor refuses in-place changes to linked folders/files or folders containing more than the four dictionary files. Make a custom copy to preserve those other files.

Closing an unsaved editor asks before discarding changes, including pending source/value/citation dialogs and when closing the manager or the application. During a pack-file save, the app stays open; close again when the save finishes. Save errors keep the editor and draft open.

A save stages and validates all four files, preserves the old folder, and publishes the new folder. If publication fails normally, the old folder is restored. A process crash between the directory moves can leave the visible folder missing; the older files remain under `.history/` for manual recovery. A failed restore reports the backup and draft locations. Active catalog snapshots remain independent of this recovery process. Temporary `.draft-*` folders are also excluded from Git and builds. Do not remove a temporary folder or the store lock while a save is running.

### Sources, allowed values, and citations

- **Sources → Add source / Edit** records an ID, title, source version, location/URL, and optional SHA-256 hash. The hash must be 64 lowercase hexadecimal characters. Locations are citation text only: the app does not open them or verify the referenced file. An existing source keeps its ID; add a new record for a different identity.
- **Allowed values → Add list / Edit** manages a list ID and its exact values, names, and definitions. Use **Add value**, fill the row, and **Apply row**; switching rows or applying the dialog also keeps a valid pending row. Codes stay literal text, including leading zeros, spaces, and line breaks. Duplicate codes and empty lists fail validation. Existing list IDs stay fixed.
- Use the list's **Citations** tab, or **Fields → Citations → Edit citations**, to link source IDs to page/cell/section locators. Add source records first. New local definitions receive an automatic authorship citation; external citations may be added alongside it.
- **Apply to pack draft** validates the dialog and updates only the open pack draft. **Cancel** discards dialog edits after confirmation when needed. **Save pack** publishes the complete draft; activation stays unchanged.
- A source that is still cited or a list that is selected by a field cannot be removed. Change those citations/selections first. Removing a code used by a field's permitted missing codes is also blocked until the field is updated. Deleting a draft row/list never silently rewrites other definitions.

Source records can be authored before fields or lists. An unfinished draft may be empty, but saving a pack still requires at least one complete field or allowed-value list. This is manual dictionary authoring; document import and automatic dictionary extraction are not implemented.

## Command-line quick start

Run these commands from the project directory, one at a time:

```powershell
.\run.bat packs list
.\run.bat packs validate .\packs\example-loans
.\run.bat packs show example.loans
.\run.bat packs activate example.loans
.\run.bat packs search balance
.\run.bat packs catalog
.\run.bat packs deactivate example.loans
```

Use `esma.reporting` in place of `example.loans` to activate or deactivate the ESMA reference pack. `show` displays the editable files on disk; `catalog` displays the saved active definitions. Both are read-only. `list` shows when an active pack differs from the files on disk, or when its source folder is missing or invalid. Invalid packs and broken snapshots produce messages and a nonzero command exit code.

Activating an already active, unchanged pack is safe and does not add a duplicate. After an edit, running `activate` again explicitly replaces that profile's selection with a new snapshot. Changing just whitespace also changes the content fingerprint. Increment the pack version when publishing a meaningful change; a same-version edit is still detected by the fingerprint.

Profiles keep selections independent:

```powershell
.\run.bat packs --profile research activate esma.reporting
.\run.bat packs --profile research list
.\run.bat packs --profile research catalog
.\run.bat packs --profile research deactivate esma.reporting
```

Options go **before** the action. Defaults are `--packs-dir packs`, `--state-dir .artifacts/packs`, and `--profile default`, relative to the current working directory. Use explicit paths when running from another directory. The module entry point `python -m loan_tape.pack_cli` exposes the same commands. The installed application can use any external packs directory; starter folders are project reference content, not automatically installed or activated resources.

## Add or edit a pack

Copy `packs/example-loans/` into a new immediate subfolder of `packs/`. Give it a new manifest ID, name, description, and version. Replace its synthetic definitions and sources with reviewed content, then validate the folder. Activate it explicitly when ready. Adding a folder alone does not alter any profile.

Each pack has four UTF-8 JSON files (a UTF-8 BOM is accepted):

| File | Shape | Purpose |
| --- | --- | --- |
| `pack.json` | Object | Identity, format version, pack version, descriptive scope |
| `sources.json` | List of objects | Source titles, source versions, locations, optional hashes |
| `code_lists.json` | List of objects | Named lists of permitted values and explanations |
| `fields.json` | List of objects | Financial meanings and expected data representations |

Each file is limited to 2 MiB. Empty lists are permitted for sources/code lists/fields when their references remain valid, but a pack must have at least one field or code list. Each field and code list must cite at least one declared source, including a project-authored source for custom definitions. Extra JSON files, unsupported keys, duplicate JSON keys, duplicate IDs/codes, missing references, and unsupported format versions fail validation. Descriptive files such as README.md may accompany the four files. Other files are never executed or imported. File links escaping the pack directory are rejected. Source URIs are reference text; the loader never fetches them.

### Manifest

`pack.json` requires exactly:

- `format_version`: integer `1`, the version of the backend contract.
- `id`: stable lowercase ID, for example `custom.corporate`. Letters, digits, dots, underscores, and hyphens are permitted, with a letter first and no adjacent separators; maximum 100 characters.
- `version`: `major.minor.patch`, for example `1.0.0`. Separate from the source document's version.
- `name` and `description`: non-empty display text. State whether this is a synthetic example, reviewed subset, or complete source mapping.
- `asset_classes`: a non-empty list of descriptive scope labels. These do not automatically determine applicability to a data set.

Only one available directory per pack ID is supported. Duplicate IDs are reported for all conflicting folders and cannot be activated, even if their versions differ. Give a custom variant a new ID. Multiple packs may define similar fields; they retain separate identities and are not automatically merged or ranked.

### Sources and code lists

A source requires `id`, `title`, `version`, and `uri` (all non-empty text, with `id` following the ID rules). Optional `sha256` is a lowercase 64-character SHA-256 fingerprint of the reference file. It records provenance; source documents are not read or re-verified by the loader. `supplied:` references in the ESMA starter identify the user's original files, which remain external to these pack folders.

A code list requires `id`, `codes`, and `references`. Each code requires non-empty `value`, `label`, and `definition` strings. Codes preserve spelling and case. A reference is `{"source": "source-id", "locator": "page, field code, section, or sheet/cells"}`. It must resolve within that pack's source list.

### Fields

Required field attributes:

| Attribute | Meaning |
| --- | --- |
| `id` | Stable field ID within this pack |
| `label` | Human-readable name |
| `definition` | Precise financial meaning |
| `entity` | `borrower`, `loan`, `holding`, `tranche`, `portfolio`, or `report` |
| `data_type` | `identifier`, `text`, `integer`, `decimal`, `date`, `boolean`, or `category` |
| `references` | At least one source reference with a locator |

Optional field attributes:

| Attribute | Meaning/default |
| --- | --- |
| `aliases` | Search terms; default `[]`. Never confirmed column mappings. |
| `context` | Required interpretation context such as currency, units, date convention, or whole-loan scope; default `[]` |
| `unit` | Descriptive unit or `null` when unspecified; default `null` |
| `required` | `true`, `false`, or `null` when unspecified/conditional; default `null` |
| `blank_allowed` | `true`, `false`, or `null` when unspecified/conditional; default `null` |
| `code_list` | Local code-list ID for `category` fields; required for categories, forbidden for other types |
| `missing_code_list` | Local code-list ID describing missing-data reasons; default `null` |
| `missing_codes` | Permitted entries from `missing_code_list`; default `[]` |
| `notes` | Applicability details, qualifications, and source limitations; default `null` |

Null means unspecified, not false or zero. Required presence and permission for a blank are separate metadata concepts. The catalog does not yet evaluate either. It does not collapse blank, zero, invalid, unreadable, or explicit missing-data values. Expected types describe meaning; a future interpreter will need explicit conventions before parsing CSV text or Excel values.

Public catalog field IDs use `pack-id:field-id`, such as `example.loans:principal_balance`. Identical labels and aliases across packs return multiple search results. They never override each other. Field lookup requires the full ID.

## Activation and reproducibility

State lives under `.artifacts/packs/`, which is ignored by Git:

- `profiles/<profile>.json` contains active pack IDs, versions, and fingerprints.
- `snapshots/<fingerprint>.json` retains the exact four source-file texts used during activation.

Profiles are atomically replaced under a store-wide writer lock so simultaneous updates fail explicitly instead of losing changes. Snapshots are content-addressed and checked against the saved fingerprint whenever loaded. These are local reproducibility records, not a protected audit archive or backup. Preserve them if future results refer to them. No automatic snapshot deletion occurs.

An edited, removed, or broken source folder does not change a previously activated snapshot. `list` makes discrepancies visible. A missing or altered active snapshot causes a clear catalog error; it does not quietly fall back to the editable folder. Deactivation can remove a selection even if its source folder or snapshot is missing/corrupt. Malformed profile files require repair and are never reset silently.

After an interrupted write, an abandoned `.activation.lock` may remain. Confirm that no pack update is running before removing that one file. Read-only commands do not acquire a write lock or create state.

## Starter content and current boundaries

- `example.loans` is a four-field synthetic authoring template. Its definitions and required-value choices are examples, not industry requirements.
- `esma.reporting` is a five-field/two-code-list selection based on the supplied reporting-instructions PDF and end-of-day/rejection workbooks. Source file hashes, document versions, page/cell references, and project-authored summaries are recorded. It is not the complete ESMA corporate-loan dictionary or a current regulatory compliance pack. The version `0.1.0` describes our selection, not ESMA's release.

The ESMA pack distinguishes tranche liabilities from collateral balances. Its ND4 code describes a category that requires a date in the original reporting format; the backend does not parse or validate that token. Its currency instructions remain descriptive and never cause a conversion.

General pack-driven check execution, inheritance, normalization, spreadsheet editing, and user-authored cross-source mapping profiles are later features. The bundled Warehouse Model exact-layout profile is separate from dictionary packs and does not create column definitions. The implemented Excel column definitions are explicit per-source/per-data-set bindings with simple mapping-specific rule metadata; saving them does not execute those rules. `checks.json`, `extends`, and executable expressions are unsupported and fail clearly if placed in the JSON contract. Edit a custom copy under a new ID and select the desired packs in a profile; there is no implicit precedence between them.

## Date field pack

`loan.dates` adds four project-authored definitions: closing date, original maturity,
current maturity and reporting date. It is not issued by SIFMA or another market association. Required
context and qualifications remain visible, required/blank permissions are unspecified,
and aliases never establish mappings. It starts inactive like the other packs.
See [DATE_FIELDS.md](DATE_FIELDS.md).

The separate [date parser](DATES.md) accepts an explicit parsing profile. Activating
this pack does not run the parser or modify existing column checks. Parsing policies
remain separate from the four-file dictionary contract; no `checks.json` or executable
expressions are introduced.

## Rate field pack

`loan.rates` is a project-authored Phase 1 dictionary for rate type, reference-rate
identity/method/tenor, contractual spread, supplied reference-rate observations,
stated/cash/PIK/total coupons, reference-rate and coupon floors/caps, supplied yields,
yield measures, and rate dates. It distinguishes U.S. Prime from an
agreement-defined Base Rate or ABR and does not infer SOFR tenor or method. It starts
inactive, and its aliases never establish mappings.

The separate [rate parser](RATES.md) applies an explicit versioned profile to one
preserved value at a time. Activating the pack does not parse values, infer units, map
columns, retrieve benchmarks, calculate rates or change existing checks. Parser policy
remains outside the four-file dictionary contract.

## Backend API and validation

`loan_tape.pack_format.load_pack()` returns immutable definitions and a content fingerprint. `loan_tape.packs.PackStore` supports `available`, `available_pack`, `activate`, `deactivate`, `pins`, `snapshot`, and `catalog`. A catalog supports `fields`, `search`, and `get_field`. No pack modules are imported by the current inspection or checking services.

`tests/test_packs.py` covers contracts, activation/deactivation, independent profiles, editable-source isolation, snapshot integrity, ID conflicts, corrupt state, atomic failures, and command-line use. `tests/test_pack_authoring.py` and native editor scenarios cover draft creation, attribution, stale edits, backups, publication/restore failures, unsaved-close protection, and unchanged activations. `tests/test_pack_content.py` and native content-dialog scenarios cover source and citation edits, literal code preservation, broken-link prevention, unchanged activations, canceled drafts, and minimum/scaled window layouts. `scripts/smoke_packs.py` verifies the lifecycle and field/source/code-list editing through an isolated installed wheel. Run `check.bat` for the full project checks.
