# Keeping data fresh

Prices, the banned list and the packages go stale. The repository ships with data as of its last commit; these commands update it.

| What | Command |
|---|---|
| Card prices (tcgcsv, at most once a day) | `gundam_cards sync-tcgplayer` (`--force` to refetch) |
| Banned and restricted cards | `gundam_cards sync-restrictions` (pass `--url` for a newer announcement) |
| Tournament events | `gundam_meta sync` |
| Re-derive the packages after new data | `gundam_packages build` and `gundam_packages build --source online` |

Each is run as `.venv/bin/python -m tools.<tool>.cli <command>`. Raw responses are cached under each tool's `data/raw/` folder (not part of the repository), so a re-run does not hit the sites again.

## The banned and restricted list in force

{{run cards restrictions | lines=18 | width=150}}

The list is applied to the decks the tools find and to the decks they suggest: a deck that breaks it is flagged `!`, and `suggest` never builds one.

## How current is what I am looking at?

- `value` prints when its prices were pulled.
- `coverage` and `packages` say which source and window they read (for example, the online example decks since a date).
- Everything is computed from the data on disk, so run `sync-tcgplayer` before you shop.
