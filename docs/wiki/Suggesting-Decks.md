# Suggesting decks

`suggest` builds a **new** 50-card deck you might not have seen in anyone's list. You give it a package, a plan and colors; it fills the deck from what real decks do and from how well each card fits the plan.

    suggest barbatos aggro PB

The words can come in any order: a package (`barbatos`), a plan (`aggro`, `midrange`, `control`) and two color letters (`PB` for purple/blue; R, B, G, W, P). Leave the colors off and you get one deck per second color.

## How it decides

1. The **core** of the package is locked in.
2. The **shape** (how many Units, pilots, Commands and Bases) comes from found decks with the same plan.
3. Cards are chosen by how often real decks run them and by **plan fit**: cheap hard-hitting Units and Bases for aggro, Blockers and interaction for control.
4. **Links matter.** A pilot adds its stats to a Unit and lets it act the turn it is played, so pilots are valued by the Unit copies they pair with. A Linked Unit without a pilot is a weaker body but is not ruled out. Another package that supplies the pilot comes in **whole** (a partner package).
5. It stays close to known lists (the `--novelty` budget), obeys the banned and restricted list, and ends on exactly 50 cards.

{{run collection suggest barbatos aggro PB --pool 0 --alt-from 99 | lines=30 | width=175}}

## Reading the output

- **rating of this 50**: the same ratings as `styles`, including `links`.
- **you own X of 50 copies; band; cost**: how close you already are and what the rest costs.
- **link pairs**: how many pilot copies can pair with a Linked Unit copy.
- **sections**: the package core, any partner package, known cards (from found lists), and novel cards (in no found list).
- **pilots and who they pair with**, then **other pilots worth a look**: pilots not in the deck, ranked by how well the Units they Link fit the plan, with their stats added.

The same run, further down:

{{run collection suggest barbatos aggro PB --pool 0 --alt-from 99 | skip=30 | lines=18 | header=no | width=175}}

## Options

    suggest suletta control GR --prefer owned --novelty 0.4
    suggest barbatos aggro PB --pool 6       # also list the next best cards by kind
    suggest barbatos aggro --alt-from 99     # no alternatives lines (they are shown for cards of $5 or more)

`--prefer fit|owned|cost` breaks near ties toward the best fit, cards you own, or cheaper cards. `--novelty` (0 to 1) is how many cards outside the found lists it may use.
