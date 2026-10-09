"""Pilot rules: a pilot is what makes a Linked Unit Link, so a pilot stands in for another when it serves the same Links.

Text, AP and HP are ignored (decided 2026-10-08). Pilot cards and Commands with a Pilot effect are both pilots. In a deck (the Links of
its Units are known), Y must satisfy every Link X satisfies there. With no deck, X and Y share a name (an alias counts) or a Link-relevant
trait (a trait some Unit's Link asks for; flavor traits such as Support do not count).

This is replacement. *Pairing* (which pilots go with a Unit, which Units with a pilot) is a different association: see design.md.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from shared.basetypes import PilotName, Trait
from shared.samejob.result import Match, Standing, Verdict
from tools.gundam_cards.models import CardModel, PilotCard, names_of, traits_of

if TYPE_CHECKING:
    from shared.samejob.matcher import Matcher


def is_pilot(card: CardModel) -> bool:
    """A Pilot card, or a Command with a Pilot effect."""
    return isinstance(card, PilotCard) or getattr(card, "pilot", None) is not None


def identity(card: CardModel) -> tuple[tuple[PilotName, ...], frozenset[Trait]]:
    return tuple(PilotName(n) for n in names_of(card)), frozenset(traits_of(card))


def stands_in(m: Matcher, x: CardModel, y: CardModel) -> Match:
    names_x, traits_x = identity(x)
    names_y, traits_y = identity(y)
    served = [link for link in m.unit_links if link.satisfied_by_any(names_x, traits_x)]
    if served:
        also = [link for link in served if link.satisfied_by_any(names_y, traits_y)]
        if len(also) < len(served):
            return Match(Verdict.DIFFERENT, ("does not serve every Link the other serves in the deck",), None, True)
        more = sum(1 for link in m.unit_links if link.satisfied_by_any(names_y, traits_y)) > len(served)
        return Match(Verdict.SAME_JOB, (), Standing.BETTER if more else Standing.EQUAL, True)
    shared_name = bool(set(names_x) & set(names_y))
    relevant = traits_x & traits_y if m.link_traits is None else traits_x & traits_y & m.link_traits
    if not shared_name and not relevant:
        return Match(Verdict.DIFFERENT, ("no shared name or Link-relevant trait",))
    standing = Standing.EQUAL if (set(names_x), traits_x) == (set(names_y), traits_y) else Standing.BETTER if set(names_x) <= set(names_y) and traits_x <= traits_y else Standing.TRADE_OFF
    return Match(Verdict.SAME_JOB, (), standing, True)
