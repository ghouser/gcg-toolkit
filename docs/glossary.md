# Glossary

The words and variable names used across the tools, so docs, code, CLI output and conversation mean the same thing. Terms from the game itself use the game's own words (Comprehensive Rules). When a term here is a column or field name, the code name is in `backticks`.

## Data: decks and counts
| Term | Meaning |
|---|---|
| **Deck** | One counted deck list from an event: a player's **main deck** (sideboards are separate tech). We have deck data, not match or game data. |
| **Counted deck** | A deck that is readable (not private, no unresolved cards). Private decks are never bypassed and are reported as not counted. |
| **Window** | The decks used in one analysis: an era plus the tiers (major, local) chosen. |
| **Era** | A span of time that starts when new cards enter the game (a set release), such as GD05 or GD05.5. Defined in `eras.json`, resolved against release dates at read time. |
| **Tier** | Event size: **major** (regional, world, qualifier) or **local** (store championship, Newtype Challenge). |
| **Copies** | How many of a card a deck plays, 0 to 4 (the rules cap it at 4). Only deck cards count (not resources, EX cards, tokens). |
| **Deck card** | A Unit, Pilot, Command or Base. |
| **Source** | Where data comes from: DuelFrontier and EGM Events (deck lists from physical events), the online ranking (per-card rates). Events seen in two sources are de-duplicated. |

## Cards
| Term | Meaning |
|---|---|
| **Trait** | A tag on a card, like `(Tekkadan)` or `(Earth Alliance)`. `/` between traits means "or". |
| **Keyword** | A named ability from the Comprehensive Rules, like `<Blocker>` or `<Breach>` (21 of them). |
| **Link** | A Unit's requirement for a Pilot: a named pilot (`[Mikazuki Augus]`) or a trait (`(Orb)`). |
| **Pilot** | A Pilot card, or a Command with a pilot effect. |
| **Reference** | Card text that points at other cards: a name reference (`"Master Gundam" in its card name`) or a trait reference (an ability that needs other cards with a trait). |

## Relations between cards (read from the card text, never from decks)
| Term | Meaning |
|---|---|
| **Combo** | Must be played together: an ability that only works with another card, names another card, or needs a specific pilot. |
| **Synergy** (relation) | Work better together: similar keywords, similar abilities, or abilities that work together. |
| **Functional reprint** (peers) | The tie between two cards that do the same job (see `shared/samejob`): each can stand in for the other, with AP/HP within 1 for Units. Players run some of each. Not substitutes: each keeps its own role. See **Squad**. |
| **Tie** | Any one of the above between two cards. Each tie records its reason (`link_pilot: Mikazuki Augus`). |

## Packages and archetypes
| Term | Meaning |
|---|---|
| **Package** | A group of cards of **one color** that are played together (each implies the other in at least 80% of decks) and are tied by their text. Named pilot + unit (`Mikazuki Barbatos`). |
| **Member** | A card in a package. **Core** members are in at least 90% of the decks that play the package; the rest are **optional**. |
| **Variant** | Which optional members come with a package's core. |
| **Plays a package** (also "runs") | A deck plays a package when it has at least 75% of its members and at least two. |
| **Archetype** | The exact set of packages a deck plays (Mikazuki Barbatos + Char Aznable). |
| **Synergy card** | A card outside every package with a tie to a package, played in that package's decks (any appearance). Its **rate** is the score. |
| **Bridge** | A card outside both of two packages, tied to each, played in at least half of the decks that play both. Reported as a bridge to the partner package. |
| **Package synergy** (synergistic packages) | Two packages that are tied (directly or through a bridge) and played together often enough. |
| **Free floating** | A card good on its own: no tie to any package. It still gets a rate in each package's decks, as information. |
| **Rare** | A card in too few decks (under 6) to classify, unless it has a tie to a package. |
| **Drift** | How a later era's decks change the packages found in an earlier one: new cards, dropped members, emerging packages. |
| **Emerging package** | A package found in the later era that shares fewer than two cards with any existing package. |

