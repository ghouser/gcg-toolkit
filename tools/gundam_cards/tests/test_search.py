"""Local search over typed cards."""
from __future__ import annotations

from collections.abc import Callable

import pytest

from shared.basetypes import SetCode, Trait
from tools.gundam_cards.build import SourcePage, build_card
from tools.gundam_cards.models import CardKind, CardModel, Color, Keyword, Rarity
from tools.gundam_cards.search import SearchQuery, format_table, search

TRAITS = frozenset(Trait(t) for t in ("Earth Federation", "White Base Team", "G Generation", "Newtype", "Cyber-Newtype", "Teiwaz", "Tekkadan"))
IDS = ["ST01-001", "ST01-010", "ST01-015", "GD05-111", "EB01-076", "GD01-047", "T-001", "R-002", "EXB-002", "EB01-008", "GD01-046"]


@pytest.fixture
def cards(page: Callable[[str], SourcePage]) -> list[CardModel]:
    return [build_card([page(i)], TRAITS, {}).card for i in IDS]


def numbers(cards: list[CardModel], **criteria: object) -> list[str]:
    typed = {k: frozenset(v) if isinstance(v, set) else v for k, v in criteria.items()}  # strict models want frozensets
    return [str(c.number) for c in search(cards, SearchQuery.model_validate(typed))]


def test_no_filters_returns_everything_in_card_number_order(cards: list[CardModel]) -> None:
    found = numbers(cards)
    assert found == sorted(IDS) and len(found) == len(IDS)


def test_name_and_text_are_case_insensitive_substrings(cards: list[CardModel]) -> None:
    assert numbers(cards, name="white base") == ["ST01-015"]
    assert numbers(cards, text="DRAW 2") == ["GD05-111"]


def test_kind_and_color(cards: list[CardModel]) -> None:
    assert numbers(cards, kinds={CardKind.PILOT}) == ["ST01-010"]
    assert numbers(cards, kinds={CardKind.UNIT, CardKind.BASE}, colors={Color.BLUE}) == ["EB01-008", "ST01-001", "ST01-015"]
    assert numbers(cards, kinds={CardKind.RESOURCE}, colors={Color.BLUE}) == []  # resources have no color


def test_level_and_cost(cards: list[CardModel]) -> None:
    assert numbers(cards, level=4, cost=3) == ["ST01-001"]
    assert numbers(cards, cost=1, kinds={CardKind.COMMAND}) == ["EB01-076", "GD05-111"]


def test_keyword_filters_require_all(cards: list[CardModel]) -> None:
    assert numbers(cards, keywords={Keyword.REPAIR, Keyword.DURING_PAIR}) == ["ST01-001"]
    assert "GD05-111" in numbers(cards, keywords={Keyword.MAIN})
    assert numbers(cards, keywords={Keyword.MAIN, Keyword.REPAIR}) == []


def test_trait_filters(cards: list[CardModel]) -> None:
    assert numbers(cards, traits={Trait("White Base Team")}) == ["ST01-001", "ST01-010", "ST01-015", "T-001"]  # T-001: the token
    assert numbers(cards, traits={Trait("White Base Team"), Trait("Warship")}) == ["ST01-015"]
    assert numbers(cards, mentions={Trait("G Generation")}) == ["EB01-008", "EB01-076"]
    assert numbers(cards, mentions={Trait("White Base Team")}) == ["ST01-015"]  # the base's tokens name that trait


def test_pilot_filter_includes_command_pilots(cards: list[CardModel]) -> None:
    assert numbers(cards, pilot=True) == ["EB01-076", "ST01-010"]
    assert "GD05-111" in numbers(cards, pilot=False) and "EB01-076" not in numbers(cards, pilot=False)
    assert numbers(cards, pilot=True, kinds={CardKind.COMMAND}) == ["EB01-076"]


def test_printing_filters(cards: list[CardModel]) -> None:
    assert numbers(cards, set_code=SetCode("EB01"), kinds={CardKind.COMMAND}) == ["EB01-076"]
    assert numbers(cards, rarity=Rarity.LR) == ["GD01-046", "ST01-001"]
    assert numbers(cards, alt_art=True) == []  # only base printings are loaded here
    assert len(numbers(cards, alt_art=False)) == len(IDS)


def test_filters_combine_with_and(cards: list[CardModel]) -> None:
    assert numbers(cards, kinds={CardKind.UNIT}, keywords={Keyword.REPAIR}, name="gundam") == ["ST01-001"]
    assert numbers(cards, name="gundam", cost=99) == []


def test_unknown_criteria_are_rejected() -> None:
    with pytest.raises(ValueError):
        SearchQuery.model_validate({"nmae": "typo"})


def test_table_formatting(cards: list[CardModel]) -> None:
    table = format_table(search(cards, SearchQuery(name="gundam", kinds=frozenset({CardKind.UNIT}))))
    line = next(l for l in table.splitlines() if l.startswith("ST01-001"))
    assert "Gundam" in line and "repair" in line and "during_pair" in line and "Lv4 C3" in line and "blue" in line
