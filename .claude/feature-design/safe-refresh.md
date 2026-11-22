# safe-refresh: design

Spec: `claude-workspace/specs/gcg-toolkit/safe-refresh/spec.md` (Approved 2026-11-22, AC-1 widened the same day). Closes #14, #6, #4.

## Approach
**One page cache, in the dataset (AC-1).** A new resolver `store.pages_folder()` returns `data_out_dir() / "pages"`
(`$GCG_DATA_DIR/gundam_cards/pages/`), resolved on every call like the other folders. Every command that reads or writes Bandai's pages
(landing, product, list and detail) uses it: `refresh` (its fetcher and its `raw_dir`), `sync` (fetcher, `read_packages`,
`sync_printings`), `refetch`, and `reparse` (`sets_from_raw`, `load_source_pages`). `load_source_pages` and `packages_by_printing` default
to it. `raw_folder()` stays where it is (under `$GCG_TOOL_DATA_DIR` or the checkout) and now holds only the tcgcsv dumps and the
restrictions page. Nothing is copied from an old checkout cache: the first run fetches every listed detail page again (owner decision).
Moving the folder, rather than pointing `GCG_TOOL_DATA_DIR` at a shared place, is what the spec asks: the dataset is the one place
two checkouts already share.

**Count every field-level change (AC-2) and name it (AC-3).** `_comparable` is replaced by `changed_fields(old, new) -> tuple[str, ...]`,
a pure function that lists what differs between a stored card and its rebuild:
- card-level fields: every field of the card's dump except `printings`, `text_versions` and `fetched_at`, by name (`name`, `faq`,
  `keywords`, ...), plus `text` when the current wording differs;
