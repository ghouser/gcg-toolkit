"""Local card search: typed filters over the catalog, no network.

Keyword filters are meant for narrowing: search on a keyword, then read the cards to judge which really have it
(`keywords` includes keywords a card grants or references, by design).
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence

from shared.basetypes import FrozenModel, SetCode, Trait
from tools.gundam_cards.models import (
    CardKind,
    CardModel,
    Color,
    Keyword,
    Rarity,
    color_of,
    cost_of,
    is_pilot,
    level_of,
    traits_of,
)


class SearchQuery(FrozenModel):
    """Every filter that is set must match (AND). Collection filters (`traits`, `keywords`, ...) require all members."""

    name: str | None = None  # case-insensitive substring of the card name
    text: str | None = None  # case-insensitive substring of the current card text
    kinds: frozenset[CardKind] = frozenset()  # any of these kinds
    colors: frozenset[Color] = frozenset()  # any of these colors
    level: int | None = None
    cost: int | None = None
    traits: frozenset[Trait] = frozenset()  # the card itself has all of these traits
    mentions: frozenset[Trait] = frozenset()  # the card's text mentions all of these traits
    keywords: frozenset[Keyword] = frozenset()  # the card's text has all of these keywords
    set_code: SetCode | None = None  # some printing is from this set
    rarity: Rarity | None = None  # some printing has this rarity
    alt_art: bool | None = None  # some printing is (True) / is not (False) an alt art
    pilot: bool | None = None  # True: Pilot cards and Commands with a pilot effect; False: everything else

    def matches(self, card: CardModel) -> bool:
        if self.name is not None and self.name.lower() not in card.name.lower():
            return False
        if self.text is not None and self.text.lower() not in card.text.lower():
            return False
        if self.kinds and card.kind not in self.kinds:
            return False
        if self.colors and color_of(card) not in self.colors:
            return False
        if self.level is not None and level_of(card) != self.level:
            return False
        if self.cost is not None and cost_of(card) != self.cost:
            return False
        if not self.traits <= set(traits_of(card)):
            return False
        if not self.mentions <= card.referenced_traits:
            return False
        if not self.keywords <= card.keywords:
            return False
        if self.set_code is not None and not any(p.set_code == self.set_code for p in card.printings):
            return False
        if self.rarity is not None and not any(p.rarity is self.rarity for p in card.printings):
            return False
        if self.alt_art is not None and not any(p.alt_art is self.alt_art for p in card.printings):
            return False
        return self.pilot is None or is_pilot(card) is self.pilot


def search(cards: Iterable[CardModel], query: SearchQuery) -> list[CardModel]:
    """Matching cards, ordered by card number."""
    return sorted((c for c in cards if query.matches(c)), key=lambda c: c.number)


def format_table(cards: Sequence[CardModel]) -> str:
    """One line per card: number, kind, name, color, level/cost, keywords."""
    lines = []
    for card in cards:
        color = color_of(card)
        level, cost = level_of(card), cost_of(card)
        stats = f"Lv{level} C{cost}" if level is not None else ""
        keywords = ",".join(sorted(k.value for k in card.keywords))
        lines.append(f"{card.number:9} {card.kind.value:11} {card.name[:34]:34} {color.value if color else '-':7} {stats:9} {keywords}")
    return "\n".join(lines)
