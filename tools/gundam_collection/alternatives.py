"""Alternatives for a required card: same-job cards that can stand in for it, never as an excuse to skip it.

**Redundancy, not substitution** (design.md, goal 4): every required card is its own slot with its own need. A same-job card does not
cover a core or staple need; it is only a *suggestion*. A stand-in **counts** toward a slot only for a card real decks do not play as a
core or staple (an *option* in a deck, an *optional* member of a package), and only if it stands in for it (the shared same-job match, against
the pilots and Links of the deck), real decks play it at least `ALT_MIN_SHARE` as often, and its color is one the deck plays.
Squads (the packages tool) say which played cards are peers; `candidates` also finds unplayed ones in the whole catalog.
Pure functions over the card catalog and the squads.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from shared.basetypes import CardNumber
from shared.samejob import Matcher, Standing, Verdict, link_traits_of, pilots_from
from tools.gundam_cards.models import CardModel, Color, UnitCard, color_of
from tools.gundam_packages.models import Squad

ALT_MIN_SHARE = 0.5  # a stand-in counts only if real decks play it at least this often compared with the card it stands in for
DECK_COLORS = 2  # a deck plays two colors


@dataclass(frozen=True)
class Alternatives:
    counted: tuple[CardNumber, ...]  # stand-ins that count toward the card's slot (option cards only)
    similar: tuple[CardNumber, ...]  # same-job peers that do not count: suggestions


@dataclass(frozen=True)
class Candidate:
    """A card in the whole catalog that could stand in for a required card, played or not."""

    card: CardNumber
    standing: Standing
    color: Color | None
    in_deck_colors: bool
    owned: int = 0  # copies of it I own (any printing)


def main_colors(numbers: Iterable[CardNumber], catalog: Mapping[CardNumber, CardModel], limit: int = DECK_COLORS) -> frozenset[Color]:
    """The colors a deck plays: the most common colors among its cards."""
    count = Counter(color_of(catalog[n]) for n in numbers if n in catalog)
    count.pop(None, None)
    return frozenset(c for c, _ in count.most_common(limit) if c is not None)


def matcher_for(required: Sequence[CardNumber], catalog: Mapping[CardNumber, CardModel]) -> Matcher:
    """A same-job matcher that knows the pilots and Unit Links of this deck (or package)."""
    cards = [catalog[n] for n in required if n in catalog]
    links = [c.link for c in cards if isinstance(c, UnitCard) and c.link is not None]
    return Matcher(pilots_from(cards), links, link_traits_of(catalog.values()))


def slot_alternatives(
    required: Sequence[CardNumber],
    counting: frozenset[CardNumber],
    squads: Sequence[Squad],
    catalog: Mapping[CardNumber, CardModel],
) -> dict[CardNumber, Alternatives]:
    """For each required card, the stand-ins that count (only for cards in `counting`) and the peers that are suggestions."""
    needed = set(required)
    matcher = matcher_for(required, catalog)
    colors = main_colors(required, catalog)
    decks: dict[CardNumber, int] = {}
    peers: dict[CardNumber, set[CardNumber]] = {n: set() for n in required}
    for squad in squads:
        members = {c.card_number: c.decks for c in squad.cards}
        for n, d in members.items():
            decks[n] = max(decks.get(n, 0), d)
        for n in members.keys() & needed:
            peers[n] |= members.keys() - {n}
    out: dict[CardNumber, Alternatives] = {}
    for n in required:
        counted: list[CardNumber] = []
        similar: list[CardNumber] = []
        for y in sorted(peers[n] - needed):
            ok = (
                n in counting
                and n in catalog
                and y in catalog
                and matcher.stands_in(catalog[n], catalog[y]).verdict is Verdict.SAME_JOB
                and decks.get(y, 0) >= ALT_MIN_SHARE * decks.get(n, 0)
                and (color_of(catalog[y]) in colors or not colors)
            )
            (counted if ok else similar).append(y)
        out[n] = Alternatives(tuple(counted), tuple(similar))
    return out


def _matches(
    card: CardNumber, required: Sequence[CardNumber], catalog: Mapping[CardNumber, CardModel], owned: Mapping[CardNumber, int]
) -> list[Candidate]:
    """Every card in the catalog that can stand in for `card` against this deck's pilots and Links, excluding the cards the deck already runs."""
    if card not in catalog:
        return []
    matcher = matcher_for(required, catalog)
    colors = main_colors(required, catalog)
    needed = set(required)
    found: list[Candidate] = []
    for y, other in catalog.items():
        if y in needed or y == card:
            continue
        result = matcher.stands_in(catalog[card], other)
        if result.verdict is Verdict.SAME_JOB and result.informative and result.standing is not None:
            color = color_of(other)
            found.append(Candidate(y, result.standing, color, color in colors or not colors, owned.get(y, 0)))
    return found


def candidates(
    card: CardNumber,
    required: Sequence[CardNumber],
    catalog: Mapping[CardNumber, CardModel],
    prices: Mapping[CardNumber, int],
    *,
    limit: int = 5,
    owned: Mapping[CardNumber, int] | None = None,
) -> tuple[Candidate, ...]:
    """Cards in the whole catalog (played or not) that can stand in for `card` against this deck's pilots and Links, cheapest first.

    Never counts toward a slot: it is the answer to "what else could I try?" (a $0.16 Besserung for a $44 Kshatriya). A card the deck already
    runs (core, staple or option) is not an alternative: it is another copy of the job, already needed."""
    found = [c for c in _matches(card, required, catalog, owned or {}) if c.card in prices]
    found.sort(key=lambda c: (not c.in_deck_colors, prices[c.card], c.card))
    return tuple(found[:limit])


def owned_alternatives(
    card: CardNumber, required: Sequence[CardNumber], catalog: Mapping[CardNumber, CardModel], owned: Mapping[CardNumber, int]
) -> tuple[Candidate, ...]:
    """The same-job alternatives to `card` that I already own (any price, any color; a color the deck does not play is flagged), most copies first."""
    found = [c for c in _matches(card, required, catalog, owned) if c.owned > 0]
    found.sort(key=lambda c: (not c.in_deck_colors, -c.owned, c.card))
    return tuple(found)
