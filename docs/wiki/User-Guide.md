# gcg-toolkit user guide

gcg-toolkit helps you play the **Gundam Card Game** with the cards you already own. It answers four questions:

1. **What do the good decks look like?** It reads tournament results and the online meta, and finds the *packages* (cards that are always played together) that make up each deck.
2. **How close am I to each of them?** You list your cards; it scores every deck by how much of it you own, in plain bands from *Perfect* down to *Long shot*.
3. **What should I buy?** It plans the cheapest path to a playable deck and writes a list you paste into TCGPlayer. It never buys or scrapes anything for you.
4. **What could I build?** It suggests a new 50-card deck from a package, a plan (aggro, midrange or control) and your colors, and shows which pilots pair with which Units.

Everything is deterministic and explained: every number on screen can be traced to a rule in the [glossary](https://github.com/ghouser/gcg-toolkit/blob/main/docs/glossary.md) or the [tuning notes](https://github.com/ghouser/gcg-toolkit/blob/main/docs/tuning.md).

## The pages

| Page | Read it to |
|---|---|
| [Getting started](Getting-Started) | install, run a first command, understand how commands are written |
| [Your collection](Your-Collection) | write your card list, check it for mistakes, see what it is worth |
| [Decks and bands](Decks-and-Bands) | see which meta decks you are close to and why |
| [Ratings and archetypes](Ratings-and-Archetypes) | understand aggro / midrange / control and group decks into archetypes |
| [Buying](Buying) | get a cheapest-first shopping list and export it |
| [Suggesting decks](Suggesting-Decks) | build a new deck from a package, a plan and colors |
| [Meta data](Meta-Data) | look at the packages, pairs and squads behind the decks |
| [Keeping data fresh](Keeping-Data-Fresh) | refresh prices, the banned list and the packages |

## A five-minute path

1. Install: `./bootstrap.sh`.
2. Put your cards in `shared/data/gundam_collection/my_tcg_collection` and run `check`.
3. `decks` shows how close you are to each deck.
4. `buy <archetype>` shows what to buy to play it.
5. `suggest <package> <plan> <colors>` builds something new.

All the sample output in this guide is real output from a modest collection (612 different cards, about 1,500 copies) of someone trying to play, not a showcase collection. Long output is cut with a `... (N more lines)` marker.
