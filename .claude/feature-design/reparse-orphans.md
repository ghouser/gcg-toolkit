# reparse-orphans: design

Spec: `claude-workspace/specs/gcg-toolkit/reparse-orphans/spec.md` (PersonalClaude workspace)

## Approach
`reparse` (which `sync` and `refetch` end in) builds from every cached detail page. It now applies the refresh's orphan rule, with the cached package list pages standing for the run's listings: a page is an orphan when its card number is in no cached listing and not in the stored catalog. Orphans are filtered out before `build_catalog` and reported with the refresh's own orphan line (one shared formatter, `refresh.orphan_line`), so the two commands cannot drift apart in wording.

When no package list page is cached, nothing is "listed" and every page of a new card would look like an orphan. `reparse` then prints that it cannot tell orphans from real cards and returns before building, leaving `cards.json`, `traits.json` and `source_titles.json` untouched. The sets rebuild that precedes the catalog is unaffected (it reads the product pages, not the listings). Exit status 2, as `sync --only printings` uses for "no cached package list".

The doc fix (AC-3) repoints `.claude/feature-design/refresh-cards.md` (page cache location and the guard's count) to `safe-refresh/spec.md` and `tools/gundam_cards/design.md`.

## Files and interfaces
- `tools/gundam_cards/refresh.py`: `orphan_line(orphans: Sequence[PrintingId]) -> str`, used by `format_report`.
- `tools/gundam_cards/cli.py`: `cmd_reparse` computes `packages_of = packages_by_printing(pages_folder())`, returns early with a message when it is empty, filters `loaded.pages` by known numbers (listed or stored), prints `orphan_line` when any.
- `tools/gundam_cards/design.md` and `docs/commands.md`: one line on reparse's orphan rule.
- `.claude/feature-design/refresh-cards.md`: lines 8 and 15 repointed.

## Tests
`tools/gundam_cards/tests/test_reparse_orphans.py`, with the safe-refresh tests' fake Bandai and `cli.main`.
- AC-1
  - orphan, catalog already exists (unhappy): a cached page of a card in no listing is absent from `cards.json` after `reparse`; count unchanged.
  - orphan, first build with no catalog (unhappy): same, the listed cards are built.
  - listed card and stored-but-unlisted card (happy): both still built.
  - no cached package list (unhappy): output says so, `cards.json`, `traits.json`, `source_titles.json` byte-identical (also with no catalog: none created).
- AC-2
  - output names each orphan by printing id in the refresh's wording, exit 0; no orphan line when none (happy).
  - `sync` and `refetch` print it too (they run the same reparse) (unhappy).
- AC-3: a documentation edit, checked by reading the file (construction).

## Risks
- A card whose listing page is not cached (a partial cache) is treated as an orphan and left out of a first build; a stored card is never dropped. `refresh` is the way to fetch the missing listings.
- Contracts made stricter: `reparse` now builds fewer pages. Callers: `cmd_sync` and `cmd_refetch` call `cmd_reparse`; their tests assert on built cards and are run in full.
