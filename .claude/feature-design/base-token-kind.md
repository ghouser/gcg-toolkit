# base-token-kind: design

Spec: `claude-workspace/specs/gcg-toolkit/base-token-kind/spec.md` (Approved 2026-11-23). Closes #15.

## Approach
**A new non-deck kind, inferred in one place (AC-1, AC-2).** `CardKind.BASE_TOKEN = "base_token"` is added after `UNIT_TOKEN`, with a
model `BaseTokenCard` that has no color and keeps the Base's other fields as optional: `level`, `cost`, `hp` (`int | None`), `zones` and
`traits` (empty when the page shows `-` or nothing). Bandai has no such TYPE, so `parse_kind` is unchanged: a page saying `Base` is still
a `BASE`, and `build._build_variant` decides in its Base branch. The rule is the spec's, checked in this order:
1. the page shows no color (`COLOR` is `-` or the label is absent), and
2. the card number is in the token series (`T-` prefix),
then it is a `BaseTokenCard`, built from whichever fields the page shows (a missing label reads as `-`). Otherwise the Base goes through
`colored()` exactly as today, so a non-token Base with no color fails with "COLOR is required here but the page shows none", a Base
that shows a color is a `BaseCard` whatever its number, and an unknown color still fails (in the refresh, the shape check rejects it
first, as today). Units, Pilots and Commands are not touched: they keep requiring a color whatever their number. The alternative, making
color optional on `BaseCard`, is out of scope (it relaxes a deck kind) and would put a colorless card in deck logic.

`is_deck_card` is unchanged (it lists the four deck kinds), so `base_token` is `deck: false` in the export. `color_of`, `level_of` and
`cost_of` stay as they are (deck kinds only), so the export leaves out `color`, `level` and `cost` for a base token, matching the
documented "deck kinds only" rule. `traits_of` includes `BaseTokenCard`, so a token Base that shows traits feeds the traits file.

**The dry run runs the same build on the same pages (AC-3).** Today the dry run fetches no detail page, so a new card is never parsed
and its drop is a surprise. Now both modes fetch the same detail pages: every listed printing whose page is not cached. The dry run
wraps its fetcher in a small `_Uncached` adapter that drops the cache key from every request, so nothing it fetches (package list,
product pages, listings or detail pages) is written to the page cache. The detail pages it fetches are parsed in memory and added to the
pages loaded from the cache, with this run's packages, before the shape check and the build. From there the code is shared, so the dry
run reports the same rejections and the same `[parse_failure] <number>: <reason>` lines the real run would, and adds nothing to them
for a card the real run would add. An unreadable or failed detail page makes the dry run incomplete, as it does the real run (nothing
to unlink, since nothing was stored). Fetching only the new cards' pages, rather than every uncached one, would need a second rule
and would predict less; the set the real run fetches is the simpler one to share.

The "writes nothing" promise widens from the catalog files to the page cache: after a dry run the whole dataset folder, pages
included, is byte-identical. No report line changes: the dropped card is named by the existing issue or rejection line.

## Files and interfaces
- `tools/gundam_cards/models.py`: `CardKind.BASE_TOKEN`; `class BaseTokenCard(CardBase)` (`kind`, `level: int | None`,
  `cost: int | None`, `hp: int | None`, `zones: SortedFrozenSet[Zone]`, `traits: tuple[Trait, ...]`), added to `Card` and `CardModel`;
  `traits_of` covers it.
- `tools/gundam_cards/build.py`: `TOKEN_SERIES = "T-"`; the Base branch of `_build_variant` (`case CardKind.BASE | CardKind.BASE_TOKEN`)
  applies the rule above.
- `tools/gundam_cards/refresh.py`: `_Uncached(fetcher)` (a `TextFetcher` that stores nothing); in a dry run every request goes through
  it, the uncached detail pages are fetched too, and their parsed pages join the build. Module docstring updated.
