# Gundam Collection

**Status:** Draft for the planner (`plan`, `export`, the deck report). Built: the collection file and `check`/`template`, `import`, `coverage`, the cross-layer `card` view, and the links they use (`link.py`).
**Folder:** `tools/gundam_collection/`
**Backlog item:** IMPROVEMENTS.md > Collection and purchase planning (replaces the TCG Store Recommendation tool and the parked Collection management tool)

## Goals
These are the principles the whole tool is built to serve. **Every feature, ranking and default below exists to enforce one of them; if a change would break one, the change is wrong.** They apply to code, to this design, and to anyone (human or Claude) extending the tool.

The aim is a system that helps me **complete and manage a whole collection**, not build one deck: it joins what wins (real deck data), what I own, and what things cost, and answers "what should I buy next, cheapest and most useful first?"

### When I am building decks
The deck report must satisfy all four, every time:
1. **Critical cards needed to make a package work are not missed.** A package's *critical cards* are its core members (in at least 90% of the decks that play it). The deck report lists every critical card that is missing or short on copies.
2. **Critical cards needed to bridge packages together are not missed.** When a deck combines packages, the *bridge cards* between each pair (outside both, tied to both, in at least half of the decks that play both) are critical too, and are listed the same way.
3. **Flexible cards are identified and prioritized by real deck inclusions.** *Flexible cards* are cards outside any package that real decks run (synergy and free-floating cards). They are ranked by how many real decks include them (and how many copies), not by opinion.
4. **Alternative cards are considered, as redundancy and not as substitution.** **Functional reprints are redundant, not substitutes.** A card that does the same job as another (a *same-job* card) exists so a deck can run more copies of that job: 4 Close Combat plus 4 Battle of Aces, or both Kshatriya, because the strategy only works with all of them (burn is viable *because* of Close Combat and its kin). Every card keeps its own role (core, bridge, staple, option) and its own copy need, judged on its own appearance rates; being a reprint changes none of that, and owning one never covers a need for another. A reprint stands in for a card only when real decks do not play that card in the role (it is not core, not a bridge, not commonly played) and do play the reprint there at a comparable rate. Price differences are shown, not hidden: if the better card is expensive and the deck needs it, the deck is out of reach and the report says so (big Kshatriya GD01-044 is a hair better than the vanilla one, and your copies of the cheap one do not replace it). Cards tied to a package but never played (*candidates*) are shown separately as lower-confidence options. *Status: built 2026-10-08 (`alternatives.py`; the same-job match is `shared/samejob`).*

### When I am spending money on cards
Priorities, in the order they apply:
1. **Within my means (the first filter).** Money goes into areas where I already have support before totally new packages or decks. Spending is staged: *home* packages first, then packages *adjacent* to them, then new ones (only when I ask for it).
2. **Purchases provide value.** Money goes to cards that *enable* a package or deck (fill a missing slot) before it goes to the best possible card when an acceptable, cheaper alternative exists. Buy the cheapest acceptable alternative, not the strongest.
3. **Purchases are durable.** Among cards that fill slots, prefer ones that work in many scenarios (many packages, many decks) over ones that support a single package or deck.

Spending order: (1) decides which stage a card is in; inside a stage, (2) and (3) set the ranking, and price breaks ties. Every line in a purchase plan states which of these made it appear and where.

### Always (hard rules)
- Near mint only. No `+`, `++` or `LK` alternate-art purchases (owning any printing counts as owning the card).
- At most 4 copies of a card number, however many printings.
- All math is deterministic from counts and prices; nothing is a judgment call a person has to take on faith. Every recommendation shows its reason.
- Nothing is bought, scraped or logged into: the tool writes a list; I paste it into TCGPlayer myself.

## Purpose
Keep a typed record of my collection, measure how complete it is against what real decks play, and produce a ranked, explained purchase list I can paste into TCGPlayer's Mass Entry tool (TCGPlayer's own Cart Optimizer then finds sellers and shipping).

## Definitions (proposed answers to the open questions)

### What "complete" means (question 1)
Completeness is measured in **slots**, not cards. A **slot** is one place in a package or deck that needs some number of copies, and any of its alternatives can fill it. Completeness comes in layers, and the first target is layers 1 to 3 for home packages:

| Layer | What | Why |
|---|---|---|
| **1. Critical** | Core members of a package, and the bridge cards for the package pairs I play together | Goals 1 and 2: a deck without these doesn't work |
| **2. Flexible** | Cards outside packages that real decks run, ranked by deck inclusion | Goal 3 and durability |
| **3. Variants and alternatives** | Optional package members and alternatives to filled slots | Goal 4 |
| **4. Candidates** | Tied to a package, never played in real decks | "Worth testing", always optional |
| (later) Full catalog | Every card | Out of scope for now |

- **Copies needed** for a slot is the *majority copy count*: the largest number n such that at least half of the decks that play the package run n or more copies. (Not always 4.)
- A package is **buildable** when all its layer-1 slots are filled; a deck (an archetype) is buildable when each of its packages is, plus the bridges between them.
- **Completion** is reported per package (slots filled / slots needed, plus the cost of the gap), per archetype, and overall weighted by how often each is played.

### Home, adjacent and new packages
A package is **home** when I own at least half of its layer-1 slots (`HOME_MIN_OWNED = 0.5`). It is **adjacent** when it isn't home but shares at least one slot (a critical card, a bridge or a flexible card) with a home package. Everything else is **new**. With an empty collection nothing is home; then I name packages in `tools/gundam_collection/preferences.json` (hand-maintained), or the planner starts from the packages with the widest reach.

