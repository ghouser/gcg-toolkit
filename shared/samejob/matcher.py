"""The Matcher: same-job checks against one set of pilots (a deck's, a package's, or the whole catalog's), with per-card caching."""
from __future__ import annotations

from collections.abc import Iterable, Sequence

from shared.basetypes import Trait
from shared.samejob import bases, commands, pilots, units
from shared.samejob.result import Match, Pilot, Profile, Verdict
from shared.samejob.vocabulary import (
    CRITICAL_CLASSES,
    GOOD_KEYWORDS,
    base_core_text,
    command_core_text,
    effect_features,
    effects,
    native_keywords,
)
from tools.gundam_cards.models import BaseCard, CardModel, CommandCard, LinkCondition, TraitLink, UnitCard


def pilots_from(cards: Iterable[CardModel]) -> tuple[Pilot, ...]:
    """The pilots among these cards: Pilot cards and Commands with a pilot effect (a card answers to its alias names too)."""
    out: list[Pilot] = []
    for card in cards:
        if pilots.is_pilot(card):
            names, traits = pilots.identity(card)
            out.append(Pilot(names, traits))
    return tuple(out)


def link_traits_of(cards: Iterable[CardModel]) -> frozenset[Trait]:
    """The traits some Unit's Link asks for (the traits that matter when pairing a pilot)."""
    return frozenset(r.trait for c in cards if isinstance(c, UnitCard) and c.link for r in c.link.any_of if isinstance(r, TraitLink))


def profile(card: CardModel) -> Profile:
    if isinstance(card, CommandCard):
        core, sizes = effects(command_core_text(card.text), grants=True)
        extras = {n for n, present in (("burst", "【Burst】" in card.text), ("pilot", card.pilot is not None), ("action", "【Action】" in command_core_text(card.text))) if present}
        return Profile(frozenset(), frozenset(core | extras), frozenset(core), sizes, cost=card.cost)
    if isinstance(card, BaseCard):
        core = effect_features(base_core_text(card.text), grants=True)
        return Profile(frozenset(), core, core)
    keywords = native_keywords(card.text)
    critical = frozenset(CRITICAL_CLASSES[k] for k in keywords if k in CRITICAL_CLASSES)
    good = frozenset(GOOD_KEYWORDS[k] for k in keywords if k in GOOD_KEYWORDS) | effect_features(card.text)
    ap = (card.ap or 0) if isinstance(card, UnitCard) else 0
    hp = card.hp if isinstance(card, UnitCard) else 0
    return Profile(critical, good, ap=ap, hp=hp)


class Matcher:
    """`unit_links` (the Links of the Units in the deck) lets a pilot's identity be judged against what the deck actually Links; without
    it, pilots are compared on names and traits. `link_traits` (see `link_traits_of`) says which traits matter; None means all."""

    def __init__(
        self,
        pilots: Sequence[Pilot] = (),
        unit_links: Sequence[LinkCondition] = (),
        link_traits: frozenset[Trait] | None = None,
    ) -> None:
        self.pilots = tuple(pilots)
        self.unit_links = tuple(unit_links)
        self.link_traits = link_traits
        self._profiles: dict[str, Profile] = {}
        self._served: dict[str, frozenset[int]] = {}

    def profile(self, card: CardModel) -> Profile:
        key = str(card.number)
        if key not in self._profiles:
            self._profiles[key] = profile(card)
        return self._profiles[key]

    def served(self, card: UnitCard) -> frozenset[int]:
        """Indexes of the pilots that satisfy the card's Link."""
        key = str(card.number)
        if key not in self._served:
            link = card.link
            self._served[key] = frozenset(
                i for i, p in enumerate(self.pilots) if link is not None and link.satisfied_by_any(p.names, p.traits)
            )
        return self._served[key]

    def link_gate(self, x: UnitCard, y: UnitCard) -> tuple[bool, str]:
        if (x.link is None) != (y.link is None):
            return False, "Link-ness differs"
        if x.link is None or y.link is None:
            return True, ""
        served = self.served(x)
        if served:
            return (True, "") if served & self.served(y) else (False, "no pilot in the deck satisfies both Links")
        return (True, "") if set(x.link.any_of) & set(y.link.any_of) else (False, "different Link requirements and no pilot to test")

    def stands_in(self, x: CardModel, y: CardModel) -> Match:
        """Can `y` stand in for `x`? (directional)"""
        if x.number == y.number:
            return Match(Verdict.DIFFERENT, ("the same card",))
        both_commands = isinstance(x, CommandCard) and isinstance(y, CommandCard)
        if pilots.is_pilot(x) and pilots.is_pilot(y) and not both_commands:
            return pilots.stands_in(self, x, y)
        if x.kind is not y.kind:
            return Match(Verdict.DIFFERENT, ("different kind",))
        if isinstance(x, UnitCard) and isinstance(y, UnitCard):
            return units.stands_in(self, x, y)
        if isinstance(x, CommandCard) and isinstance(y, CommandCard):
            return commands.stands_in(self, x, y)
        if isinstance(x, BaseCard) and isinstance(y, BaseCard):
            return bases.stands_in(self, x, y)
        return Match(Verdict.DIFFERENT, (f"no same-job rules for {x.kind.value} cards",))


def stands_in(x: CardModel, y: CardModel, pilots: Sequence[Pilot] = ()) -> Match:
    """Convenience: one check against these pilots."""
    return Matcher(pilots).stands_in(x, y)

