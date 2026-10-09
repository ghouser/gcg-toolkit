"""Archetypes: decks grouped by what they are known as, so popularity is readable (design.md, "Archetypes").

Nobody names a deck by all its packages: "oh, Barbatos again". An archetype is a deck's **primary package** (the most-played package in it, from the
raw rates; no judgement) plus its **plan** (aggro / midrange / control, from `styles.py`): "Mikazuki Barbatos aggro". Every deck is in exactly one
archetype, so the archetype shares add up to the meta (not more), and one archetype's share is the sum of its decks' play rates in each source.
Pure functions over decks and the card catalog.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from shared.basetypes import CardNumber
from tools.gundam_cards.models import CardModel, color_of
from tools.gundam_collection.decks import _LETTER, Deck
from tools.gundam_collection.styles import style_of
from tools.gundam_packages.models import DataSource


@dataclass(frozen=True)
class Archetype:
    name: str
    rates: Mapping[DataSource, float]  # the share of the meta, per source
    decks: tuple[Deck, ...]  # most played first

    @property
    def top_rate(self) -> float:
        return max(self.rates.values(), default=0.0)


def assign_archetypes(decks: Sequence[Deck], catalog: Mapping[CardNumber, CardModel]) -> tuple[Deck, ...]:
    """Each deck with its archetype name and the archetype's share of every source. Give all the decks (before any play-rate floor)."""
    keyed: list[tuple[str, str, str]] = []  # per deck: primary anchor, primary package name, plan
    for deck in decks:
        i = deck.primary
        anchor = deck.anchors[i] if i < len(deck.anchors) else ""
        name = deck.package_refs[i][0] if deck.package_refs else deck.name
        keyed.append((anchor, name, style_of(deck.requirements, catalog).plan.value))
    anchors_by_name: dict[str, set[str]] = defaultdict(set)
    for anchor, name, _ in keyed:
        anchors_by_name[name].add(anchor)

    def label(anchor: str, name: str, plan: str) -> str:
        if len(anchors_by_name[name]) > 1:  # two different packages share this name: a color letter tells them apart when it can
            card = catalog.get(CardNumber(anchor))
            color = color_of(card) if card is not None else None
            if color is not None:
                name = f"{name} ({_LETTER[color.value]})"
        return f"{name} {plan}"

    labels = [label(*k) for k in keyed]
    totals: dict[str, dict[DataSource, float]] = defaultdict(lambda: defaultdict(float))
    for deck, lab in zip(decks, labels, strict=True):
        for source, rate in deck.rates.items():
            totals[lab][source] += rate
    return tuple(replace(deck, archetype=lab, archetype_rates=dict(totals[lab])) for deck, lab in zip(decks, labels, strict=True))


def group_archetypes(decks: Sequence[Deck]) -> list[Archetype]:
    """The archetypes of already-assigned decks, the biggest first."""
    members: dict[str, list[Deck]] = defaultdict(list)
    for deck in decks:
        members[deck.archetype].append(deck)
    found = [Archetype(name, group[0].archetype_rates, tuple(sorted(group, key=lambda d: (-d.top_rate, d.name)))) for name, group in members.items()]
    return sorted(found, key=lambda a: (-a.top_rate, a.name))
