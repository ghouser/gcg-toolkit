# Gundam Meta

**Status:** Agreed, implemented (see "Implementation status")
**Folder:** `tools/gundam_meta/`
**Backlog item:** IMPROVEMENTS.md > Gundam Meta Data tool

## Purpose
Keep a local copy of what is being played and answer "what's played" questions from it, with no dependency on TCGPlayer. There are three metas, never merged into one score:

| Meta | Source(s) | What it represents |
|------|-----------|--------------------|
| **MobileSuitArena meta** (`msa`) | the online card ranking: last 14 days, 200 games per hour | Online best-of-1 play |
| **Major meta** (`major`) | DuelFrontier + EGM Events: regionals, world championships and qualifiers, large and small official events | Top-level tournament play |
| **Local meta** (`local`) | DuelFrontier + EGM Events: store championships, Newtype Challenge, unofficial events | Smaller in-person play |

Other tools (the store recommender, and a planned "played together" analysis) consume `shared/data/gundam_meta/`.

## Usage
```
python3 -m tools.gundam_meta.cli sync [--only duelfrontier|egm]   # fetch new data, rebuild popularity.json
python3 -m tools.gundam_meta.cli top-cards --meta major                   # current era, all sources combined and de-duplicated
python3 -m tools.gundam_meta.cli top-cards --meta major --source egm --era gd05
python3 -m tools.gundam_meta.cli top-cards --meta local --since 2026-08-01 --until 2026-09-30
python3 -m tools.gundam_meta.cli top-cards --meta msa --bucket core_meta
python3 -m tools.gundam_meta.cli eras                                     # eras and event counts
python3 -m tools.gundam_meta.cli duplicates                               # events both sources report, with the evidence
python3 -m tools.gundam_meta.cli popularity                               # rebuild popularity.json (no network)
python3 -m tools.gundam_meta.cli reparse                                  # rebuild stored events from saved raw responses (no network)
python3 -m tools.gundam_meta.cli refetch --source duelfrontier --event <slug>   # re-pull and replace if changed; --all for everything
```
(Run with `.venv/bin/python -m ...` from the repo root.) A skill can map "most played tournament cards after the newest starter sets" to these commands.

