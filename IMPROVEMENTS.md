# Improvements

Backlog of tools and improvements we want to build. Newest ideas at the bottom of each section. When an item is started, link its tool folder; when done, move it to Done.

## Backlog

### Gundam Meta Data tool (implemented)
Design: `tools/gundam_meta/design.md` (Status: Agreed, implemented)

Local, TCGPlayer-independent store of what's played: MobileSuitArena (the online ranking, best-of-1, 5 popularity buckets), and tournaments from DuelFrontier and EGM Events (major = regional/world/large+small official; local = store championship/Newtype Challenge/unofficial). Part-over-whole card shares per era, with events both sources report de-duplicated by decklist + player name. Immutable stored events, `reparse`/`refetch` redo paths, eras from set release dates (GD05, GD05.5, GD06).

- Synced 2026-10-06: 184 DuelFrontier + 83 EGM events (231 distinct after de-duplication), 1,808 of 1,809 decks counted (only a private deck is not). 254 tests, `mypy --strict` clean.
- Decided: EGM `A|B` slots are the main/sideboard boundary; local events of any size count.

### Gundam Card Catalog tool (build first)
Design: `tools/gundam_cards/design.md` (Status: Draft)

Local, searchable catalog of every card, scraped directly from Bandai's official English site (server-rendered HTML, per-package lists plus per-card detail pages). Keyed by card number, with printings/parallels, set release dates (including unreleased sets), and a card-number-to-TCGPlayer-`productId` mapping. Local `search` command for any combination of filters. Shared by `gundam_meta` (card types, set dates) and the store recommender (resolve "want" names, `+` alt arts).