- `tools/gundam_cards/cli.py`: the `--dry-run` help says it fetches new pages without storing them and writes nothing.
- Docs: `docs/catalog-export.md` and `docs/catalog-export.example.json` (the new kind in `reference.kinds`), `tools/gundam_cards/design.md`
  (kind list, model, parser rule, refresh step 7's dry run), `docs/commands.md` (dry run line), `docs/glossary.md` (**Base token**).
- Tests: `tools/gundam_cards/tests/test_base_token.py` (new); `test_catalog_refresh.py` (the `detail` helper takes field overrides; the
  two dry-run tests that asserted no detail request now expect the new cards' pages and a byte-identical page cache);
  `test_export.py` (the per-kind parametrization and the reference kinds gain `base_token`).

## Tests
Refresh tests run `refresh_catalog` with `FakeBandai` (no network) in the per-test temp dataset; the command tests run `cli.main` with
only the network faked, so the real `Fetcher` is the one that must not write. Pages are built with the refresh tests' `detail` helper.
"T-037 as Bandai shows it" is TYPE `Base`, COLOR `-`, Lv. `-`, COST `-`, AP `-`, HP `5`, Zone `-`, Trait `-`.
- AC-1
  - token-series Base, no color (happy): a real run over T-037 adds it as `base_token`, color absent, `hp == 5`, `level`, `cost` None,
    no zones, no traits; `cards.json` has it; no `parse_failure` issue and no rejection names it; the run is written.
  - the page's other fields are kept, none required (both sides): a `T-` Base with no color that shows Lv. 2, COST 1, HP 3, Zone Space,
    Trait (Earth Federation) keeps all of them; one whose HP label is absent and Lv./COST are `-` is still added, with `hp` None.
  - no color shown as an absent label (other side of "shows no color"): a `T-` Base page with no COLOR label is a base token too.
  - token-series Base that shows a color (other side of the color condition): a `T-` Base showing Blue is added as `base` with blue.
- AC-2
  - each deck kind with no color (unhappy, every family member): `unit`, `pilot`, `command` and a non-token `base`, each with a `GD01-`
    number, are left out with `[parse_failure] <number>: COLOR is required here but the page shows none`; unit, pilot and command with a
    `T-` number are left out with the same message (the token rule is for Bases only).
  - a non-token Base with no color label at all is left out as today (`page has no 'COLOR' field`).
  - unknown color (unhappy, both numbers): a `T-` Base and a `GD01-` Base showing `Orange` are rejected with "unknown color 'Orange'"
    and not stored.
- AC-3
  - drop predicted (unhappy): with a stored catalog, a dry run over new cards (the AC-2 cases and an unknown-color Base) reports each by
    number with the same parse-failure or rejection line as the real run that follows; the real run's issue and rejection lines equal
    the dry run's.
  - add not reported as dropped (happy): in the same dry run T-037 and the coloured `T-` Base appear in no issue and no rejection, and
    the following real run adds them.
  - fetches without storing, warm state: with a stored catalog and cache, the dry run requests the new cards' detail pages, and
    afterwards every file under the dataset folder (pages included) and the tracked `sets.json` are byte-identical.
  - fetches without storing, empty state: a dry run on an empty dataset creates no file at all.
  - with the real `Fetcher` (command): `cli.main(["refresh", "--dry-run"])` with the network faked prints the parse failure for the
    colorless non-token Base and none for T-037, and the dataset and tool-data folders are byte-identical before and after.
  - an unreadable new detail page in a dry run: the run is incomplete, names the page, and nothing is written or cached.
  - updated: `test_a_dry_run_reports_what_a_real_run_would_do_and_changes_nothing` and `test_the_refresh_command_dry_run` now expect the
    new detail requests and a byte-identical page cache.
- AC-4
  - per-kind export (happy): `BaseTokenCard` with `hp=5` is exported with kind `base_token` and no `color`, `level` or `cost`; one that
    shows level and cost is exported without them too (deck kinds only).
  - reference kinds: `base_token` is listed with `deck: false`, after `unit_token`.
  - end to end: after a real refresh adds T-037, `export` succeeds, the file validates as `CatalogExport`, holds no `null`, and has T-037 as
    `base_token` with no `color`, `level` or `cost`.

## Risks
- A real T-037 page may show its empty fields differently (`-`, an empty value, or no label). The build reads a missing label as `-`;
  an empty value would fail the integer parse and be reported as a parse failure (never a crash), and the next dry run now shows it.
- A dry run on a dataset with no page cache fetches every listed page and keeps none, so the next real run fetches them again. This
  is the price of "the page cache is byte-identical"; it only matters for a first run, where a real run is the normal choice.
- `cards.json` keeps `schema_version` 2: a new kind is a new member of the discriminated union, readable by this code. An older checkout
  reading a dataset that holds a base token fails to validate the catalog; that is the same as any new kind, and the export's own
  version policy (new kinds in `reference`) covers the UI.
- Contracts made stricter: none. The dry run's fetcher wrapper only removes caching; no type or validation tightens.
