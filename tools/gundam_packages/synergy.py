"""Structural ties between cards, read from the card catalog (never from decks).

Three relations (see models.Relation):
- **Combo** (must be played together; it needs a specific card): LINK_PILOT, a Unit's named Link `[Mikazuki Augus]` satisfied by a Pilot
  (a Pilot card, or a Command with a pilot effect); NAME_REFERENCE, card text that names another card (`a Unit with "Master Gundam" in
  its card name`; a fragment matching more than MAX_NAME_MATCHES cards is too generic and ignored).
- **Synergy** (work better together): LINK_TRAIT (a trait Link satisfied by a Pilot with that trait); TRAIT_REFERENCE (an ability that
  needs **other** cards with a trait, see `reference_needs_others`; no limit on how many cards carry the trait); SIMILAR_ABILITY and
  SHARED_KEYWORD (the same effect or native keyword at a different level/cost; see functional.py).
- **Functional reprint** (basically the same thing at a similar level and cost): see functional.py.
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence

from shared.basetypes import CardNumber, PilotName, Trait
from tools.gundam_cards.models import (
    CardModel,
    CommandCard,
    PilotCard,
    PilotNameLink,
    TraitLink,
    UnitCard,
    traits_of,
)
from tools.gundam_packages.functional import functional_edges
from tools.gundam_packages.models import SynergyEdge, SynergyKind

MAX_NAME_MATCHES = 25
_NAME_REFERENCE = re.compile(r'"([^"]+)"\s+in\s+(?:its|their)\s+card name')


def pilot_identity(card: CardModel) -> tuple[PilotName, frozenset[Trait]] | None:
    """The pilot a card can act as (a Pilot card, or a Command with a pilot effect) with its traits."""
    if isinstance(card, PilotCard):
        return PilotName(card.name), frozenset(card.traits)
    if isinstance(card, CommandCard) and card.pilot is not None:
        return card.pilot.name, frozenset(card.traits)
    return None


class SynergyGraph:
    """Undirected structural ties between cards."""

    def __init__(self, edges: Iterable[SynergyEdge]) -> None:
        self._adjacent: dict[CardNumber, list[SynergyEdge]] = defaultdict(list)
        seen: set[tuple[frozenset[CardNumber], SynergyKind, str]] = set()
        for edge in edges:
            key = (frozenset((edge.a, edge.b)), edge.kind, edge.detail)
            if edge.a == edge.b or key in seen:
                continue
            seen.add(key)
            self._adjacent[edge.a].append(edge)
            self._adjacent[edge.b].append(edge)
        self.edge_count = len(seen)

    def edges_of(self, card: CardNumber) -> tuple[SynergyEdge, ...]:
        return tuple(self._adjacent.get(card, ()))

    def neighbors(self, card: CardNumber) -> frozenset[CardNumber]:
        return frozenset(e.b if e.a == card else e.a for e in self.edges_of(card))

    def edges_between(self, a: CardNumber, b: CardNumber) -> tuple[SynergyEdge, ...]:
        return tuple(e for e in self.edges_of(a) if {e.a, e.b} == {a, b})

    def edges_among(self, members: Iterable[CardNumber]) -> tuple[SynergyEdge, ...]:
        """Every tie with both ends in `members`, each once."""
        inside = set(members)
        found: dict[tuple[frozenset[CardNumber], SynergyKind, str], SynergyEdge] = {}
        for card in inside:
            for edge in self.edges_of(card):
                if edge.a in inside and edge.b in inside:
                    found[(frozenset((edge.a, edge.b)), edge.kind, edge.detail)] = edge
        return tuple(sorted(found.values(), key=lambda e: (e.a, e.b, e.kind.value, e.detail)))

    def edges_across(self, left: Iterable[CardNumber], right: Iterable[CardNumber]) -> tuple[SynergyEdge, ...]:
        """Every tie with one end in `left` and the other in `right`, each once."""
        outer = set(right)
        found: dict[tuple[frozenset[CardNumber], SynergyKind, str], SynergyEdge] = {}
        for card in set(left):
            for edge in self.edges_of(card):
                if (edge.b if edge.a == card else edge.a) in outer:
                    found[(frozenset((edge.a, edge.b)), edge.kind, edge.detail)] = edge
        return tuple(sorted(found.values(), key=lambda e: (e.a, e.b, e.kind.value, e.detail)))

    def ties_to(self, card: CardNumber, members: Iterable[CardNumber]) -> tuple[SynergyEdge, ...]:
        """Ties between `card` and any of `members`."""
        wanted = set(members)
        return tuple(e for e in self.edges_of(card) if (e.b if e.a == card else e.a) in wanted)


_NEEDS_OTHERS_CUE = re.compile(r"\b(?:another|other)\b|\b(?:from|in) your (?:trash|hand|deck|shield area)\b", re.I)


def reference_needs_others(card: CardModel, trait: Trait) -> bool:
    """Does this card's ability name `trait` in a way that needs *other* cards?

    A card without the trait always does (it can't count itself). A card with the trait does only when the sentence naming it says
    "another"/"other" or looks in the trash, hand or deck: Barbatos Lupus ("Choose 3 (Tekkadan)/(Teiwaz) Unit cards from your trash")
    needs others, but Kapool ("a friendly (Marine) Unit is in play") is satisfied by Kapool itself, so Marine is not a package.
    """
    if trait not in traits_of(card):
        return True
    marker = f"({trait})"
    sentences = re.split(r"(?<=[.!?])\s+|\n", card.text)
    return any(marker in s and _NEEDS_OTHERS_CUE.search(s) for s in sentences)


def build_graph(cards: Sequence[CardModel]) -> SynergyGraph:
    """All structural ties between the given cards."""
    by_trait: dict[Trait, list[CardNumber]] = defaultdict(list)
    for card in cards:
        for trait in set(traits_of(card)):
            by_trait[trait].append(card.number)
    pilots = [(c.number, ident) for c in cards if (ident := pilot_identity(c)) is not None]

    edges: list[SynergyEdge] = []
    for card in cards:
        if isinstance(card, UnitCard) and card.link is not None:
            for requirement in card.link.any_of:
                if isinstance(requirement, PilotNameLink):
                    for pilot_number, (pilot_name, _) in pilots:
                        if requirement.fragment in pilot_name:
                            edges.append(SynergyEdge(a=card.number, b=pilot_number, kind=SynergyKind.LINK_PILOT, detail=str(requirement.fragment)))
                elif isinstance(requirement, TraitLink):
                    for pilot_number, (_, pilot_traits) in pilots:
                        if requirement.trait in pilot_traits:
                            edges.append(SynergyEdge(a=card.number, b=pilot_number, kind=SynergyKind.LINK_TRAIT, detail=str(requirement.trait)))
        for fragment in dict.fromkeys(_NAME_REFERENCE.findall(card.text)):
            matches = [o.number for o in cards if o.number != card.number and fragment in o.name]
            if 0 < len(matches) <= MAX_NAME_MATCHES:
                edges.extend(SynergyEdge(a=card.number, b=m, kind=SynergyKind.NAME_REFERENCE, detail=fragment) for m in matches)
        for trait in card.referenced_traits:
            if reference_needs_others(card, trait):
                edges.extend(
                    SynergyEdge(a=card.number, b=m, kind=SynergyKind.TRAIT_REFERENCE, detail=str(trait))
                    for m in by_trait[trait]
                    if m != card.number
                )
    edges.extend(functional_edges(cards))
    return SynergyGraph(edges)