### Rules to bake in (question 3)
Beyond the hard rules above, these are defaults (named constants, adjustable):
- **Price tiers** from market price: bulk up to $0.50, cheap up to $2.00, mid up to $10.00, premium above. Lists are sorted by tier then rank.
- **Counted stand-in** (`alternatives.py`): only for an *option* card of a deck or an *optional* member of a package: a squad peer that stands in for it (the shared same-job match against the deck's pilots and Links), that real decks play at least half as often (`ALT_MIN_SHARE = 0.5`), in a color the deck plays. The cheapest counted card is the one priced. Core and staple cards never have counted stand-ins.
- **Budget:** `plan --budget <dollars>` caps a run; with no budget the plan prints running totals so I can cut anywhere. No standing budget is stored.
- **Exploring new packages** only with `plan --explore`.
- **Colors and archetypes** are not asked for: they follow from what I own (home packages) and from `preferences.json` pins.

## Collection input (question 2)
I type my binder into a plain text file, `shared/data/gundam_collection/my_tcg_collection` (hand-maintained, my source of truth). The tool turns it into structured data and reports every line it could not use. Re-running is idempotent: the file is read in full each time. **Card numbers only** (no names): a card number is exact, so nothing is ever matched by guessing.

```
# a comment; blank lines are fine
GD02-041 1          card number, then quantity (the format I started with)
4 GD05-002          quantity first also works
ST05-004 x2         "x" before or after the number is allowed (x2, 2x)
ST01-010+ 1         a trailing +, ++ or LK marks an alternate art of that card
ST05-006 ?          a placeholder for a quantity still to fill in
```

Checks (`check`, deterministic, no network; exits 1 only on errors):
- **Errors** (the line is not usable): not "card number + quantity"; not shaped like a card number; a card number the catalog doesn't have (close ones are *suggested*, never applied); a quantity that isn't a whole number from 1 to 99; an art marker the card has no printing for.
- **Warnings** (probably a mistake): the same card and art on more than one line (reported with all line numbers and the sum, so a double-typed page is visible); a quantity of 0; a `?` placeholder still to fill in.
- **Info**: resource, EX resource and token cards (kept, not used for deck building); an unusually large total for one card (over 12).
- A summary: lines read, distinct cards, total copies, by kind.

Ownership counts by **card number** (any printing satisfies a slot); the art marker is kept for the record. `template <SET...>` prints the unique cards a product contains as `CARD ?` lines (cards with a normal printing in that set, tokens included) so only the quantities have to be filled in.

## Usage
```
python3 -m tools.gundam_collection.cli check               # validate my_tcg_collection: bad lines, unknown cards, duplicates (built)
python3 -m tools.gundam_collection.cli template ST05 SC01  # unique cards in a product, as "CARD ?" lines to fill in (built)
python3 -m tools.gundam_collection.cli import              # my_tcg_collection -> collection.json; refuses if the file has errors (built)
python3 -m tools.gundam_collection.cli coverage [--source tournament|online|both]   # critical copies owned per package, home/adjacent/new, cost to complete (built)
python3 -m tools.gundam_collection.cli card GD01-026       # one card across every layer: facts, price, what I own, associations, coverage (built)
python3 -m tools.gundam_collection.cli decks               # every deck by completeness band, with the cost to the next band (design below)
python3 -m tools.gundam_collection.cli deck "Mikazuki Barbatos + Tekkadan"   # one deck: what to buy, with picks (design below)
python3 -m tools.gundam_collection.cli plan --budget 25    # ranked, explained purchase list
python3 -m tools.gundam_collection.cli export --format massentry   # the plan as text to paste into Mass Entry
```
(Run with `.venv/bin/python -m ...` from the repo root.)

## Inputs
| Input | From | Used for |
|---|---|---|
| `shared/data/gundam_collection/my_tcg_collection` | me (hand-maintained) | what I own |
| `shared/data/gundam_cards/cards.json` | `gundam_cards` | card identity, names, printings, kinds |
| `shared/data/gundam_cards/prices.json` | `gundam_cards sync-tcgplayer`, built on tcgcsv (Gundam is `categoryId` 86; market price per product; no per-seller or per-condition data) | per card: latest price in cents, the product it came from, the date pulled; read joined onto the card (`load_cards_with_prices`) |
| `shared/data/gundam_packages/packages.json`, `rates.json` | `gundam_packages` | packages, members and roles, bridges, reprint groups, appearance rates |
| `tools/gundam_collection/preferences.json` | me (optional) | pinned home packages |

**Required additions to other tools' contracts** (both done 2026-10-08: the copy histogram is in `rates.json` and `rates_online.json` as `histogram` on package members and partner cards, with `majority_copies`; prices are `prices.json` read through `load_cards_with_prices`):
- `gundam_packages` `rates.json`: a **copy-count histogram** per card in each package's decks (decks with 0, 1, 2, 3, 4 copies), so the majority copy count is exact; and the same for reprint groups (copies of any member).
- `gundam_cards`: `sync-tcgplayer` on tcgcsv (its own design change: a small one; honors tcgcsv's usage rules: custom User-Agent, 100 ms or more between requests, one pull per 24 h after checking `last-updated.txt`).

## Outputs
| File | Format | Key | Fields | Consumers |
|---|---|---|---|---|
| `shared/data/gundam_collection/collection.json` | JSON (envelope) | card number | `CollectionFile`: per card `copies`, `printings` (marker, copies), `notes` (binder headers) | this tool, others |
| `shared/data/gundam_collection/import_report.json` | JSON (envelope) | line number | lines not applied (reason, candidates), duplicates summed | me |
| `tools/gundam_collection/data/out/plan.json` | JSON (envelope) | slot | the purchase plan with reasons | export, me |
| `tools/gundam_collection/data/out/massentry.txt` | text | line | the pasteable list | TCGPlayer Mass Entry |

Models are frozen pydantic with `mypy --strict`, per `docs/tool-pattern.md`; money is integer cents; prices carry their fetch timestamp. Typed concepts: `CollectionEntry`, `Slot`, `SlotCoverage`, `PlanLine` (card, copies, cost, stage, reasons), `Stage` (home, adjacent, new).

## Approach
All steps are deterministic scripts; no LLM judgment.
1. **Import** the text, resolve each line (number, then exact name), write the collection and the report.
2. **Demand.** For each package in the current era's `packages.json`, build its slots: core members (layer 1) at their majority copy count, optional members (layer 3), and for each package pair I play, its bridge cards (layer 1). Reprint groups merge their members into one slot. Flexible cards come from the synergy and free-floating lists with their overall inclusion (layer 2).
3. **Subtract** what I own (functional reprints that keep the Link count toward a slot; see goal 4).
4. **Price** each missing slot with its cheapest acceptable alternative.
5. **Stage** each package as home, adjacent or new from the collection.
6. **Rank** missing slots inside a stage by `reach x unlock / price`, where:
   - **reach** = the share of all decks that run the card (or any acceptable alternative): how durable the purchase is;
   - **unlock** = the sum, over the packages that need the slot, of the package's played rate divided by that package's remaining missing slots (the last missing piece of a popular package is worth the most): how much it enables;
   - **price** has a 5-cent floor so free cards don't divide by zero.
7. **Plan** greedily down the ranked list, home stage first, until the budget runs out; **export** the text list; every line records its reasons.
The deck report applies steps 2 to 4 to one chosen deck and lists missing critical cards, bridges, flexible cards by inclusion, alternatives, and candidates.

## Data Sources
| Source | Access | Endpoint | Auth | Notes |
|---|---|---|---|---|
| tcgcsv.com | Static JSON/CSV | `https://tcgcsv.com/tcgplayer/86/<groupId>/products` and `/prices` | none | Updated daily about 20:00 UTC. Market price only, one price row per product. Alt arts are separate products (same `Number`, rarity with `+`). Probe results in `notes/tcgcsv.md`; rules in `notes/source-terms.md`. |
| TCGPlayer Mass Entry | I paste a file | n/a | my account | Exact line format not verified yet; need a sample. Nothing is automated against TCGPlayer. |

## Acceptance Checks
- Importing a sample binder file reproduces its counts; an ambiguous name, an unknown name and a bad quantity are each reported with a line number and are not applied; importing twice gives identical output.
- The deck report for Mikazuki Barbatos + Tekkadan lists the 3 Mikazuki core cards, the 4 Tekkadan core cards and the bridge Gundam Flauros as critical, with copies needed from the real copy histogram.
- Owning a peer of a core or staple card does not fill its slot; each card keeps its own need (see goal 4).
- The plan never includes an alt art, never takes a card number above 4 copies, never suggests a card I already have enough of, and never exceeds the budget.
- No new-stage line appears before every home layer-1 slot is filled, unless `--explore` is set.
- Every plan line prints its reasons (stage, slot, alternative chosen, reach, unlock, price tier); numbers recompute from `rates.json` and prices.
- Rebuilding gives identical files; files round-trip through the typed models.

## Completeness bands (decided 2026-10-08; replaces supported / close / far)

One ladder says **how much of a package or deck I have**, measured on copies: a package on its critical (core) copies, a deck on its core + staple copies.

| Band | Share owned | Meaning |
|---|---|---|
| **Perfect** | 100% | every copy |
| **Complete** | 90% to 99% | a few copies short |
| **Playable** | 75% to 89% | about 3 of 4 of each card: I would sleeve it |
| **Reachable** | 50% to 74% | "could get there": a real purchase away |
| **Long shot** | 25% to 49% | most of it still to get |
| **Not happening** | under 25% | |

- **Key-card guard.** A package or deck cannot be Playable or better while any **core** card has fewer than half the copies it needs (2 of 4, 2 of 3, 1 of 2; so "1 or 0" of a 4-of fails): the band is capped at Reachable. A key card cannot be covered by 2 copies and 2 "close enough" stand-ins; stand-ins never count for core (goal 4).
- **Small packages jump.** A package with few critical copies cannot land in Complete (7 of 8 is 87.5%, Playable). That is just how it is.
- **Cost to the next band** is always shown beside the band: Reachable shows the cost to Playable, Playable the cost to Complete, Complete the cost to Perfect (and Long shot / Not happening the cost to the band above). It is the cheapest set of missing copies that reaches the next threshold: the copies the guard forces first (for a Playable-or-better target), then the cheapest remaining missing copies; a copy with no price is counted separately, so the cost is a minimum. Cost is never part of the band name.
- **Home / adjacent / new stays a separate axis** (where to invest, not how much I have): home is at least 50% of the critical copies, i.e. Reachable or better.
- The same ladder is used for decks (`decks`, `deck`) and packages (`coverage`); "decks I support or am close to" now means Playable or better.

## Deck style: ratings and plan (decided 2026-10-08)

"What the decks do" comes from the deck's own cards, as **ratings** (0-100, each one measured number mapped between two named anchors in `styles.py`, so they are explainable and tunable) and a **plan**. After "Who's the Beatdown" (SCG, 1999): with no true combo in this game, every matchup you are either the beatdown or the control, so a deck is pure beatdown, pure control, or flexible.

| Rating | High means | Measured as |
|---|---|---|
| **Curve** | an aggressive curve: lots of small Units | share of Unit copies at Lv3 or less, and how little is Lv6+ |
| **Pressure** | Units that hit harder than they take | Units with AP greater than HP or a Breach / Suppression / High-Maneuver keyword, minus Units with AP less than HP, over Units (Blockers are interaction, not pressure) |
| **Interaction** | answers to the opponent's board | Commands plus Units that have a Blocker or an ability that damages, destroys, bounces, -APs or rests (each Unit once, full weight), over all copies |
| **Advantage** | lots of cards put in my hand | cards that put a new card in my hand ("draw N", "add ... to your hand"; draw-then-discard counts), at full weight, or half when a condition gates it (an "if" that is not "if you do", a "when ..." trigger, a Destroyed trigger, a filtered search, a pick from the trash). "Look at the top N" alone and deploying from the trash do not count |
| Finisher (not in the plan) | a way to top out | Lv7+ Units, half for Lv6 |
| Resilience (not in the plan) | survives while setting up | Bases, Repair Units, protect effects |

- **Plan: a beatdown-to-control axis (revised 2026-10-08).** The mean of four ratings: curve, pressure, **low** interaction (100 minus it) and **low** advantage (100 minus it). A pure beatdown wants a fast curve and pressure and needs neither answers nor cards; a control deck wants answers and a steady supply of cards. **Aggro** = 60 or more, **Control** = 40 or less (it was 40 at first, then 38 so that Barbatos + Kira Strike Freedom, at 39, read midrange; back to 40 on 2026-10-08, because both that and Master Asia + Domon Shining, also at 39, are better called control than midrange; the pressure behind Master Asia + Domon Shining was checked card by card and is a real, moderate lean from its Maxter and Rising fighters), **Midrange** = between (it can be the beatdown or the control). Advantage weighs in. Only these three labels; no combo, burn or ping labels. (The first version required curve, pressure and interaction each to clear a line; that left control decks with an ordinary curve as midrange.)
- **Displayed out of 10** with one decimal (4.2, 1.6) beside the deck in `decks`, `deck` and `styles`; the plan's lines are 6.0 (aggro) and 3.8 (control) on the same scale. The 0-100 values are internal.
- **A deck gets one plan plus its ratings.** Colors: the colors with at least 20% of the colored copies, most copies first (`R/G`).
- **Weights:** core and staples count fully, options half.
- **Revised 2026-10-08 after review:** pressure used to subtract Blockers and interaction gave board-hitting Units half weight; both were wrong. Blockers are interaction; pressure is about AP against HP and the pressure keywords. The anchors for pressure (-0.35 to +0.35) and interaction (0.15 to 0.65) were widened so decks do not all saturate at 100.
- **Advantage revised 2026-10-08:** it used to count any draw, search or revive, including every Base's baseline Shield-to-hand. It now means "puts a card in my hand" with a condition halving it (Barbatos 1st Form's "if this Unit is damaged, draw 1" is half); anchors 0 to 0.35. Mikazuki Barbatos decks drop from 59 to about 20.
- **Calibration:** `styles --explain` prints the ratings and the measured numbers for the most played decks; the labels are checked against what I know of the meta and the anchors tuned.
- **Built (2026-10-08):** `styles.py` (pure; 6 tests), the `styles` command, and colors and plan in the `decks` table and the `deck` header. Assumption to confirm: "burst" among the beatdown's wants was read as the Breach keyword.

**Edits are picked up automatically (2026-10-08).** Every view first compares `my_tcg_collection` with `collection.json`; if the file is newer and has no errors it re-imports it and says so on stderr (`note: my_tcg_collection changed, re-imported ...`); with errors it keeps the last good import and says so. `import` still works on its own.

## Buy recommendations: `buy <archetype>` (decided 2026-10-08)

"I want to play more of the Suletta archetype: what should I buy?" The unit is an **archetype** (not a global ranking): the tool turns what the archetype's decks still need into an ordered, explained shopping list. It never buys or scrapes anything; it writes text you paste into TCGPlayer.

- **Input:** words of an archetype name (`buy suletta`), or **every deck that contains a package** in any role (`buy --package "char aznable (b)"`, or its anchor `--package ST11-001`: a package is usually a deck's *secondary* part, so it is not the archetype the deck is filed under), or specific decks (`--deck redletta`); they combine. Words of an archetype name: Every archetype whose name has all the words is used together (Suletta Aerial midrange and control), and they are listed; no match lists the archetypes. Decks below the fringe floor are left out (`--min-rate`).
- **Playable first.** For each deck of the archetype that is not yet Playable, the list is the cheapest copies that make it Playable (the key-card guard's copies, then the cheapest missing ones: `bands.cost_to`). Decks already Playable or better are listed as "you can already play these".
- **A path, not one deck.** Greedy and deterministic: pick the deck that is cheapest to make Playable, treat those copies as bought, then pick the next deck by its **incremental** cost (cards shared with the first deck are now free), and so on (`--steps`, default 3). Each step shows the cards to buy, the cost of the step, the running total, and which other decks of the archetype it also moves up ("this also makes Suletta Aerial + Academy Playable").
- **Each line says why:** `4 x Char's Gelgoog [GD01]  $1.20 = $4.80  (core of X; also needed by 2 other decks in this archetype)`. Copies never take a card past 4 owned; near mint, the cheapest printing, no alt art (the price rows already follow these).
- **Premium cards ($10 or more) are never included without asking.** They are always considered, shown inline as SKIPPED and once more in a "skipped premium cards" summary with the cost, the decks they hold back, and the cheapest same-job alternatives (never counted); a deck whose Playable needs a premium copy stays in the path with its regular copies, the premium copies are marked **skipped** (not bought, not in the totals), it is flagged as not Playable until you approve them, and it comes after the decks that can be finished. `--include-premium` treats them like any other card.
- **Alternatives for expensive cards (`--alt-from DOLLARS`, default 5.00).** Under every card to buy whose price is at least this, the plan shows the cheapest same-job alternatives (never counted, and the card is **not** skipped: only premium cards are), how many of each I own, and **any same-job alternative I already own** (any price, any color; a color the deck does not play is flagged). A card the deck already runs is not an alternative. If nothing matches it says so, so "none exist" is never confused with "not checked". The threshold is separate from the $10 premium line, which still skips.
- **The same alternatives in `deck`** (`--alt-from`, default 5.00): under every pick of at least that price, the cheapest same-job alternatives, what you own of each, and any alternative you already own; `--alternatives` still lists them for every missing core and staple card at any price.
- **Polish (`--polish`):** after the Playable steps, the copies that take **every Playable deck of the archetype** (the ones the steps just made Playable *and* the ones already Playable) to Complete, cheapest first, copies shared between decks counted once.
- **No budget cap.** The running total lets you cut anywhere.
- **Export (`--export [path]`):** one TCGPlayer Mass Entry line per card, `quantity name [set]`, such as `4 Char's Gelgoog [GD01]`, using TCGPlayer's own product name and the set of the cheapest printing (so the price rows now carry `name` and `set_code`; Edition Beta printings read `[GD01_b]`). Excluded: premium cards unless `--include-premium`.
- Your blue is still being typed; nothing is worked around: the lists assume what is in the file.

## Deck identity: id, name, nickname (decided and built 2026-10-08)

Many decks share a pilot ("Marida" can mean five decks), and two different packages can share a name, so a deck has three ways to be named:
- **Id** (stable, deterministic): the anchor cards of its packages, sorted and joined: `GD02-054+ST11-001`. A package found in both sources has the same anchor in both, so the same deck has the same id whichever source it came from. Shown with `decks --ids`, `styles --ids`, in the `deck` header and in every "several decks match" list.
- **Name** (readable): the package names joined with " + ". Where one package *name* belongs to different packages (the tournament Char Aznable is anchored on a green Char's Zaku II, the online one on a blue Z'Gok), only that name gets its color letter (R/B/G/W/P): `Mikazuki Barbatos + Char Aznable (G)`. If two decks still share a name, each gets the cards it is anchored on in brackets. Names are worked out over all decks, so the floor on play rate does not change them.
- **Nickname** (yours): `nickname "<deck>" redletta` stores it in `shared/data/gundam_collection/deck_names.json` by id (`--remove`, `--list`); it replaces the name everywhere and the generated name stays in `deck`.
- **Lookup** (`deck`, `nickname`): an id (any case, any punctuation, anchors in any order, so `gd02054 st11001` works), then a nickname, then an exact name, then every word (or card number) of a name, then digits only when unique. Several matches are listed with their ids, never guessed. Digits alone are accepted only because the lookup refuses to guess: GD01-001 and ST01-001 would both read `01001`.

## Deck suggestions: `suggest` (decided 2026-10-08)

`suggest barbatos aggro PB` builds **hypothetical decks**: the *shape* comes from real decks, the *cards* are chosen by the ratings. It is explainable and deterministic, stays close to known lists, and always gives an exact 50 (so it can be rated) plus a pool of other options.

- **Input.** Words of a **package** (`barbatos`, or `--package ST11-001`), a **plan** (`aggro`, `midrange`, `control`) and **color letters** (`PB`, `pb`: R B G W P). A specific color pair is used as given and must include the package's color. With no colors, one deck is built for every second color, shown grouped by color (B, then G, R, W), each with its own reference decks. A missing plan is taken from the package's most common plan.
- **Card-level ratings.** The deck ratings are measured on single cards too (`card_signals` in `styles.py`, shared by the deck rating): a Unit's curve (Lv<=3 low, Lv6+ top), pressure (AP over HP, Breach / Suppression / High-Maneuver) or sturdiness (AP under HP), whether it interacts (Blocker or a board-hitting ability) or draws (a card in hand, halved if conditional), finisher and resilience. A card's **plan alignment** is how well that fits the plan: aggro likes cheap, hard-hitting, non-interactive Units and cheap damage; control likes Blockers, answers and card advantage; midrange is the middle.
- **Known first.** Reference decks are the found decks that contain the package in the chosen colors (and, for plan staples, found decks of the same plan in those colors). Each card gets a **known weight**: how often, among those decks (weighted by how played they are), the card is run, and at what copy count. The package's core is **locked** at its real copy counts.
- **Shape from data.** How many Units, Pilots, Commands and Bases a deck of this plan has comes from the found decks of that plan (their median), not from a rule. A Linked Unit is only added if the deck has a pilot that satisfies its Link.
- **Fill, then adjust.** (1) Lock the core. (2) Add known cards, most known and best aligned first, within the shape and 4 copies. (3) If the deck still reads as the wrong plan, swap the least aligned non-core card for a better aligned one (known elsewhere, or **novel**: not in any found list), at most a few novel swaps (`--novelty`, default low) and each is labeled novel. (4) Rate the 50 with the same ratings as any deck.
- **Pool.** The best cards not chosen, by role (Units, Pilots, Commands, Bases), with why: how proven, how aligned, owned, price.
- **Ownership and cost, both.** `--prefer fit` (default: the ratings decide), `--prefer owned` (owned cards win near-ties, so the deck is as buildable as possible) or `--prefer cost` (cheaper cards win near-ties). Every deck shows what I own, the cost to build, its band, and, for any card of $5 or more, same-job alternatives and the ones I already own, as in `buy`.
- **Not done by it:** it never edits my collection or buys anything; to buy a suggestion, `buy --deck` plans it once a deck is a real archetype, or read the cost to build.

## Archetypes (decided and built 2026-10-08)

Single-deck play rates are all small (the best is 12% and only 8 decks reach 5%), because decks are packages jammed together: "Marida" can mean five decks. An **archetype** is what a deck is known as: its **primary package** plus its **plan**, like "Mikazuki Barbatos aggro" or "Kira Strike Freedom control".
- **Primary package = the most-played package in the deck**, from the raw package rates (averaged over the sources the deck is played in; ties to the lower anchor card). No judgement about which package "drives" the deck: that cannot be read from the data, and the opponent's "oh, Marida again" is about what is most seen.
- **Each deck is in exactly one archetype**, so archetype shares add up to the meta (98% of both sources) and a pair of packages that always play together (Kira Aile Strike and Kira Strike Freedom) is not counted twice. An archetype's share is the sum of its decks' play rates, per source (T / O).
- **The plan splits the same package** (Amuro Ray aggro is 20% of tournament decks; Amuro Ray control a separate archetype).
- Names are the package name (they already read pilot-style), with a color letter only where two packages share a name.
- **The fringe floor uses the archetype** (`is_played`): a deck is kept if its own play rate reaches the floor in some source (default 5%), or if it is a real variant of an archetype that does (its own rate at least a fifth of the floor, 1% by default), so Mikazuki Barbatos + Char Aznable (B), 2% online inside a 12% archetype, is shown while a 0% variant is not. `decks` shows each deck's id by default (`--no-ids` hides it).
- **Shown:** an `archetype %` column in `decks` (`--sort archetype` puts the biggest first), an `archetype:` line in `deck`, and `archetypes`, which lists each archetype with its share, its decks and how close I am to the closest of them. Built in `archetypes.py` (pure; 4 tests).
- **Known soft spots:** a deck near a plan line (a beatdown score of 40 vs 41) lands in a different archetype; tiny-sample decks are noisy; tournament and online disagree a lot (Kira control is 36% of tournament decks but 7% online), so both are always shown.

## What is built: the linked views (2026-10-08)
**The links.** Everything joins on the card number: the master card model and its latest price (`gundam_cards`, `PricedCard`), what I own (`collection.json`), and the associations (`packages*.json`, `rates*.json`, for tournament and online decks). `link.py` is pure functions over loaded data; the CLI loads the layers and prints.
- **Slot:** a place in a package that needs copies of one card; every required card is its own slot (same-job cards are redundant, not substitutes). Copies needed = the **majority copy count** from the histogram (the most copies at least half of the package's decks run). **Critical** = the core members' copies; optional members are layer 3.
- **Coverage:** critical copies I own over critical copies needed, per package; **cost to complete** = the missing critical copies at the cheapest printing's market price (a minimum, and it says so, when a card has no price).
- **Stage:** home = I own at least half of the critical copies; adjacent = not home but shares a critical card (a core member or a bridge) with a home package; new = neither.
- **`card <number>`:** the card's facts, price and copies owned; then for each source the package it is in (or the two it is played with most), its stage, what I still need to complete it (with the price, and uncounted similar cards), and a table of every associated card with its rate, copies needed, copies owned and price.
- **Found while building:** pricing a missing Char's Zaku II slot at the cheapest *reprint* (Re-GZ) was wrong, since the card is in the Char Aznable package through a Link to its pilot. That led to the redundancy rework (2026-10-08): a peer never covers a core or staple card; see `alternatives.py` and goal 4.

First run on the real data (164 cards, 535 copies, all the starter decks typed so far): Kira Aile Strike is complete (8 of 8 critical copies, the ST04 deck), Amuro Ray 5 of 8, Mikazuki Barbatos 4 of 12 and $210 to complete (Gundam Barbatos 1st Form alone is $43.44), Marida Kshatriya $179 (Kshatriya $44.29).

## Price analyzer: `value` (2026-10-08)
`python3 -m tools.gundam_collection.cli value [--bands 0.5,1,5,10] [--limit N] [--bulk]`: what my collection is worth, from `collection.json` and the latest `prices.json` (no network). Each card is valued at its latest TCGPlayer market price times my copies. **Bands are contiguous, in whole cents:** `under $0.50` (bulk, counted but not listed unless `--bulk`), `$0.50 to under $1`, `$1 to under $5`, `$5 to under $10`, and `$10 or more`. Edge rule (changed 2026-10-08): **every threshold opens the band above it**, so a card priced at exactly a threshold is in the higher band (a card at $0.50 is "$0.50 and above"); the header also shows the value with the bulk ignored (cards of $0.50 or more, the ones worth selling) and the bulk's own value.

## Deck report: `decks` and `deck` (agreed 2026-10-09; built)
**Purpose.** Show which decks my collection supports, which it is close to supporting, and for one deck exactly which cards to get next. It **never produces a 50-card list**: its job is to grow the collection, so it reports gaps and picks (what to buy, how many, what it costs, why), under the goals at the top of this file.

**A deck is an archetype**: the set of packages real decks run together (from `packages*.json`, e.g. Mikazuki Barbatos + Char Aznable). The same deck found in both tournament and online decks (its packages match, at least half of their cards shared, as `compare` does) is one row with both play rates; otherwise it is a row for the one source that has it.

**What a deck needs (three layers).**
| Layer | Cards | Copies | Principle |
|---|---|---|---|
| **Core** | the core members of every package in the deck, and the **bridge cards** between each pair of its packages | the majority copy count | goals 1 and 2: never missed |
| **Staples** | cards that at least half of the deck's lists run and are not core | the majority copy count in this deck's lists | goal 3: ranked by real inclusion |
| **Options** | optional package members, and cards in 25% to 50% of the lists | the majority copy count | layer 3: last, never needed to play |

Reprints follow the redundancy rule in goal 4: each card keeps its own need; a reprint stands in only for a card real decks do not play in that role. A card with several numbers is bought at its cheapest printing *where one number truly suffices*.

**Support levels: superseded 2026-10-08 by the completeness bands above** (Perfect / Complete / Playable / Reachable / Long shot / Not happening, with the key-card guard and the cost to the next band). The old levels, for the record (the 5% play-rate floor and the staples-count decision still stand):
- **Supported**: I own every **core and staple** copy: the cards I need to have a working deck. (Decided 2026-10-09: staples count, since a deck without them is not playable.) The core is still shown on its own, and the options (not needed to play) are shown but not counted.
- **Close**: not supported, but I own at least 70% of the core and staple copies (now: Playable is 75% plus the guard).
- **Far**: everything else; listed only with `--all`.
Each deck row also tags its packages as home, adjacent or new, since goal "within my means" says to grow where I already have support first.

**Data this needs (a `gundam_packages` contract addition).** `rates*.json` gets, for each archetype, a **card table** `cards[]`: every package core member and every card in at least 25% of the archetype's lists, with `card_number`, `role` (core, optional, bridge, synergy, free_floating, other), `decks` and `share` (how many of the archetype's lists run it), the copy `histogram` and `majority_copies`, and a `low_sample` flag when the archetype has few lists. It is computed in `rates.py` from the same copy decks, so a staple's "copies needed" is what half of this deck's actual lists run, not a guess. Bridge roles come from the package pairs inside the archetype.

**`decks` (the overview).** Lists decks played in at least **5%** of decks in at least one source (`--min-rate`; a deck in only one source qualifies if it clears 5% there), in three groups. Illustrative output:
```
== decks I support (every core copy owned) ==
deck                                 played in          core       staples   packages
Kira Aile Strike                     37% T / 9% O       8/8        3/6       home
Amuro Ray + Amuro Nu                 12% T / 4% O       ...

== decks I am close to (at least 70% of the core copies owned), cheapest to finish first ==
deck                                 played in          core       to finish   missing   packages
Amuro Ray + Char Aznable             8%  T / 3% O       13/16 ...  $4.61       3 cards   home + new
Mikazuki Barbatos + Tekkadan         9%  T / 6% O       ...
```
Close decks are sorted by the cost to finish the core (cheapest first), then by how often the deck is played. A deck that starts a package I do not have is marked, so I can see when "close" means "start something new".

**`deck <name>` (one deck).** The name matches an archetype or its package names (several matches are listed, never guessed). The output, in order:
1. **Header:** the deck, its packages with colors and stages, play rates in each source, support level, core copies owned, and the cost to finish the core and to add the staples.
2. **Core:** per package, each critical slot: card, copies needed, copies owned, missing, price (cheapest printing), with premium cards (price at the top band) flagged. Then the bridge cards for each pair.
3. **Staples:** ranked by inclusion in this deck (the share of its lists), each with need, owned, price, and **durability**: how many other decks that are Playable or better also need the card.
4. **Options** (`--options`): optional members and 25-50% cards.
5. **Alternatives** (`--alternatives`): for each missing core or staple card, the cheapest same-job cards in the whole catalog, played or not (`candidates`, from the shared same-job match against the deck's pilots and Links), each marked better or trade-off and flagged when it needs a color the deck does not play; plus squad peers real decks run. None are ever counted toward the deck. Example: for the $44.29 Kshatriya GD01-044 it offers Shamblo ($0.25, red, better), Kshatriya Besserung ($0.16, needs blue) and the two Banshees.
6. **Picks:** the ordered list of what to get, which is the answer to "what do I buy for this deck".

**Picks (deterministic, each line explained).** Every missing copy is a candidate, ordered by:
1. **Layer:** core first (goal 1 and 2), then staples, then options. Spending goal 2: money goes to what makes the deck playable before what improves it.
2. **Durability** (spending goal 3), within a layer: the card also needed by more of the other Playable-or-better decks first, then by how often those decks are played.
3. **Staples** order by inclusion in this deck, then durability.
4. **Price, cheapest first** as the tiebreak, always at the cheapest printing (spending goal 2: not the best card when a cheaper acceptable one exists).
Each pick says: copies to buy, unit and line price, why ("core of Tekkadan", "bridge between Mikazuki Barbatos and Tekkadan", "in 87% of this deck's lists"), where else it is needed, and the running total. A marker shows where the core is complete ("with these 7 copies, $14.20, you can play the core").

**Both sources.** The default is both: a slot is critical if it is critical in either source, at the larger copy count (goal 1: never miss a critical card); each line says which source needs it. `--source tournament|online` restricts to one.

**Outputs.** Read-only views (no new files). All numbers come from `collection.json`, `prices.json`, `packages*.json` and `rates*.json`.

**Acceptance checks (a first list).**
- Every core copy of a deck's packages, and the bridges of each pair, appear in its core section (goals 1 and 2); the Mikazuki Barbatos + Tekkadan deck lists the three Barbatos cards, the four Tekkadan cards and the bridge Gundam Flauros.
- A deck whose core copies are all owned is Supported and only then; owning 70% or more (and not all) is Close; the counts and costs equal the sum over its slots.
- Reprints are redundant, not substitutes (goal 4); a card number is still a card.
- Staples are ordered by inclusion, and a card needed by several decks shows its durability.
- Picks are ordered by layer, durability and then price, the cheapest printing is priced, the running total is exact in cents, and no pick exceeds the copies the deck needs.
- No output is a 50-card list.
- The overview and the one-deck view agree on a deck's counts and costs; rebuilding gives identical output.

**Out of scope.** A 50-card list or deck legality; sideboards; matchups and counter picks; buying or logging in anywhere.

**Decisions (confirmed 2026-10-09).** (1) Close = at least 70% of the core and staple copies. (2) The play-rate floor is 5% in at least one source. (3) Both sources by default, with the union of critical slots (critical in either, at the larger copy count). (4) **Staples count toward supported** (as above). (5) Premium cards (priced at $10 or more) are flagged with a star in the core, staples and picks, never skipped.

### Deck report: what was built (2026-10-09)
`decks [--source tournament|online|both] [--min-rate 0.05] [--all] [--limit N]` and `deck "<name words>" [--options] [--alternatives]` in `cli.py`; the logic is `decks.py` (pure functions, 11 tests on the synthetic worlds). Findings while building:
- **The data it needs is in `rates*.json`:** per archetype, `cards[]` (`ArchetypeCard`: role, decks, share, copy histogram; every package member and every card in at least 25% of the archetype's lists) and `low_sample` (under 20 decks). Same deck in both sources: the packages match by shared cards (`shared/overlap.py`, moved out of `gundam_packages` because two tools need it).
- **Copy counts:** the majority copy count is 0 for a card under half the lists, so options and sub-half bridge cards use the **typical** count (the most common count among the lists that run the card; `typical_copies`).
- **One "in N% of its lists" per card**, not one per source (the larger share).
- **Matching a deck name:** every word must be in the name; a single exact name wins; several matches are listed, never guessed.
- **Built (2026-10-08): the redundancy rework.** The collection tool no longer merges reprints into slots; the same-job match is `shared/samejob` (shared code, so both tools can use it) and squads come from `packages*.json`. Result for Marida Kshatriya + Haman Qubeley + Full Neo Zeong: FAR (34 of 50 core and staple copies), $224.76 to finish the core, because the $44.29 Kshatriya GD01-044 and the $10.53 Char's Zaku II ST03-006 are each still needed and the cheaper same-job cards do not cover them.

First run on the real collection (244 cards, before all colors were typed): no deck is supported or close yet (a working deck is about 50 copies of core and staples, so the bar is high while the collection is partial); the closest are Marida Kshatriya + Haman Qubeley + Full Neo Zeong (online, 33 of 50 copies, $22.17 to finish) and Kira Strike Freedom + Kira Aile Strike + Amuro Ray (17 of 54, $176.81). `deck "Master Asia + Domon Shining"` shows 22 core copies to get for $15.95 (the Domon Shining cards are $0.12 to $0.88 each; Darkness Finger is $7.91) and 42 copies for $93.10 to finish the working deck, with Argama ($15.02) flagged premium.

## Out of Scope
- Finding sellers, cart optimization and shipping (TCGPlayer's Cart Optimizer does it); any scraping of TCGPlayer or login on my behalf.
- Condition-level or per-seller inventory (tcgcsv has none).
- Selling or trading; price history; image or barcode scanning of the binder.
- Counter picks and sideboard options (need matchup and sideboard data we are not yet permitted to collect; they would attach later as another demand layer).

## Open Questions
- **Which decks set the demand:** the tournament packages, the online packages, or both. Proposed: both. A slot is needed if either source has it; **reach** is the average of the card's share of tournament decks and of online decks (so a card only the online field plays is still durable, and one only tournaments play is too). Confirm.
- **Price to use:** `marketPrice` (default) or `lowPrice`. Market price is the typical sale; low price is the cheapest listing and swings more.
- **Promo groups** (`GCG-PR`, `EXBP`, `EXRP`, `RP`) are excluded from purchases by default; their cards are not generally buyable singles.
- **Mass Entry format:** I need a sample line from the tool (does it take set or product info, to pick the right printing?).
- **Which era's decks set the demand:** my default is the latest era with enough decks (GD05), with drift (GD05.5) shown beside it as a flag, not blended in. Confirm.
- **Minimum order:** should the plan pad to a $5 minimum (TCGPlayer's free-shipping line applies per seller)? My default is no padding, since the optimizer splits across sellers.
- **Thresholds** (`HOME_MIN_OWNED` 0.5, `ALT_MIN_SHARE` 0.5, the price tiers, the 50% majority copy rule): defaults above; adjust after seeing a first real plan.

**Built (2026-10-08): the bands.** `bands.py` (pure: `Band`, `Need`, `band_of`, `next_band`; 7 tests), used by `link.py` (`PackageCoverage.band`, `.next_band`) and `decks.py` (`DeckCoverage.band`, `.next_band`, `.playable`; `overview` groups by band). `coverage` and `decks` show the band and the cost to the next band; `deck` also lists the exact copies to buy for the next band. First run: online packages 9 perfect, 1 complete, 7 playable, 5 reachable, 3 long shot, 8 not happening; decks: Master Asia + Domon Shining is Playable ($0.12 to Complete); Marida Kshatriya is Reachable, $88.58 to Playable (two GD01-044, the key-card guard).

**Built (2026-10-08): `buy`.** `buy.py` (pure planner; 7 tests) and `cli.py buy <archetype words> [--steps N] [--polish] [--include-premium] [--export [PATH]] [--min-rate X]`. The price rows now carry TCGPlayer's product `name` and `set_code` (`prices.json` schema 2; rebuilt from the raw cache with `reparse-tcgplayer`, no refetch). First runs: `buy suletta` is 3 steps for $4.73 (1 Gundam Schwarzette, 3 Michaelis, 1 Aegis Gundam + 1 Gundam Aerial) and `--polish` takes every Playable deck (the ones the steps made Playable and the ones already Playable, such as Suletta Aerial + Haman Qubeley) to Complete, cheapest first with shared copies counted once, for $49.75 total; `buy marida kshatriya` has nothing to buy without approval: every Marida deck is held back by 2 x Kshatriya GD01-044 ($88.58), and two by 2 x Char's Zaku II ST03-006 ($21.06), listed once with Shamblo / Besserung / the Banshees as alternatives that are not counted.

**Built (2026-10-08): `suggest`.** `suggest.py` (pure builder; 10 tests), `styles.card_signals` (the card-level ratings, shared with the deck rating; refactored with identical results on all 60 rated decks) and `cli.py suggest <package words> <plan> <colors> [--package ANCHOR] [--novelty 0.2] [--prefer fit|owned|cost] [--pool N] [--alt-from X]`. Found while building: references must be of the **same plan** (a Kira *control* deck that happens to include Barbatos was feeding Kira Yamato pilots into a Barbatos *aggro* build, so decks of another plan are ignored and the note says how many), and a pilot is only admitted if it satisfies the Link of a Unit already in the deck. `suggest barbatos aggro PB` rates aggro (beatdown 8.6, 41 of 50 owned, $4.04 to build); with no colors it builds B/P, G/P, P/R and P/W grouped by second color.

**Bases, Burst and the banned / restricted list (2026-10-08).**
- **Bases count toward the ratings like a body** (`styles.card_signals`): a cheap Base (Lv3 or less) is a low curve, a Base that deploys a token with AP over HP is pressure (AP under HP is sturdy), and a Base that hits the opponent's board (damage, destroy, bounce, rest, -AP) is interaction (Gundam Fight). The Shield-to-hand baseline is still not advantage; a Burst effect that puts a card in hand is (a conditional one is half), and the pilots' "add this card to your hand" baseline is not. Corsica Base reads aggro (fit +0.8). Effect on 59 rated decks: curve +0.8 on average (most Bases are cheap), 7 decks cross a plan line (six control to midrange, one midrange to aggro); the Kira Strike Freedom decks stay control and Barbatos + Kira stays midrange.
- **The banned / restricted list is applied** (`gundam_cards/legality.py`, data from `sync-restrictions`): found decks' needs are clamped to each card's limit (Corsica Base 2) and banned cards dropped; a found deck that breaks a banned pair or runs two different vanilla 2/2 Units (the group the page describes) is flagged `!` in `decks` and `NOT LEGAL as found` in `deck`, and `buy` leaves it out (3 of 123 today, all Amuro Ray decks: the data predates the 2026-09-25 list). `suggest` never builds an illegal deck: it respects copy limits, banned pairs and one vanilla card per deck, in the deck and in the pool. Before this, its Barbatos aggro build had five vanilla 2/2 Units.

**`suggest` and Links (2026-10-08, after review).** A Link matters more than the first version gave it credit for: a pilot adds its stats to the Unit, and a Linked Unit can be used the turn it is played, which helps aggro and interaction alike. So:
- **A Link is a bonus, not a gate.** A Linked Unit with its pilot in the deck scores higher; one without is a weaker body but is not excluded (found decks run those). A pilot is scored by the Linked Unit copies it pairs with, may exceed the usual pilot count when it makes pairs, and a pilot that pairs with nothing is a single stat-bonus copy at most.
- **Partner packages come in whole.** The reference decks' other packages (a pilot and the Units it Links) are brought in together, up to two, so `suggest barbatos aggro PB` shows the Char Aznable package (Char's Z'Gok x4, ZnO x3, the pilot x4) instead of one card at a time.
- **Pairs are shown:** `link pairs: N possible (L Linked Unit copies, P pilot copies)`, a section listing each pilot with the Units it pairs with, and **other pilots worth a look** (pilots not in the deck, the Unit copies they would pair with here and the Units they would Link).
- **Kinds are reserved:** while filling, a kind may not take the slots the others still need for their own shape (found: Units were crowding the Bases out; Corsica Base had dropped out). It relaxes at the end so the deck is always exactly 50.
- **Links rating (2026-10-09).** `style_of` also rates **links** out of 10: the Link pairs a deck's core and staple cards can make, scaled 0 to a dozen (`LINKS`). It is shown beside the other ratings (`suggest`, `styles`, `deck`) but is **not** part of the plan axis, since every plan wants Link pairs.
- **Other pilots are ranked by fit.** A pilot not in the deck is scored by the plan fit of the best `PILOT_UNITS` Units it Links, each judged **with the pilot's AP/HP added** plus `PAIRED_HASTE` (usable the turn it is played), plus their known play, plus a little for pairs it already makes here. So Ple-Twelve (Marida Cruz) surfaces through Kshatriya Besserung and the purple Banshees even when none of them is in the deck yet. The list is the only pilot list: the pool no longer repeats pilots.
