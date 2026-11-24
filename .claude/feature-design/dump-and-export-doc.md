# dump-and-export-doc: design

Spec: `claude-workspace/specs/gcg-toolkit/dump-and-export-doc/spec.md` (PersonalClaude workspace)

## Approach
`read_raw_dump` checks only `groups.json`, then reads each listed group's products and prices files with `read_text`. A dump interrupted part-way through its save has `groups.json` but not every group file, so the read raised a bare `FileNotFoundError`. It now checks every file it is about to read first and raises `NoData(Kind.PRICES, ...)` naming the dump and the missing file, like the not-stored case. A complete dump reads exactly as before. The example export gets `set_code` `BASIC` on `R-001` and its printing, and `BASIC` joins `reference.sets` as the doc says new sets appear there.

## Files and interfaces
- `tools/gundam_cards/store.py`: `read_raw_dump` raises `NoData` for a missing group file; docstring says so.
- `docs/catalog-export.example.json`: `R-001` and its printing carry `set_code` `BASIC`; a `BASIC` entry in `reference.sets` (kind `other`, no date).
- `shared/test_empty_dataset.py`, `tools/gundam_cards/tests/test_tcgcsv.py`: tests below. The reader's existing empty-dataset row (`NoData` prices) is unchanged: its empty answer did not change.

## Tests
- AC-1
  - a dump with `groups.json` and no `<group>_products.json` (unhappy): `NoData` of kind prices, message names the dump.
  - a dump with `groups.json` and no `<group>_prices.json` (unhappy): same.
  - a complete dump (happy): reads back as before (`test_a_saved_dump_reads_back_the_same`, existing).
- AC-2: `test_the_documented_example_export_is_a_valid_export_with_no_null` (existing) still passes; the card and printing set code is a stated way to check by reading the file (docs are not scanned by tests).

## Risks
- Contracts made stricter: none for callers; the CLI (`reparse-tcgplayer`, `price`) calls `read_raw_dump` only after `raw_dump_stamps` finds a stamp, and a `NoData` there is the same exception type it already handles for a missing dump.