## Inputs
- Network, only during `sync`/`refetch`: DuelFrontier, EGM Events. The online ranking and the example decks are stored data (collected out of band, not by this repository's commands).
- `shared/data/gundam_cards/sets.json` (release dates, for eras) and `cards.json` (card kinds, to exclude resources, EX cards and tokens, and to name cards).

## Outputs
Shared dataset `shared/data/gundam_meta/`, owned by this tool; other tools read it through the models in `tools/gundam_meta/models.py`. Raw responses are cached in `tools/gundam_meta/data/raw/`.

| File | Contents | Notes |
|------|----------|-------|
| `events/<source>/<id>.json` | `EventFile` | **Immutable once written.** Only completed events are stored. Replaced only by `reparse`/`refetch`. |
| `online_rankings/<generated_at>.json` | `SnapshotFile` | One per distinct snapshot of the rolling 14-day ranking. |
| `example_decks/<fetched_at>.json` | `DecksSnapshotFile` | The weighted example decks (below). |
| `popularity.json` | `PopularityFile` | Derived. Latest MobileSuitArena ranking with buckets, plus part-over-whole tournament shares per era, tier, and source (and combined). |

## Data Models
Frozen pydantic v2 models, strict, `mypy --strict` (see `docs/tool-pattern.md`). Card identity is the card number; names live in the card catalog.

- `Source` (`duelfrontier`, `egm`), `Tier` (`major`, `local`, `other`), `EventType` (`regional`, `world_championship`, `store_championship`, `newtype_challenge`, `large_official`, `small_official`, `unofficial`, `other`). `EventType.tier` maps: regional, world championship, large official, small official -> major; store championship, Newtype Challenge, unofficial -> local; anything unrecognized -> `other` (stored, never counted, with a warning).
- `Event`: source, id, name, start/end date, country, city, players, rounds, `event_type`, `type_raw`, `format_label` (the source's own label), `decks`, `fetched_at`, `warnings`.
- `Deck`: id, player name, placement, name, `available` (False for private decks), `main` and `side` as `DeckCard(card_number, qty)`, `unresolved` (list tokens we couldn't interpret). A deck is **counted** only if it is available, has no unresolved tokens, and has a main deck.
- `OnlineRankingSnapshot` / `OnlineRankedCard` (rank, games observed, appearance rate in percent of games), `MsaBucket`.
- `EraDef` (hand-maintained `eras.json`) and `Era` (resolved at read time, never stored).
- `TournamentStats` (source or None for combined, tier, era, window, events, decks counted and not counted, `total_copies`, `excluded_copies`, `cards[CardShare(copies, decks, share)]`), `MsaStats`, `PopularityFile`.

## Data Sources
| Source | Access | Endpoint | Notes |
|--------|--------|----------|-------|
| DuelFrontier | JSON API | `GET api.duelfrontier.com/v1/events?PageNumber=&PageSize=` (list); `/v1/events/<slug>?Include=Players` (top cut); `/v1/decks/<slug>?Include=Cards` (deck, one entry per copy, `section` 0 main / 1 sideboard) | Event type codes 8 store championship, 16 regional, 64 world championship (includes WCQ), 128 Newtype Challenge. Only the top cut is available. Private decks answer HTTP 200 `succeeded:false` ("not authorized"); recorded as unavailable, never bypassed. The numeric-id event route needs auth and is not used. About 1,000 requests for a full sync (0.5 s apart). |
| EGM Events | JSON API | `GET deckbuilder.egmanevents.com/api/tournaments/gundam` | One request (~600 KB) returns every tournament with results. Each result's deck is a URL: `?deck=CARD:qty,...` (main deck only, no sideboards). Event types "Large Official Event", "Official Event" (small official), "Unofficial Event"; "Total Color Breakdown" rows are aggregates, not events, and are skipped. `format` is EGM's own label (e.g. `GD05 + ST11-14`), kept as metadata; eras come from dates. robots.txt allows it. |

## Approach
1. **Sync** (script): fetch, parse into typed models, store. Stored events are never re-fetched. An event is stored once it ended **at least 2 days** ago (`GRACE_DAYS`); a complete DuelFrontier event with no decks yet is kept only after 30 days.
2. **Counting** (script), for one source (or combined) and tier over a window:
   - **whole** = every deck-card copy in counted decks, **main deck plus sideboard** (sideboard cards are played);
   - **part** = copies of one card; **share** = part / whole. Example: 8 decks x 50 cards = 400; a singleton is 1/400; a 4-of in three lists is 12/400.
   - Resources, EX resources, EX bases and tokens are excluded from whole and parts (by catalog `kind`). Cards missing from the catalog are excluded and reported.
   - Private decks and decks with unresolved list slots are not counted (their number is reported). Only the top cut exists, so shares describe what top finishers played.
   - Windows pool their events (bigger events weigh more, by design).
3. **De-duplication** (see below): the default tournament view counts each real event once across sources.
4. **Eras**: windows that start when new cards enter the game (below).
5. **MobileSuitArena buckets** by `appearanceRate`: Core Meta >= 10%, Often Played >= 3%, Played >= 1%, Sometimes Played >= 0.4%, Niche below; unranked cards stay unranked. Cards are played as part of a *package* (archetype), so the curve isn't linear; cutoffs live in one constant and are expected to be tuned.
6. **Redo**: `reparse` rebuilds every stored event/snapshot from saved raw responses (no network); `refetch` re-pulls from the source and replaces what changed. Both report changes.

### De-duplication
DuelFrontier and EGM often report the same event under different names and dates one or two days apart. Names and dates are unreliable, so the evidence is the decks:
- A deck pair is **confirmed** when the main-deck card list is identical *and* the player name matches (case/width-insensitive).
- Two events from different sources within 3 days are the same event when confirmed decks are at least half of the smaller event's counted decks (and at least one); a stricter fallback accepts identical lists alone (>= 5 and >= 75%) in case names are spelled differently.
- A coincidentally identical popular list at unrelated events doesn't qualify (no shared players).
- Of two copies, the one with **more counted decks is kept** (DuelFrontier on a tie, since it also records sideboards); decks the kept copy couldn't read (private, or EGM's unreadable slots) are **filled in from the other copy**, noted in the event's warnings.
- Each event joins at most one group. `duplicates` lists the groups and the evidence. The default `top-cards` view and `popularity.json` "combined" entries use the de-duplicated events; per-source views stay available.

### Eras
Non-overlapping windows `[start, next start)` defined in `eras.json` by the sets that open them; start dates come from `sets.json` at read time.

| Era id | Label | Anchor sets | Start |
|--------|-------|-------------|-------|
| `gd05` | GD05 | GD05 | 2026-07-24 |
| `gd05_5` | GD05.5 | ST11, ST12, ST13, ST14 | 2026-09-25 |
| `gd06` | GD06 | GD06 | 2026-10-30 (not started) |

`--era current` is the latest era that has started, so on 2026-10-30 it becomes `gd06` by itself. `--since/--until` gives an ad-hoc range.

## Decisions (confirmed with user)
- Qualifiers (WCQ events) count as **major**. Sideboard cards are counted. Top-cut-only data is accepted.
- An event is stored 2 days after it ends.
- EGM mapping: large and small official -> **major**; unofficial -> **local**.
- The online ranking is stored as dated snapshots, one per distinct `generated_at`.
- Cutoffs for MobileSuitArena buckets as above; unranked stays unranked.
- **De-duplicate events that DuelFrontier and EGM both report.**
- **EGM's `A|B` list slot** (25 decks, best-of-3 events) is the **boundary between the main deck and the sideboard**: in every one, the entries up to `A` total exactly 50 and `B` plus the rest total exactly 10. Accepted only when that arithmetic holds; otherwise the deck stays unresolved.
- **Local events of any size count as local**, even with only one or two decks listed. No minimum size.

## Acceptance Checks
- Syncing twice makes no detail requests for stored events; `reparse` reproduces stored events from raw with no network; `refetch` reports exactly what changed.
- The worked example (8 decks, 400 copies, 1/400 and 12/400) is a test; shares for a window sum to 1.0.
- Resources/EX/tokens appear in no share output; private and unreadable decks are counted in `decks_not_counted`, never fetched around.
- De-dup: the same event under different names/dates is grouped; one coincidentally identical list is not; each event is in at most one group.
- Data from all three sources parses with strict wire models; a changed API shape fails loudly.
- `top-cards --era current` states the era, date range, event count and deck count in its output.

## Example decks: weighted lists (added 2026-10-08)
Online **decks** come as **example decks**: per archetype, a set of curated tournament deck lists (EGM deck-builder links), each with a weight, that stand in for the online field. They are collected out of band (the collection method is private and is not part of this repository), stored as data, and read by this toolkit through the models in `models.py`.

**Weights.** A list's weight is `archetype games / all archetypes' games x list share`; per archetype the list shares add up to 1.0, so the example decks cover whole archetypes. A list with no share has no weight and is not used.

**Data contract.** `shared/data/gundam_meta/example_decks/<fetched_at>.json` (envelope `{schema_version, data}`): `ExampleDecksSnapshot` = `fetched_at`, `window_days`, `season`, `archetypes[ExampleArchetype(slug, name, games, sides_analyzed, lists[ExampleList(url, cards, share)])]`, `slugs_without_archetype`, `unresolved_lists`. Nothing is guessed: a list link that does not parse into a main deck is reported in `unresolved_lists`. The newest snapshot is the one used (`store.load_decks_snapshot`).

**Used by** `gundam_packages build --source online` (see its design, "Online example decks").

## Out of Scope
- TCGPlayer prices or inventory (the store recommender).
- Merging online and tournament numbers into one score.
- Match results, matchup win rates, archetype classification, and "cards played together" (planned next; see IMPROVEMENTS.md). The stored decks and de-duplication are what it needs.

## Open Questions
- **EGM `Official Event` = small official = major**: confirm that includes small events such as a 256-player regional that EGM labels `Official`.