## Online decks (example decks)
| Term | Meaning |
|---|---|
| **Example list** | One of the curated deck lists of an online archetype (tournament decks, as EGM deck-builder links). |
| **List share** | The share of an archetype's online decks that match a list; an archetype's shares add up to 1. |
| **Weight** | A list's share of the online field: its archetype's games over all games, times its list share. |
| **Online deck** | One of 10,000 whole stand-in decks: the weighted lists repeated in proportion to their weights (apportioned exactly). One online deck is 0.01% of the field. |
| **Source** | Which decks an analysis used: `tournament` (an era's top-cut events) or `online` (the weighted example lists). Online files end in `_online.json`. |

## Collection and purchasing (`tools/gundam_collection/design.md`)
| Term | Meaning |
|---|---|
| **Critical card** | A card a package or deck does not work without: a package's core members and the bridge cards between packages played together. Never missed. |
| **Flexible card** | A card outside any package that real decks run (synergy and free-floating cards), ranked by deck inclusion. |
| **Alternative** | A same-job card for a required card. It *counts* toward the slot only for an option card (or an optional package member), when it stands in for it, real decks play it at least half as often, and its color is one the deck plays. For core and staple cards it is only a suggestion; the card is still needed. |
| **Candidate** | A card tied to a package that real decks never play: a lower-confidence option worth testing. |
| **Slot** | One place in a package or deck that needs some copies of a card; any alternative can fill it. Completeness is counted in slots. |
| **Copies needed** | The majority copy count: the largest n such that at least half of the decks that play the package run n or more copies. |
| **Layer** | How complete a collection is: 1 critical, 2 flexible, 3 variants and alternatives, 4 candidates. |
| **Home / adjacent / new package** | Home: I own at least half of its layer-1 slots. Adjacent: not home, but shares a slot with a home package. New: neither. Spending goes home, then adjacent, then new. |
| **Buildable** | A package whose layer-1 slots are all filled; a deck whose packages are all buildable and whose bridges are present. |
| **Typical copies** | For a card fewer than half of a deck's lists run: the most common copy count among the lists that run it. |
| **Majority copies** | The most copies of a card that at least half of the decks playing a package run (from the copy histogram). The number of copies to own. |
| **Redundancy (functional reprints)** | Same-job cards are redundant, not substitutes: each keeps its own role and copy need, and owning one never covers another. A reprint stands in only for a card real decks do not play in that role, at a comparable rate. See goal 4 in `tools/gundam_collection/design.md`. |
| **Card view** | One card joined across the layers: facts, latest price, copies owned, packages and associated cards (`gundam_collection card`). |
| **Supported / close deck** | A deck (archetype) is supported when I own every core and staple copy (a working deck); close when I own at least 70% of them. Options are not counted. |
| **Core / staples / options** | A deck's three layers: core (core package members and bridges), staples (cards at least half of its lists run), options (optional members and cards in 25-50% of its lists). |
| **Pick** | One line of the deck report's buy list: how many copies of a card to get for a deck, its price, and why. |
| **Reach** | The share of all decks that run a card or any acceptable alternative: how durable a purchase is. |
| **Unlock** | How much filling a slot enables: the sum, over packages needing it, of the package's played rate divided by its remaining missing slots. |
| **Price tier** | Market-price band: bulk up to $0.50, cheap up to $2.00, mid up to $10.00, premium above. |
| **Collection file** | `shared/data/gundam_collection/my_tcg_collection`: my hand-typed list of `CARD QUANTITY` lines, the source of truth; `collection.json` is derived from it. Validated by `gundam_collection check`. |

## Appearance rates (the math: `tools/gundam_packages/appearance-rates.md`)
Perspective package **X** is the package being looked at; **W** is another package played with it.

| Symbol | Name | Meaning | Code |
|---|---|---|---|
| **Z** | **total decks** | All counted decks in the window. | `RatesFile.total_decks` |
| **Y** (also written ZZ) | **package decks** | Decks that play X. | `PackageRates.package_decks` |
| **Y / Z** | **played rate** (package rate) | How often X is played. | `PackageRates.rate` |
| **YY** | **pair decks** | Decks that play both X and W. | `PartnerRates.pair_decks` |
| **YY / Y** | **combined rate** | How often X's decks also play W. | `PartnerRates.combined_rate` |
| **YY / Z** | **joint rate** | How often the pair appears in the whole window. | `PartnerRates.joint_rate` |
| **B** | **copies** | Total copies of a card across a set of decks. | `copies` |
| **C** | **possible copies** | 4 x the decks in that set. | `possible` |
| **B / C** | **card rate** | A card's appearance rate. | `rate` |
| | **rate in combo** | A card's card rate inside the pair decks. | `ComboCard.rate_in_combo` |
| | **rate from X** | Rate in combo x combined rate = copies / (4 x package decks): the card's rate from X's perspective. | `ComboCard.rate_from_x` |
| | **alone decks / rate** | Decks that play X and no other package, and that over package decks. | `alone_decks`, `alone_rate` |
| | **perspective** | Looking at one package: every rate is measured inside that package's decks. | |

Pair rates from one perspective overlap (a deck can play three packages) and add up to 100% only if every deck plays exactly two packages. Archetype rates are exclusive and always add up to 1.
| **Squad** | A set of cards in which every pair are peers (each can stand in for the other, with AP/HP within 1 for Units). A card may be in several squads. Replaces "reprint group". |
| **Pairing** | The Link relation between a pilot (a Pilot card or a Command with a Pilot effect) and the Units it Links. Not the same as "same job": pilots do not replace Units. |
| **Band** | How much of a package or deck I own, by share of critical copies (decks: core + staples): **Perfect** 100%, **Complete** 90%+, **Playable** 75%+ (I would sleeve it), **Reachable** 50%+ (could get there), **Long shot** 25%+, **Not happening** below. Playable or better also needs the key-card guard. Replaces supported / close / far. |
| **Key-card guard** | A core card must be owned at least half its needed copies (2 of 4) for the band to reach Playable or better; otherwise it is capped at Reachable. |
| **Cost to next band** | The cheapest missing copies that reach the next band's threshold (the guard's copies first, then the cheapest): what to spend to move up one band. Shown beside every band. |
| **Rating** | A score for one thing a deck does (shown out of 10, like 4.2): **curve** (lots of small Units), **pressure** (Units with AP over HP or Breach / Suppression / High-Maneuver, minus Units with AP under HP), **interaction** (Commands, Blockers and board-hitting Unit abilities), **advantage** (cards that put a new card in my hand; a condition halves it), plus **finisher** and **resilience**. |
| **Plan** | Aggro, midrange or control, from one beatdown-to-control score: the mean of curve, pressure, low interaction and low advantage. 60+ is aggro, 40 or less is control, in between is midrange (it can be the beatdown or the control). |
| **Deck id** | The anchor cards of a deck's packages, sorted and joined (`GD02-054+ST11-001`): stable and unique per deck; typed in any case, punctuation or order. |
| **Nickname** | A name you give a deck (`redletta`), kept by deck id in `deck_names.json`; it replaces the generated name. |
| **Archetype** | What a deck is known as: its most-played package plus its plan ("Mikazuki Barbatos aggro"). Every deck is in exactly one; an archetype's share is the sum of its decks' play rates. |
| **Primary package** | The most-played package in a deck (by the raw package rates); it names the deck's archetype. |
| **Skipped premium** | A premium card ($10+) the buy plan considers but does not include without `--include-premium`: it is marked SKIPPED, left out of the totals, and the deck that needs it stays in the plan, flagged as not Playable until you approve it. |
| **Suggestion** | A hypothetical deck from `suggest`: an exact 50 built from a package's core, cards found decks run (same plan, these colors) and cards chosen by plan fit, plus a pool of other options. **Known** cards are in found lists; **novel** cards are in none. |
| **Restricted / banned** | From Bandai's list: a banned card has no copies, a restricted card at most N (Corsica Base: 2), a banned pair cannot share a deck, and the **vanilla group** (a Unit Lv2, cost 1, 2 AP, 2 HP, no effects) allows one such card, up to four copies. Applied to found decks and to `suggest`. |
| **Link pair** | A pilot paired with a Unit whose Link it satisfies: the Unit takes the pilot's AP/HP and can be used the turn it is played. A deck's possible pairs are its pilot copies matched to Linked Unit copies they satisfy (shown by `suggest`). |
| **Partner package** | In `suggest`, another package from the reference decks brought in whole (a pilot and the Units it Links). |
| **Links rating** | Out of 10: how many Link pairs a deck can make (0 to a dozen). Shown with the other ratings; not part of the plan axis. |
