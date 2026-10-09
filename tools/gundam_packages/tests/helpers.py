"""Small valid cards for tests (the real catalog is used in test_corpus.py)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from shared.basetypes import CardNumber, PilotName, PrintingId, Trait
from tools.gundam_cards.models import (
    BaseCard,
    Block,
    CardModel,
    CommandCard,
    Color,
    LinkCondition,
    LinkRequirement,
    PilotCard,
    PilotNameLink,
    PilotProfile,
    Printing,
    Rarity,
    TextVersion,
    TraitLink,
    UnitCard,
    Zone,
)


def _common(number: str, name: str, text: str, traits_mentioned: tuple[str, ...] = ()) -> dict[str, Any]:
    return dict(
        number=CardNumber(number),
        name=name,
        text_versions=(TextVersion(text=text, printing_ids=(PrintingId(number),), block=Block.ONE, as_of=None, substantive=False),),
        keywords=frozenset(),
        referenced_traits=frozenset(Trait(t) for t in traits_mentioned),
        printings=(
            Printing(id=PrintingId(number), variant=None, rarity=Rarity.C, alt_art_level=0, link_art=False, block=Block.ONE,
                     source_title=None, where_to_get="x", set_code=None, package_ids=(), image_url=None),
        ),
        faq=(),
        unknown_tags=(),
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
    )  # fmt: skip


def unit(number: str, name: str, *, link: str | None = None, link_trait: str | None = None, traits: tuple[str, ...] = (),
         text: str = "", mentions: tuple[str, ...] = (), color: Color = Color.BLUE, level: int = 3, cost: int = 2, ap: int = 3,
         hp: int = 3) -> UnitCard:  # fmt: skip
    requirement: list[LinkRequirement] = []
    if link:
        requirement.append(PilotNameLink(fragment=PilotName(link)))
    if link_trait:
        requirement.append(TraitLink(trait=Trait(link_trait)))
    return UnitCard(
        **_common(number, name, text, mentions), color=color, level=level, cost=cost, ap=ap, hp=hp, zones=frozenset({Zone.EARTH}),
        traits=tuple(Trait(t) for t in traits), link=LinkCondition(any_of=tuple(requirement)) if requirement else None,
    )  # fmt: skip


def pilot(number: str, name: str, *, traits: tuple[str, ...] = (), color: Color = Color.BLUE, text: str = "") -> PilotCard:
    return PilotCard(**_common(number, name, text), color=color, level=3, cost=1, ap_bonus=1, hp_bonus=1, traits=tuple(Trait(t) for t in traits))


def command(number: str, name: str, *, text: str = "", pilot_name: str | None = None, traits: tuple[str, ...] = (),
            mentions: tuple[str, ...] = (), color: Color = Color.BLUE, level: int = 1, cost: int = 1) -> CommandCard:  # fmt: skip
    return CommandCard(
        **_common(number, name, text, mentions), color=color, level=level, cost=cost, traits=tuple(Trait(t) for t in traits),
        pilot=PilotProfile(name=PilotName(pilot_name), ap_bonus=1, hp_bonus=1) if pilot_name else None,
    )  # fmt: skip


def catalog(*cards: CardModel) -> dict[CardNumber, CardModel]:
    return {c.number: c for c in cards}


def base(number: str, name: str, *, text: str = "", color: Color = Color.BLUE, level: int = 3, cost: int = 1, hp: int = 5) -> BaseCard:
    return BaseCard(**_common(number, name, text), color=color, level=level, cost=cost, hp=hp, zones=frozenset({Zone.EARTH}), traits=())
