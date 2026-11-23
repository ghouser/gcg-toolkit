# no-data-audit: design

Spec: `claude-workspace/specs/gcg-toolkit/no-data-audit/spec.md` (Approved 2026-11-23, AC-1 to AC-4). Closes issue #8.

## Approach
The commands are already covered by `shared/test_empty_dataset.py`; the gaps are the store readers, one reader that crashes, and
`dataset status` sitting outside the subcommand check. So the work is mostly tests, one small code fix and one rule.

Re-check of the spec's audit (against an empty temp dataset and tool data folder):
- Subcommands: cards has 14, not 12 (`--help` lists `refresh, sync, refetch, sets, reparse, export, search, changes, show,
  sync-tcgplayer, sync-restrictions, restrictions, reparse-tcgplayer, price`), so 47 in all, and 36 read the dataset (34 exit 2,
  2 degraded), not 34. The 11 that do not are as the spec lists. Every one of the 36 is already in `shared/test_empty_dataset.py`.
  No command gap; scope unchanged.
- Readers: every public function in a `store.py` that reads stored data comes to 29, not 25: cards 15 (`packages_by_printing`,
  `load_source_pages`, `load_tracked_sets`, `load_provisional_sets`, `load_sets`, `load_catalog`, `load_catalog_or_fail`,
  `load_price_history`, `load_prices`, `catalog_as_of`, `prices_as_of`, `load_cards_with_prices`, `raw_dump_stamps`,
  `read_raw_dump`, `load_restrictions`), meta 9 (`load_events`, `load_events_or_fail`, `stored_event_ids`, `events_as_of`,
  `load_snapshots`, `known_snapshot_times`, `rankings_as_of`, `load_decks_snapshot`, `decks_as_of`), packages 4, collection 1.
  Their empty behavior is as the spec says (only `read_raw_dump` crashes). Named in no test: the spec's 8 plus meta
  `stored_event_ids`. The extra readers are a few one-line table rows, inside AC-2/AC-3's "every store reader"; not a scope change.

Readers: two tables in `shared/test_empty_dataset.py`, `EMPTY_ANSWERS` and `RAISES_NO_DATA`, list every store reader with the empty
answer or the `NoData` source worked out from its docstring and code, and a test calls each against the empty dataset. Tables in the
file that already holds the commands' cases are easier to review against the new rule than cases scattered over four tools' test
folders, and they cover the 16-or-so readers whose existing tests did not clearly pin the empty case without auditing each one.
Readers that read the dataset are called with no folder, so they resolve the root conftest's empty `GCG_DATA_DIR`/`GCG_TOOL_DATA_DIR`
as a real run would. Readers of tracked files (`sets.json`, `restrictions.json`, `names.json`, packages, rates, `drift.json`,
`deck_names.json`) are called with an empty folder or a missing path, because the root conftest copies the tracked inputs into the
temp tool data folder and `names.json` is a fixed path in the repository.

`read_raw_dump` raises `NoData(Kind.PRICES, ...)` naming the dump when its `groups.json` is not stored (the same test
`raw_dump_stamps` uses for "stored"). `NoData` gains an optional `missing` text that replaces the dataset hint in its message, since
the dump lives in the tool's raw cache, not the dataset: `no data: prices (saved price dump <stamp> is not in <folder>)`. Every
existing `NoData(kind)` message is unchanged.

`dataset status` joins the subcommand check: `shared.dataset_cli.main` is added to the mains that check walks, with `status` in a
small list of its own (`SOURCE_REPORTS`) and a case asserting exit 0 and a `no data` line for each of the five sources. Its existing wording is kept
(out of scope to change).

Rule: `.claude/rules/store-readers.md` says every public store reader has a row in the reader tables
(`EMPTY_ANSWERS` or `RAISES_NO_DATA`) and the reviewer checks it;
`review-checklist.md` points to it; `docs/testing.md` says the file holds the readers too.

## Files and interfaces
- `shared/dataset.py`: `NoData(kind: Kind, missing: str | None = None)`.
- `tools/gundam_cards/store.py`: `read_raw_dump` raises `NoData` when the dump is not stored.
- `shared/test_empty_dataset.py`: `EMPTY_ANSWERS` and `RAISES_NO_DATA` tables and their tests; `read_raw_dump` cases;
  `SOURCE_REPORTS` with the `dataset status` case and its place in the subcommand check.
- `shared/test_dataset.py`: `NoData` with `missing` names it and leaves out the dataset hint.
- `.claude/rules/store-readers.md` (new), `.claude/rules/review-checklist.md`, `docs/testing.md`.

## Tests
- AC-1
  - each of the 36 dataset-reading subcommands, empty dataset, exits 2 or 0 with `no data: <source>`: existing
    `test_a_command_on_an_empty_dataset_reports_no_data`, `test_a_command_that_works_without_the_dataset_says_which_source_has_no_data`
  - `dataset status`, empty dataset: exit 0, each of the five sources on a line saying `no data`:
    `test_a_source_report_on_an_empty_dataset_says_no_data_for_every_source[dataset_cli status]` (new, `SOURCE_REPORTS`), plus existing `shared/test_dataset_cli.py`
- AC-2
  - each `EMPTY_ANSWERS` reader returning its empty answer (None, (), {}, frozenset(), `LoadedPages((), ())`): `test_a_store_reader_on_an_empty_dataset_gives_its_empty_answer[<tool> <reader>]`
  - each `RAISES_NO_DATA` reader raising `NoData`, with its kind: `load_catalog_or_fail`, `load_cards_with_prices` (card catalog),
    `load_events_or_fail` (in-person events), `read_raw_dump` (prices): `test_a_store_reader_on_an_empty_dataset_raises_no_data[<tool> <reader>]`
  - `read_raw_dump` with no dump folder, and with a folder but no `groups.json`: `NoData` of kind prices whose message names the stamp
    (`test_reading_a_price_dump_that_is_not_stored_raises_no_data_naming_it`); the stored side stays covered by
    `tools/gundam_cards/tests/test_tcgcsv.py` (round trip)
  - `NoData` with `missing`: message names it, kind kept, no dataset hint; without it, unchanged (`shared/test_dataset.py`)
- AC-3: the two reader tables above hold every store reader, the 9 untested ones included; each row fails if that reader's empty
  answer changes or it raises.
- AC-4: `test_every_subcommand_is_checked_or_is_not_a_dataset_read` now also walks `shared.dataset_cli`; a new subcommand on any of
  the five mains that is in no table fails it. Checked by hand once: a scratch copy with an extra dataset_cli subcommand fails.

## Risks
- A reader added later without a row is caught only by review (the rule), not by a test: the repo forbids tests that scan code.
- `NoData` contract widened, not tightened: the new argument is optional; every existing caller and the CLIs' `except NoData`
  handlers print `str(e)`, which still starts `no data: <kind>`. `read_raw_dump`'s callers (`cards_cli` `reparse-tcgplayer`,
  `price --explain`) only pass stamps from `raw_dump_stamps`, so they never hit it; if they did, `cards_cli.main` already turns
  `NoData` into exit 2.
- Contracts made stricter: none.
