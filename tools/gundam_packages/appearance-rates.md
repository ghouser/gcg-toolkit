# Appearance Rates: how we measure why cards are played

**Status:** Agreed, implemented in `rates.py`; outputs in `shared/data/gundam_packages/rates.json`. Names are defined in `docs/glossary.md`.
**Part of:** `tools/gundam_packages/design.md` (that file defines packages, synergy and bridges; this one defines the math on top of them).

## Goal
Popularity says *that* a card is played. This analysis says **why**: a card is played because it belongs to a package, or because it is linked to a package (or to a combination of packages). Two direct lookups:

1. **Card -> package.** Give a card; get the package it is in, how often that package is played, how often the card is played in it, and every linked package and card with their rates.
2. **Package -> cards.** Give a package; get the appearance rate of every card played with it: its own cards, each partner package's cards, bridge cards, synergy cards, free-floating cards.

The result says how *related* any card is to every other played card, and every number is reproducible from counts.

## Terms
- **Deck**: one counted deck list in the window (from `gundam_meta`'s de-duplicated events, **main deck only**). We have deck data, not match results. **Z** (`total_decks`) is the number of decks in the window. See [the glossary](../../docs/glossary.md) for every name below.
- **Copies**: a deck plays a card 0 to 4 times (the rules cap it at 4; the GD05 data has no deck above 4). Only deck cards count (resources, EX cards and tokens are left out).
- **A deck plays package X** when it has at least 75% of X's members (and at least two). A deck is made of packages played together; a deck that plays X and W is one where X is played **with** W.
- **Perspective package X** ("looking at X"): everything below is measured inside the decks that play X.

## The math
All counts are integers; every rate is one integer divided by another.

### 3.1 Package played rate
`Y` (**package decks**, `package_decks`) = decks that play X. **Played rate = Y / Z** (package decks / total decks).
"Mikazuki Barbatos is played in 54 of 253 decks: 21%."

### 3.2 Card rate inside a package
For a card A in package X, inside the Y decks that play X:
- `B` (**copies**) = total copies of A in those decks.
- `C` (**possible copies**) = copies it could have had = **4 x Y**.
- **Card rate = B / C** (copies / possible copies).
"Gundam Barbatos 1st Form: 214 of 216 possible copies: 99%."

### 3.3 Combined package played rate
Inside X's Y decks, `YY` (**pair decks**, `pair_decks`) = decks that also play W.
- **Combined package played rate = YY / Y** (how often X is played with W).
- **Joint rate = YY / Z** (the pair's weight in the whole window).

"Mika with Tekkadan: 24 of 54 = 44%; joint 24 of 253 = 9.5%."

### 3.4 A partner package's cards, from X's perspective
For a card A in W, inside the YY decks that play both:
- rate in the combo = (copies of A in those decks) / (4 x YY),
- **rate from X's perspective = combined package played rate x rate in the combo** = copies of A in those decks / (4 x Y).

If half of Mika's decks play Char (combined rate 0.5) and Char's Zaku II is at 98% in them, it is 49% from Mika's perspective. The card rate is measured **inside the decks that play both packages**, not across all of W's decks: it is the observed rate next to X, and it can be checked by counting. (W's own rate in all its decks is still reported as the card's rate in its own package.) Only decks that *play* W count as "with W"; a deck with one or two Tekkadan cards that doesn't play the package isn't "with Tekkadan" (Graze Custom is 42.6% of Mika's slots through the Tekkadan package, 48.1% counting every deck).

### 3.5 Bridge cards
A bridge is only played when X and W are played together (it is outside both packages, tied to both, and in at least half of the decks that play both). So: take the card's overall rate inside the YY decks that play both, then multiply by the combined package played rate:

**rate(bridge from X, via W) = combined package played rate x rate in the combo.**

It is reported as a bridge **to W**: "Strike Rouge (Ootori), from Tekkadan's perspective, via Strike Freedom". A card that bridges several pairs is listed once per partner and the rates are never added.

### 3.6 Synergy and free-floating cards
These are not tied to being played with a partner, so they are **not** multiplied. Inside X's Y decks (not the YY): the card was played `B` times out of `C = 4 x Y` possible, so **rate = B / C**. Synergy cards (a tie to X, any appearance) and free-floating cards (no tie; the rate says how often they are played with X, not that they work with it) use the same formula. Every other card seen in X's decks is listed the same way as "other".

### 3.7 Do the rates add up?
If every deck played exactly two packages, X's combined rates with its partners would sum to 100%. Decks that play three or more packages count toward more than one partner, so the sum goes **over** 100% (Mika: Tekkadan 44%, Strike Freedom 37%, Char 37%, ...), and decks that play only X (the "played alone" rate) pull it the other way. Do not add partner rates. The exclusive split is the **archetype** (the exact set of packages a deck plays): its rate is decks / Z and does sum to 100%.

## Worked toy example
Mika is played in Y = 100 decks. Half (YY = 50) also play Char: combined rate 0.5. In those 50 decks Char's Zaku II appears 196 times of 4 x 50 = 200 possible: 98%. From Mika's perspective: 0.5 x 0.98 = **49%** (= 196 / (4 x 100)). A bridge that is in 40 of the 50 decks (4 copies in 30, 2 in 10 = 140 copies) is 140 / 200 = 70% in the combo, so **35%** from Mika's perspective, via Char. A free-floating card played 120 times in Mika's 100 decks is 120 / 400 = 30%.

## Lookups (CLI)
- `card <number>`: the card's package and rates in it; the package's partners with combined rates; for a bridge, synergy or free-floating card, each package it goes with and its rate there; then the top cards from the package's perspective.
- `package <name or id>`: played rate; each member's rate (core/optional); each partner with combined and joint rates, its cards and bridges (from this perspective); then synergy, free-floating and other cards by rate; the "played alone" rate.
- `build` writes `rates.json` alongside `packages.json`, so the two always match.

## Output contract: `shared/data/gundam_packages/rates.json`
Typed models in `models.py`; counts are stored, rates derived and validated against them.
- `window`, `total_decks` (Z), `packages[]`, `archetypes[]` (`packages`, `decks`, `rate`), `card_index` (card -> package id or none, for every deck card seen).
- `packages[]`: `package`, `name`, `package_decks` (Y), `rate`, `alone_decks`, `alone_rate`, `members[]` (`card_number`, `role`, `copies`, `possible`, `rate`), `partners[]`, `others[]`.
- `partners[]`: `package`, `synergistic` (the pair is a package synergy), `pair_decks` (YY), `combined_rate`, `joint_rate`, `cards[]` and `bridges[]` (`card_number`, `copies`, `possible` = 4 x YY, `rate_in_combo`, `rate_from_x`).
- `others[]`: `card_number`, `role` (synergy / free_floating / other), `belongs_to` (a package it is a member of but wasn't played as, if any), `copies`, `possible` = 4 x Y, `rate`.

## Determinism and checks
Same decks and catalog give identical output. Tests (synthetic world with the toy numbers; real GD05): every rate is copies / possible with possible = 4 x decks; `rate_from_x` = copies / (4 x Y) straight from the decks and = combined rate x rate in the combo; archetype rates sum to 1; every deck card is in `card_index`. A rate from fewer than 6 decks is flagged in the CLI (the GD05.5 window of 42 decks is a snapshot).

## Out of scope for now
Putting rates into the meta report; applying the same rates to the GD05.5 window (`rates` is for the base era).
