# collection-file-read: design

Spec: `claude-workspace/specs/gcg-toolkit/collection-file-read/spec.md` (Approved 2026-11-22, AC-1 to AC-5)

## Approach
One new module, `tools/gundam_collection/collection_file.py`, is the only code that reads collection data. It resolves the path when called (`$GCG_COLLECTION_FILE`, else `~/.gcg/collection.json`), parses and validates the file (version, timestamp, printing ids, counts of 1 or more) and returns `Owned`: printing id -> count, with derived card -> count (`cards`) and printing -> count views. A bad file raises `CollectionRefused` (message names the problem; for a version, the one found and the supported ones). The file is never written.

When the file does not exist, the same module reads the old text list (`my_tcg_collection`) read-only through the existing `parse_lines`: every counted line becomes that card's base printing (a `+`, `++` or `LK` marker does not map to a printing id), and the module reports how many marker lines it counted. When the file exists the text list is not opened. They are never merged.

Unknown printing ids (not in the catalog the command already loaded, `_pN` alternates included) are split off after reading and listed once each on stderr; the command goes on with the rest and its exit code is unchanged. For the text-list fallback a base id counts as known when its card number is in the catalog.

The commands' `_layers()` calls the reader once. `Layers.owned` stays card -> count (so coverage, decks, buy and suggest need no change: any printing of a card is the card); `Layers.printings` is new, for `value`. `value` prices each owned printing at its own price when the store has one (`gundam_cards.export.printing_prices`, the same rule the catalog export uses) else at the card's price. `import` becomes a pointer to the UI. The derived `collection.json` store (`write_collection`, `load_collection`, `owned_copies`, `CollectionFile` and friends, `build_collection`, the auto re-import and its test) is removed, and the tracked derived `shared/data/gundam_collection/collection.json` is `git rm`ed. `check` and `template` are unchanged.

Schema (documented in `docs/collection-file.md`, for the UI): `{"schema_version": 1, "updated_at": "<ISO 8601 UTC>", "counts": {"<printing id>": <integer >= 1>}}`. The spec fixes the three parts but not the key names for the timestamp and the map; `updated_at` and `counts` are chosen here and documented. Unknown extra keys are ignored (as in the catalog export). Chosen over a pydantic model for the file because the refusal messages must name the exact problem (bool, null, float, bad id), which hand validation gives plainly.

## Files and interfaces
- `tools/gundam_collection/collection_file.py` (new): `collection_file_path() -> Path`, `text_list_path() -> Path` (both resolved per call; the text list under `tool_data_root()` so tests point it at a temp folder), `SUPPORTED_VERSIONS`, `CollectionRefused`, `Owned` (frozen model: `printings`, `unknown`, `source`, `markers`, property `cards`), `parse_collection_file(text) -> dict[PrintingId, int]` and `parse_text_list(text) -> (dict, markers)` (pure), `read_owned(catalog) -> Owned` (the shell).
- `tools/gundam_collection/cli.py`: `_layers()` uses `read_owned`, prints the fallback notice and unknown ids on stderr; `main` turns `CollectionRefused` into a stderr message and exit 1; `cmd_import` prints the pointer; `cmd_value`, `cmd_coverage`, `cmd_card`, `_deck_context` use `Layers`; `_refresh_collection` removed; usage text updated.
- `tools/gundam_collection/value.py`: `analyze` takes owned printings and per-printing prices; lines are per printing.
- `tools/gundam_collection/store.py`, `models.py`, `check.py`: the derived-collection pieces removed.
- `shared/data/gundam_collection/collection.json`: removed from git.
- `docs/collection-file.md` (new): schema, version policy, legacy text format (AC-5). `docs/commands.md`, `docs/glossary.md`, `docs/wiki/Your-Collection.md`, `tools/gundam_collection/design.md`, `.claude/rules/data-folders.md`: say what the code now does.

## Tests
- AC-1: `tests/test_collection_file.py` unit tests on `parse_collection_file` (valid example, unsupported version names found and supported, not JSON, count 0, null, float, bool, bad id, missing parts); CLI tests with `GCG_COLLECTION_FILE` pointed at a temp file: `card` shows the file's copies, an invalid file exits non-zero with no fallback even when a text list exists, the env var is read at call time, the file is byte-for-byte unchanged and no other file appears beside it.
- AC-2: CLI tests: an unknown id is named once on stderr, exit code unchanged, other entries used; a file of known ids prints nothing of the kind.
- AC-3: CLI tests: no file, text list present -> one-line notice with the marker count, nothing written; file present -> text list ignored (a card only in the list counts as not owned) and no notice; `import` prints the pointer, exits 0, writes nothing, with and without either file.
- AC-4: unit and CLI tests: a card owned only as `ST01-001_p5` fills the `ST01-001` slot (`cards` view, `card` command), copies of printings add up; `analyze` prices a printing at its own price, else at the card's price (an alternate with no own price is valued).
- AC-5: a stated way to check, since docs are not scanned by tests (`docs/testing.md`): the reviewer reads `docs/collection-file.md` against the checklist in this design; the example in it is the one the tests parse (`docs/collection-file.example.json`, checked by `test_collection_file.py` through `parse_collection_file`, the same way `docs/catalog-export.example.json` is used).
- "No data": `read_owned` with neither file gives an empty `Owned`; commands that need a collection name the missing file and exit 2.

## Risks
- The spec leaves the key names for the timestamp and the counts map open; `updated_at` and `counts` are my choice. If gcg-ui builds against other names, the schema doc and reader change together (one place).
- `value` is the one view whose output changes shape (lines per printing); an owned alternate with no price of its own is priced as the card, so totals stay what they were for the same owned counts.
- Existing tests monkeypatch `load_collection`/`COLLECTION_PATH`; they are moved to the new env/folder seams. A missed one would read `~/.gcg`; the root `conftest.py` sets `GCG_COLLECTION_FILE` to a temp path for every test as the backstop.
