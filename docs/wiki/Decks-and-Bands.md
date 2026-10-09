# Decks and bands

The tools find the decks players actually run (from tournaments and the online meta), then score each one by **how much of it you own**.

## The bands

A deck needs its **core** (the package cards and the bridges between packages) and its **staples** (cards at least half of its lists run). Optional cards are not counted. The share of those copies you own gives the band:

| Band | You own | Meaning |
|---|---|---|
| Perfect | 100% | everything |
| Complete | 90% or more | all but a couple of cards |
| Playable | 75% or more | you can sit down and play it |
| Reachable | 50% or more | a few purchases away |
| Long shot | 25% or more | |
| Not happening | under 25% | |

A percentage alone can hide a missing key card, so the top three bands also need **every core card at half its copies** (2 of 4). That is why a deck at 90% can still be only Playable.

## decks: the whole meta by band

{{run collection decks | skip=7 | lines=14 | width=178}}

Each row shows the deck's id, how often it is played (`T` tournament, `O` online), its archetype's share, colors, plan, the ratings (see [Ratings and archetypes](Ratings-and-Archetypes)), how many core and total copies you own, and **what it costs to reach the next band**. `*` marks decks with few results (copy counts are uncertain) and `!` marks a deck that breaks the banned or restricted list as found.

Useful options:

    decks --all                  # include the lower bands
    decks --sort played          # by meta coverage instead of cheapest first
    decks --min-rate 0.10        # leave out decks played in under 10% of decks
    decks --ids                  # show each deck's id

## deck: one deck in detail

Pick a deck by its id (`GD05-033+GD05-066`, in any order or case), a nickname you gave it, or words from its name. If several decks match the words, `deck` lists them with their ids so you can pick one:

{{run collection deck GD05-033+GD05-066 | lines=34 | width=170}}

`--cards` lists every card with need, owned, short and price; `--options` includes the optional layer; `--alternatives` shows same-job cards for what you are missing (they are never counted toward the band, because decks run reprints alongside each other, not instead of each other).

## Nicknames

Deck ids are exact but long. Give a deck a name you will remember:

    nickname "Suletta Aerial + Academy" redletta
    deck redletta
    nickname --list

## coverage: package by package

`coverage` does the same for single packages rather than whole decks, and says whether each one is a **home** package (you already own at least half), **adjacent** (shares a bridge with one) or **new**:

{{run collection coverage --source online --limit 4 | lines=18 | width=170}}
