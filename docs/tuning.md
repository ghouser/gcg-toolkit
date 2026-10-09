# Tuning constants

Every judgment-call number in the toolkit, where it lives, and why it has its value. Most were set by looking at real output and checking it against what a player knows of the meta; none is fitted to data. **When one changes, run the regression tests (`tools/gundam_collection/tests/test_regression.py`) and say here what moved and why.**

"Basis" says how the value was reached: *rule* (from the game or a published list), *judgment* (set by reading output; the reason is given), or *default* (a first guess nobody has contested yet).

## Packages (`tools/gundam_packages`)

| Constant | Value | Meaning | Basis |
|---|---|---|---|
| `DEFAULT_PARAMS.min_decks` | 6 | A card must be in at least this many tournament decks to be considered for a package | judgment: a sample-size guard for about 250 decks |
| `ONLINE_PARAMS.min_decks` | 50 of 10,000 | The same guard for online example decks (0.5% of the field) | judgment: the tournament count does not carry over |
| `mutual_threshold` | 0.8 | Two cards are co-played when each is in 80% of the other's decks | judgment |
| `run_share` | 0.75 | A deck runs a package when it has 75% of its cards (all but one of four) | judgment: cutting one card of four is still the package; half is not |
| `bridge_share` | 0.5 | A card bridges two packages when decks of both play it at this share | judgment |
| `CORE_SHARE` | 0.9 | A member is core when 90% of the decks running the package have it | judgment |
| `MIN_BRIDGE_DECKS`, `MIN_CONTROL_DECKS` | 3 | Decks needed before a bridge, or a "carried by another package" claim, is made | default |
| `TYPICAL_SHARE` | 0.5 | A card is typical of an archetype at half its decks | default |
| `PEER_STAT_SLACK` | 1 | Units are graph peers when AP and HP are each within 1, both ways | judgment |
| `ONLINE_TOTAL` | 10,000 | Example decks are apportioned to this many whole decks so each is 0.01% of the field | rule (a scale, not a tuning) |
| `ARCHETYPE_CARD_MIN_SHARE` | 0.25 | A card is in an archetype's table when a quarter of its decks run it | default |
| `LOW_SAMPLE_DECKS` (rates / drift) | 20 / 100 | Below this many decks, copy counts (or a drift window) are flagged as uncertain | default |
| `MIN_OVERLAP` (`shared/overlap.py`) | 0.5 | Two groups are the same group when at least half of their combined items are shared (Jaccard) | default |

## Same job (`shared/samejob/vocabulary.py`)

| Constant | Value | Meaning | Basis |
|---|---|---|---|
| `STAT_SLACK` | 1 | A Unit stands in for another when its AP and HP are each at most 1 below | judgment: stats matter, level and cost do not |
| `SIZE_SLACK` | 1 | A Command's main effect number may be at most 1 below | judgment |
| `COST_SLACK` | 1 | A Command may cost at most 1 more | judgment |
| `LOSS_ALLOWED` | 1 | Commands and Bases may lose one net good-to-have (Burst, pilot pairing, Action timing, other effects) | judgment |
| `CRITICAL_CLASSES` | Blocker; Breach / Suppression / High-Maneuver (interchangeable) | Keywords that must match for a Unit to do the same job | judgment: from the player's own definition of a job |
| `GOOD_KEYWORDS` | First Strike, Repair, Support, Development | Keywords that are good to have, not required | judgment |

## Completeness bands (`tools/gundam_collection/bands.py`)

| Constant | Value | Meaning | Basis |
|---|---|---|---|
| `THRESHOLDS` | Perfect 100%, Complete 90%, Playable 75%, Reachable 50%, Long shot 25% | Share of a deck's core and staple copies owned | judgment: Playable means a deck can actually be played |
| `KEY_SHARE` | 0.5 | In the top three bands, a core card needs at least half its copies (2 of 4) | judgment: a percentage alone hid a missing key card |
| `AHEAD` | 2 | Bands shown ahead of Reachable and Playable | default |
| `HOME_MIN_OWNED` | Reachable (50%) | A package is "home" when you own at least this much of it | judgment |

## Deck lists (`tools/gundam_collection/decks.py`, `archetypes.py`)

| Constant | Value | Meaning | Basis |
|---|---|---|---|
| `MIN_PLAY_RATE` | 0.05 | A deck played in under 5% of decks in every source is fringe and left out | judgment |
| `VARIANT_SHARE` | 0.2 | A variant of a played archetype counts when it reaches 20% of that floor | judgment |
| `STAPLE_MIN_SHARE` | 0.5 | A card in half of a deck's lists is a staple | judgment |
| `OPTION_MIN_SHARE` | 0.25 | A card in a quarter is an option (not counted toward a band) | judgment |
| `PREMIUM_CENTS` | 1000 | A pick of $10 or more is premium: shown, never silently bought | judgment |
| `DECK_SIZE` | 50 | Deck size | rule |
| `ALT_MIN_SHARE` | 0.5 | A stand-in is only counted when real decks play it at least this often compared with the card | judgment |
| `DEFAULT_THRESHOLDS`, `SELL_MIN_CENTS` (`value.py`) | 50 / 100 / 500 / 1000 cents; 50 | Price bands for `value`; a card of 50 cents or more is worth selling | judgment |