- printing-level fields, for each printing in both: every field except `package_ids` (gaining a package is not a change), as
  `<printing id> <field>` (`GD01-001_p1 source_title`), and `<printing id> text` when the wording of that printing differs (from the text
  versions' printing ids);
- a stored printing missing from the rebuild, as `<printing id> missing` (gaining a printing is not a change; losing one is).

A card is changed when this list is not empty. `RefreshReport.changed` becomes `tuple[ChangedCard, ...]` (a frozen
`ChangedCard(number, fields)`), the guard counts `len(changed)` as before, and `format_report` adds one line per changed card,
`  changed GD01-001: name, GD01-001_p1 source_title`, after the anomaly-guard line. Dry run and real run share this code, so they
name the same cards and fields.

**Orphan pages (AC-4).** Before the shape check, the loaded pages are split: a page whose card number is in this run's listings or in
the stored catalog is kept; any other page is an orphan, left out of the build. `RefreshReport.orphans` holds their printing ids
(sorted), and the report prints `N orphan page(s), not added: ...` in both modes. Orphans never enter `changed`, `missed` or the guard.
A stored card missing from the listings is still kept by the filter and handled by the two-miss rule in `merge_catalog`.

## Files and interfaces
- `tools/gundam_cards/store.py`: `pages_folder() -> Path`; `load_source_pages` and `packages_by_printing` default to it;
  `raw_folder()` docstring says tcgcsv and restrictions only.
- `tools/gundam_cards/cli.py`: `refresh_fetcher()` caches in `pages_folder()`; `cmd_refresh`, `cmd_sync`, `cmd_refetch`, `cmd_reparse` use
  `pages_folder()` for the Bandai pages. `sync-tcgplayer`, `reparse-tcgplayer`, `price` and `sync-restrictions` are unchanged.
- `tools/gundam_cards/refresh.py`: `ChangedCard`, `changed_fields(old: CardModel, new: CardModel) -> tuple[str, ...]`,
  `RefreshReport.changed: tuple[ChangedCard, ...]`, `RefreshReport.orphans: tuple[PrintingId, ...]`, the orphan split, and the new
  report lines. `_comparable` is removed.
- Tests: `tools/gundam_cards/tests/test_safe_refresh.py` (new); `test_catalog_refresh.py` and `shared/test_tool_data_dir.py` updated
  for the new folder and the `changed` type.
- Docs: `tools/gundam_cards/design.md` (where the raw pages live, refresh step 7: changed cards and orphans), `docs/commands.md`
  (cache location note), `docs/tuning.md` (`ANOMALY_SHARE`: what counts as changed), `docs/wiki/Keeping-Data-Fresh.md` (cache
  location).

## Tests
Unit tests call `changed_fields` and `refresh_catalog` with `FakeBandai`; the commands run through `cli.main` with only the network faked
(the real `Fetcher` writes the cache), as in `shared/test_tool_data_dir.py`.
- AC-1
  - shared across checkouts (happy): `refresh` from checkout A (`GCG_TOOL_DATA_DIR`=A), then from checkout B, same `GCG_DATA_DIR`: the
    second run requests no detail page.
  - an older cache in a checkout is not read and not changed (unhappy): checkout B's own raw folder holds a detail page with another
    name; after the run the catalog has Bandai's name, and B's raw folder is byte-identical.
  - another dataset uses its own cache (both sides): a third run with `GCG_DATA_DIR` pointed elsewhere requests every detail page again and
    writes them under that folder's `gundam_cards/pages/`.
  - `sync`, `refetch`, `reparse` (happy, per command): each reads and writes pages only in `pages_folder()` and leaves the checkout's raw
    folder empty of Bandai pages (updated `shared/test_tool_data_dir.py` cases; `reparse` builds from pages placed in the dataset only).
  - tcgcsv and restrictions stay in `raw_folder()` (unchanged test).
  - empty state: `reparse` with no pages in the dataset still runs as before; `refetch` with no cached package list says to run `sync`
    (exit 2).
- AC-2
  - each family member is counted, one card each: `name` (card field), `faq` entry, current `text`, a printing's `source_title`, an older
    printing's wording, a printing missing from the rebuild.
  - not a change (both sides): gaining a printing; gaining a package on a printing; an unchanged card; `fetched_at` alone.
  - the guard uses the count: with 10 existing cards, one changed only in a printing's source title is 10% and refuses (the old code
    counted 0 and passed); `--allow-anomaly` still writes.
  - N changed reported as N: 3 of 50 cards changed in different families: the guard line says `3 changed`.
- AC-3
  - real run and dry run: same cards and fields in both reports, one `changed <number>: <fields>` line per card with the printing named
    for a printing-level field; the dry run writes nothing.
  - no changes: no `changed` lines.
- AC-4
  - an orphan page (card in no listing, not stored) is reported by printing id, is not in `cards.json`, and the card count is unchanged, in
    a real run and in a dry run; the run is not refused by it.
  - a stored card missing from the listings is not an orphan: it is missed (first miss), not in the orphan line.
  - a page of a listed card's unlisted printing is not an orphan.
  - empty state: with no orphans the orphan line is left out (asserted).

## Risks
- **First run after this ships is long.** About 2,000 detail pages at 0.5 s or more each, as the owner decided. A run interrupted in the
  fetch phase writes nothing and keeps the pages it fetched, so a rerun continues.
- **A stored printing no listing names any more has no page in the new cache.** Its card's rebuild lacks it, so it is reported as
  `<id> missing` and counted. If there are many, the first run's guard refuses; the owner then reads the named list and decides
  (`--allow-anomaly`). This is the guard working, and the dry run shows it first.
- **The stricter guard may refuse more runs.** Changes it used to hide (printing fields, older wordings) are now counted; that is the
  point of #6.
- **Tests that compared the whole dataset folder** now see the page cache inside it; their helper compares the catalog files and
  leaves the `pages/` folder out, since the dry run's "writes nothing" never covered list pages (its help says so).
- Contracts made stricter: `RefreshReport.changed` changes type (card numbers to `ChangedCard`); its only readers are `format_report` and
  the tests (found by search). No file format changes.
