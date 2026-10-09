"""Pairing: which pilots go with a Unit and which Units go with a pilot (not the same as same-job replacement)."""
from __future__ import annotations

from collections.abc import Sequence

from tools.gundam_cards.models import CardModel, Color
from tools.gundam_packages.pairing import pilots_for, units_for
from tools.gundam_packages.tests.helpers import command, pilot, unit

MARIDA = pilot("GD01-093", "Marida Cruz", traits=("Neo Zeon", "Cyber-Newtype"), color=Color.RED)
PLE_TWELVE = pilot("ST12-012", "Ple-Twelve", traits=("Earth Federation", "Cyber-Newtype"), color=Color.PURPLE,
                   text="This card's name is also treated as [Marida Cruz].")  # fmt: skip
SOMEONE = pilot("GD01-070", "Someone Else", traits=("Newtype",))
PILOT_COMMAND = command("GD01-112", "Extreme Hatred", pilot_name="Marida Cruz", traits=("Cyber-Newtype",))
BIG = unit("GD01-044", "Kshatriya", link="Marida Cruz")
SMALL = unit("GD01-051", "Kshatriya", link_trait="Cyber-Newtype")
DELTA_PLUS = unit("GD01-006", "Delta Plus", link_trait="Earth Federation")
PLAIN = unit("GD01-031", "Plain")
CARDS: list[CardModel] = [MARIDA, PLE_TWELVE, SOMEONE, PILOT_COMMAND, BIG, SMALL, DELTA_PLUS, PLAIN]


def numbers(cards: Sequence[CardModel]) -> set[str]:
    return {str(c.number) for c in cards}


def test_the_pilots_that_make_a_unit_link_include_aliases_and_pilot_commands() -> None:
    assert numbers(pilots_for(BIG, CARDS)) == {"GD01-093", "ST12-012", "GD01-112"}  # by name, by alias, and a Command with a Pilot effect
    assert numbers(pilots_for(SMALL, CARDS)) == {"GD01-093", "ST12-012", "GD01-112"}  # by trait (Cyber-Newtype)
    assert numbers(pilots_for(DELTA_PLUS, CARDS)) == {"ST12-012"}  # only Ple-Twelve is Earth Federation
    assert pilots_for(PLAIN, CARDS) == []  # no Link, no pilot needed


def test_the_units_a_pilot_links() -> None:
    assert numbers(units_for(PLE_TWELVE, CARDS)) == {"GD01-044", "GD01-051", "GD01-006"}
    assert numbers(units_for(MARIDA, CARDS)) == {"GD01-044", "GD01-051"}
    assert numbers(units_for(SOMEONE, CARDS)) == set()
