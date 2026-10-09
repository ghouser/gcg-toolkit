# Ratings and archetypes

## What a deck does: styles

`styles` rates every deck out of 10 on four things and then reads the plan off them:

| Rating | High means |
|---|---|
| **curve** | lots of cheap (Lv 3 or lower) Units and Bases |
| **pressure** | Units and Bases that hit harder than they take, or have Breach, Suppression or High-Maneuver |
| **interaction** | Commands, Blockers and abilities that hit the board |
| **advantage** | cards that put a card in your hand (conditional ones count half; Burst effects count) |

The **plan** comes from one number, `beatdown`, the mean of curve, pressure, *low* interaction and *low* advantage: **aggro** at 6.0 or more, **control** at 4.0 or less, **midrange** in between. `links` (also out of 10) counts the Link pairs a deck can make; it is shown but is not part of the plan, since every plan wants Link pairs.

{{run collection styles | lines=14 | width=185}}

Add `--explain` to see the measured numbers behind each rating.

## Archetypes: decks grouped by their main package

Many lists are the same deck with a few cards changed. `archetypes` groups every deck under its **most-played package** and its **plan**, so Suletta Aerial played as midrange and as control are different archetypes. Every deck is in exactly one, and the shares add up to the meta.

{{run collection archetypes | lines=22 | width=170}}

"my closest" is your nearest deck in that archetype, and what it costs to move up a band. This is how you answer "I want to play more of the Suletta archetype": [Buying](Buying) takes the same words.
