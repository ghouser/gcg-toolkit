"""Pairing: which pilots go with a Unit, and which Units go with a pilot. A different association from "same job" (replacement).

Pilots work *with* Units, they do not replace them: a Linked Unit is stronger than a plain one, so an unpaired Link Unit is a gap in a
deck. A pilot is a Pilot card or a Command with a Pilot effect; it satisfies a Link by name (an alias counts: Ple-Twelve is also Marida Cruz)
or by trait. Pure functions over the card catalog; ranking by how often decks run the pair is done by the caller from the rates.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping

from shared.basetypes import CardNumber
from shared.samejob.pilots import identity, is_pilot
from tools.gundam_cards.models import CardModel, UnitCard
from tools.gundam_packages.models import PackageRates, RatesFile


def pilots_for(unit: UnitCard, cards: Iterable[CardModel]) -> list[CardModel]:
    """Every pilot (Pilot card or Command with a Pilot effect) that satisfies the Unit's Link; empty for a Unit with no Link."""
    link = unit.link
    if link is None:
        return []
    return [c for c in cards if is_pilot(c) and link.satisfied_by_any(*identity(c))]


def units_for(pilot: CardModel, cards: Iterable[CardModel]) -> list[UnitCard]:
    """Every Linked Unit the pilot satisfies."""
    names, traits = identity(pilot)
    return [c for c in cards if isinstance(c, UnitCard) and c.link is not None and c.link.satisfied_by_any(names, traits)]


def rates_with(rates: RatesFile, number: CardNumber) -> Mapping[CardNumber, float]:
    """How often each card is played in the decks of the package that plays `number` most (its own cards, then everything else in them)."""
    homes: list[tuple[float, PackageRates]] = []
    for package in rates.packages:
        mine = [m.rate for m in package.members if m.card_number == number] + [o.rate for o in package.others if o.card_number == number]
        if mine:
            homes.append((max(mine), package))
    if not homes:
        return {}
    package = max(homes, key=lambda h: (h[0], h[1].package))[1]
    out: dict[CardNumber, float] = {m.card_number: m.rate for m in package.members}
    out.update({o.card_number: o.rate for o in package.others})
    return out