## Deck style ratings (`tools/gundam_collection/styles.py`)

Each rating is a measured share scaled between two anchors to 0-10 (`scale`).

| Constant | Value | Meaning | Basis |
|---|---|---|---|
| `CURVE` | 0.35 to 0.85 | Half the share of cheap (Lv 3 or lower) bodies plus half the share that is not Lv 6 or higher | judgment |
| `PRESSURE` | -0.35 to 0.35 | Share of Units and Bases with AP above HP or a pressure keyword, minus those with AP below HP | judgment |
| `INTERACTION` | 0.15 to 0.65 | Commands plus Blocker and board-hitting Units and Bases, over all cards | judgment |
| `ADVANTAGE` | 0 to 0.35 | Share of cards that draw, search or add to hand. A hand-add counts 1.0, a conditional one `CONDITIONAL_WEIGHT` = 0.5; Burst effects count; the Shield-to-hand baseline and the pilot "add this card" baseline do not | judgment |
| `FINISHER`, `RESILIENCE` | 0 to 0.25 | Shown, not part of the plan | default |
| `OPTION_WEIGHT` | 0.5 | An option card counts half in a deck's rating | judgment |
| `LINKS` | 0 to 12 pairs | The links rating; not part of the plan axis because every plan wants Link pairs | judgment |
| `HIGH` | 60 | A beatdown score at or above this is aggro | judgment |
| `LOW` | 40 | At or below this is control; between is midrange | judgment: moved 40 to 38 and back to 40 (2026-10-09). At 38, Master Asia + Domon Shining and Barbatos + Kira Strike Freedom (both 39) read midrange; after checking that pressure was measured right (31% of the Master/Shining list pushing, 16% sturdy), both read as control, which matches how they are played |
| `COLOR_MIN_SHARE`, `MAX_COLORS` | 0.20, 3 | A color is named when it is a fifth of the colored copies | default |

The plan axis is `beatdown = mean(curve, pressure, 10 - interaction, 10 - advantage)` (on a 0-100 scale).

## Suggested decks (`tools/gundam_collection/suggest.py`)

| Constant | Value | Meaning | Basis |
|---|---|---|---|
| `PLAN_SCORE` | aggro 70, midrange 50, control 30 | The beatdown score a plan aims for, inside its band | judgment |
| `DEFAULT_SHAPE` | Units / Pilots / Commands / Bases per plan | The deck shape when no found deck says | default |
| `KIND_SLACK` | 3 | A kind may exceed its target by this many copies | default |
| `MAX_SWAPS` | 14 | Swaps toward the plan inside the novelty budget | default |
| `FILL_FLOOR` | -0.25 | A known card this badly aligned is added only to reach 50 | judgment |
| `MAX_BUNDLES`, `BUNDLE_MIN` | 2, 0.15 | Partner packages brought in whole, and how strong one must be | judgment: so `barbatos aggro PB` shows the Char Aznable package |
| `LINK_BONUS`, `UNLINKED_PENALTY` | 0.25, 0.1 | Score for a Linked Unit with its pilot (or a pilot with its Units), and for a Linked Unit with no pilot | judgment: a Link is a bonus, not a gate |
| `PILOT_EXTRA` | 4 | Pilots that make Link pairs may exceed the usual pilot count by this many | judgment |
| `MIN_PILOT_PAIRS`, `PILOT_KEEP` | 2, 0.3 | A pilot picked on its own needs two copies' worth of pairs or a pull of 0.3 toward the plan, else it is filler | judgment: removed Sarah Zabiarov / Rosamia Badam / Loni Garvey singles |
| `PILOT_UNITS`, `PAIRED_HASTE` | 5, 0.2 | "Other pilots" are ranked by the best 5 Units they Link, judged with the pilot's stats added, plus a flat bonus for being usable the turn played | judgment |
| `POOL_SIZE` | 8 | Next-best cards shown per kind | default |

## Meta data (`tools/gundam_meta`)

| Constant | Value | Meaning | Basis |
|---|---|---|---|
| `GRACE_DAYS` | 2 | An event is stored two days after it ends | rule (decided with the user) |
| `EMPTY_EVENT_GRACE_DAYS` | 30 | An event with no decks yet is kept only once this old | judgment |
| `MAX_DAYS_APART`, `CONFIRMED_SHARE`, `LIST_ONLY_MIN_DECKS`, `LIST_ONLY_SHARE` | 3, 0.5, 5, 0.75 | When two sources' events are the same event (dates, shared decks) | judgment |
| `BUCKET_CUTOFFS` | 10 / 3 / 1 / 0.4 % | Online appearance-rate buckets: core meta, often, played, sometimes; below is niche | judgment, expected to be tuned |
| `EXPECTED_MAIN_DECK`, `MAX_SIDEBOARD` | 50, 10 | Deck sections | rule |

## Legality (`tools/gundam_cards/legality.py`)

`MAX_COPIES` = 4 and the banned and restricted lists are rules from Bandai's announcement, not tuning (see `notes/` and `sync-restrictions`).