- Progress: `gundam_cards` is functionally complete except the TCGPlayer mapping: sets, full printing sync (2,011 pages -> 1,152 cards), refetch, reparse, show, and local search all work (163 tests, `mypy --strict` clean). Remaining: `sync-tcgplayer`, plus a few wording/attribute rules awaiting decisions (see its design's Open Questions).
- Survey done: all 1,149 base cards crawled and saved in `tools/gundam_cards/data/raw/` (also the parser's test fixtures). The model is a discriminated union by card kind.
- Later idea: per-ability parsing (native vs granted keywords, pilot-condition tags like `【During Pair･(Vulture) Pilot】`).

### Packages and archetypes (implemented)
Design: `tools/gundam_packages/design.md` (Status: Agreed, implemented)

Decks organized **first into packages** (co-play plus a tie from the card catalog: combo like pilot-and-unit Links, synergy like abilities that need other cards, or functional reprints that do the same thing), **then into archetypes** (combinations of packages), with **synergy** and **free-floating** cards separated, and groups of cards that do the same thing listed. GD05 packages and archetypes, plus drift analysis for GD05.5 (new cards adjusting packages). Names are pilot + unit (`Mikazuki Barbatos`, `Kira Strike Freedom`). Built from `gundam_meta`'s de-duplicated main decks. 14 one-color packages from 253 GD05 decks, with package synergy (bridge cards) and scored synergy cards; your examples (Barbatos trio, Master Asia, Char, Marida; Airframe Seizure and Exia Repair free floating) are the tests.

- Appearance rates (`rates.json`; `package` and `card` lookups): package played rate, card rate in a package (copies out of 4 per deck), combined package rates, and bridge rates, all from counts. Spec: `tools/gundam_packages/appearance-rates.md`. Not done: rates for the GD05.5 window, rates in the meta report, and labeling a partner package's synergy cards (Axis under Char, seen from Mikazuki Barbatos) as such instead of "other".

### Meta over time (next idea)
Track how the meta changes over time, not just per era: how each package's share of decks, each archetype, and each card's play rate move week to week and across eras. Metas change constantly, so small windows are accepted; this makes the changes visible instead of re-measuring from scratch.

- Data exists: events are stored with dates (immutable), online ranking snapshots are dated (hourly), decks are stored in full, and package discovery is deterministic, so any window can be rebuilt.
- Ideas: rolling windows (for example 4 weeks) with packages found once per era and counted per window; a package's rise and fall; when a new card first appears in a package's decks (extends the GD05.5 drift report); the 14-day online ranking snapshots as the online trend line.
- Needs: a decision about window size versus noise, and where to keep the time series (probably derived files per window).

### More deterministic card-text understanding (later)
The functional-reprint and synergy detection reads card text with heuristics (content-word overlap, native keyword lines, "needs other cards" cues). A more deterministic approach would parse each ability into structured form (trigger, cost, target, effect, conditions) so synergies like "one card gives -X AP, another destroys units with 1 or less AP" are matched by rule instead of by text similarity, with less reading and fewer judgment calls. Too much scope for now.

### Sideboard tech analysis (next idea)
Sideboards are separate tech, not part of package discovery. Take a first crack at **estimating what each sideboard card is meant to solve**: which main-deck cards, packages, or opposing archetypes it is swapped in against.

- Data exists: DuelFrontier and EGM best-of-3 events record 10-card sideboards (main deck and sideboard stored separately). Only best-of-3 events have them.
- Ideas: how sideboard cards differ by archetype (what each package side-boards), what the main deck is missing that a sideboard card covers (removal, an answer to a keyword like Blocker or Suppression, a specific unit), and which sideboard cards are common across archetypes (generic tech) versus specific to one.
- Needs: the card catalog's keywords and text to classify what a card does; the question of how to validate "what it solves" without game logs.

### Example decks with weights (done)
Curated deck lists per online archetype, weighted by archetype games x list share, stored as data in `shared/data/gundam_meta/example_decks/` (the collection method is private; refreshing them is a manual, out-of-band step). Done (2026-10-08): our own package discovery, bridges, synergy and free-floating cards and all appearance rates on these decks (`gundam_packages build --source online`, `compare`). Later: matchup data for counter picks, an online meta report.

### Card database (long term)
One database with three layers joined by card number: card facts (the master card model), card association facts (packages, bridges, rates, per source) and price history (a time series). Layers and read models are described in `docs/tool-pattern.md`, "Data layers". The JSON files are already shaped as its tables; build it when cross-layer queries justify SQLite. Price history comes after the first price sync.

### Collection and purchase planning (design drafted)
Design: `tools/gundam_collection/design.md` (Status: Draft). Replaces the dropped store recommender and the parked collection manager. Goals (deck-building principles and spending priorities) are at the top of that design and summarized in `CLAUDE.md`. Collection typed as a plain text list; slots, home/adjacent/new packages, and a ranked, explained purchase list exported for TCGPlayer's Mass Entry. Order: (1) done 2026-10-08: `gundam_cards sync-tcgplayer` on tcgcsv (`prices.json`, `price`, the `PricedCard` join; all 956 deck cards priced); (2) a copy-count histogram in `rates.json`; (3) `gundam_collection import` and `coverage`; (4) the deck report; (5) `plan` and the Mass Entry `export`. Built so far: the collection file format, `check` and `template`, the copy histogram (2026-10-08), `import`, `coverage`, the cross-layer `card` view and the `value` price analyzer (cards by price band, with totals). Possible next: price the printing I actually own (alt arts, Edition Beta) by keeping those products' prices too. **Deck report** (`decks`, `deck <name>`): built 2026-10-09 (the per-archetype card table is in `rates*.json`). Not built: the candidates part of `--alternatives`. Next: `plan` and the Mass Entry export. Next: the deck report, then `plan` and the Mass Entry `export`; later, a `gundam` front door over all the layers, and a tie check so functional reprints can count toward a slot.

### TCG Store Recommendation tool (dropped 2026-10-09)
Removed: there is no permitted data route to build it on. Purchase planning lives in `gundam_collection buy`, which writes a list to paste into TCGPlayer.

### Candidates: potentially viable cards (next idea)
Cards not in lists that the card text suggests would work, found from the structural ties (no new data). First count on GD05: of 956 deck cards, 694 were never played; 266 of those have a tie to a played package member and 128 have a combo, functional-reprint or link tie (Gundam Barbatos 3rd Form with Mikazuki Barbatos; Akihiro Altland as a Tekkadan pilot; Gundam Gusion Rebake Full City as an alternative Blocker). Kinds: **alternatives** (functional reprints of played cards, with the played card's rate beside it), **diamonds in the rough** (strongest ties to a package, never played), unplayed pilots for played units. Combine with prices for a "cheap cards worth testing" list. Candidates are test ideas, not predictions. **Blocked:** counter picks need matchup data (no permitted source yet); sideboard options need sideboard lists (DuelFrontier's stored data has them; EGM does not).

Given cards I want, find TCGPlayer sellers and build a padded cart: padding target is $5 minus the wanted cards, plus up to $1 wiggle, NM only, max 4 copies per card, chosen by popularity from the meta tool (and collection gaps later).

- Inventory source: TCGPlayer `mp-search-api` (unauthenticated JSON), filtered by `sellerKey`.
- Shipping: sellers entering $0.00 shipping get TCGPlayer's default, which is $1.49 under $5 and free at $5+.
- Depends on `gundam_meta`'s `popularity.json`. Needs a per-product listings endpoint probe to find sellers of a card.
- Card matching: join on card number (`customAttributes.number` in the TCGPlayer search API), which matches the online ranking's `cardNumber`.
- Excludes `+` alt-art rarities and non-NM listings; falls back to the closest total above target.

### Collection management tool (superseded by "Collection and purchase planning")
Track and manage my card collection. TCGPlayer's app has no export or API for it, so our own data is the source of truth, keyed by TCGPlayer `productId`.

- Likely a small app, to be designed together (user is a software dev).
- Parked until the tool-structure pattern and the store recommendation tool exist.
- Will feed the store recommendation tool (skip cards already owned / fill gaps).

### Open items (2026-10-09)
- **Corsica Base logic review.** In `suggest barbatos aggro PB` Corsica Base gets 1 copy although it is restricted to 2 and fits aggro (+0.8). Check how Bases compete with Units for slots (`room`, the `strict` reservation, the Base shape taken from found decks) and whether a restricted-to-2 card that is the best-fitting Base should reach its cap.
- **Link pairs in curve and pressure.** The links rating exists (not part of the plan axis), but `style_of` still reads a Unit's printed AP/HP and cost. A Unit paired with its pilot has the pilot's AP/HP and can act the turn it is played (haste), which makes it a lower effective curve and more pressure. Review whether pairs should adjust curve and pressure, and what that does to the control/midrange/aggro lines.
- **Refresh skill and staleness (spec together).** The workflow repeats: sync cards, prices and restrictions, re-import the collection, then `buy` or `suggest`. Spec it as one skill wrapping the existing commands, and spec staleness with it: a "data as of" line in `buy`, `suggest` and `value` output, a warning when prices or the banned list are older than a threshold, and what counts as stale per source.
- **Deck views:** a `blockers` view for decks (the Blocker cards in or around a deck); a `--pool` option for `deck` like `suggest`'s pool (the next best cards to add); and drawing `deck --alternatives` candidates from that pool as well as from same-job matches. Low priority.

## Done

- `gundam_cards`, `gundam_meta`, `gundam_packages`, `gundam_collection` built and tested (see each `design.md`).
- (2026-10-09) Link-aware `suggest` (partner packages, Link pairs, other pilots ranked by plan fit) and the links rating; filler pilots left out.
- (2026-10-09) Regression tests on the real data for the top-meta decks (Master Asia + Domon Shining, Barbatos + Char, Kira Strike Freedom, and the Barbatos aggro suggestion): `tools/gundam_collection/tests/test_regression.py`; every tuning constant is listed in `docs/tuning.md`.
- (2026-10-09) The toolkit moved into its own repository (`gcg-toolkit`); portable paths, `bootstrap.sh`.


## Same-job classification and redundancy rework
(Done 2026-10-08 for Units, Commands, Pilots, Bases, squads and pairing: `shared/samejob/`.) Was: replace the text-overlap and same-name heuristics with a structural *same job* match. Rework the collection slot logic to the redundancy rule (goal 4 in `tools/gundam_collection/design.md`): reprints never merge slots; they stand in only for cards real decks don't play in that role. Revert the same-name rule in `functional.py` and the same-name bypass in `reprints.py`. Test cases: both Kshatriya, both Char's Zaku II, Close Combat / Improved Technique / Battle of Aces, Gundam Ariel's rest-a-Unit damage ability.

(2026-10-08) Collection redundancy rework done: `tools/gundam_collection/alternatives.py` replaces `reprints.py`; slots are one per required card.
Still open: a plan/Mass Entry export, price history, rules for Pilots and Bases beyond the first version (check the squads for oddities), and a saved check of an outside source's own groupings against ours.

(2026-10-08) Banned / restricted cards: `sync-restrictions` (Bandai's announcement), `legality.py`, applied to found decks and `suggest`. Next time Bandai publishes a list, run `sync-restrictions --url <the new page>`; the pairs and the vanilla group are read from the page.
