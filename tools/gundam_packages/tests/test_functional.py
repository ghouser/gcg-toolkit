"""Graph ties built from the same-job match (functional.py): mutual, informative, Units and Commands only."""
from __future__ import annotations

from tools.gundam_cards.models import CardModel, Color
from tools.gundam_packages.functional import functional_edges
from tools.gundam_packages.models import Relation, SynergyKind
from tools.gundam_packages.tests.helpers import command, pilot, unit

BLOCKER = "<Blocker> (Rest this Unit to change the attack target to it.)"


def ties(cards: list[CardModel]) -> dict[frozenset[str], SynergyKind]:
    return {frozenset({str(e.a), str(e.b)}): e.kind for e in functional_edges(cards)}


def test_units_that_can_stand_in_for_each_other_are_reprints_in_one_color_and_synergy_across_colors() -> None:
    cards: list[CardModel] = [
        unit("GD01-086", "Gundam Lfrith", text=BLOCKER + "\n【Deploy】Deal 1 damage to 1 enemy Unit.", color=Color.WHITE),
        unit("GD02-079", "Rick Dias", text=BLOCKER + "\n【Deploy】Draw 1.", color=Color.WHITE),
        unit("GD01-050", "Blue Blocker", text=BLOCKER + "\n【Deploy】Draw 1.", color=Color.BLUE),
    ]
    found = ties(cards)
    assert found[frozenset({"GD01-086", "GD02-079"})] is SynergyKind.FUNCTIONAL_EFFECT and found[frozenset({"GD01-086", "GD02-079"})].relation is Relation.FUNCTIONAL_REPRINT
    assert found[frozenset({"GD01-050", "GD01-086"})] is SynergyKind.SIMILAR_ABILITY  # another color: a deck may use it, but it is synergy in the graph


def test_a_one_way_stand_in_is_not_a_tie() -> None:
    # The big Kshatriya's 5 AP is out of reach of a 3/4 vanilla body, so only the deck-level check (directional) relates them.
    big = unit("GD01-044", "Kshatriya", link="Marida Cruz", ap=5, hp=4, text="【When Paired】Choose 1 enemy Unit. Deal 1 damage to it.")
    small = unit("GD01-051", "Kshatriya", link_trait="Cyber-Newtype", ap=3, hp=4)
    marida = pilot("GD01-093", "Marida Cruz", traits=("Cyber-Newtype",))
    assert ties([marida, big, small]) == {}


def test_two_plain_linkless_bodies_share_nothing_so_they_are_not_tied() -> None:
    assert ties([unit("GD01-031", "Plain A"), unit("GD01-032", "Plain B")]) == {}


def test_commands_with_the_same_core_effect_are_tied_and_different_effects_are_not() -> None:
    close = command("ST03-013", "Close Combat", text="【Main】/【Action】Choose 1 enemy Unit. Deal 2 damage to it.", color=Color.RED, cost=2)
    aces = command("GD01-111", "Battle of Aces", text="【Burst】Draw 1.\n【Main】/【Action】Choose 1 enemy Unit. Deal 3 damage to it.", color=Color.RED, cost=2)
    airframe = command("GD05-111", "Airframe Seizure", text="【Main】Discard 1. If you do, draw 2.", color=Color.RED, cost=2)
    area = command("GD01-108", "Strategic Arms", text="【Main】Deal 2 damage to all Units with <Blocker>.", color=Color.RED, cost=2)
    found = ties([close, aces, airframe, area])
    assert found[frozenset({"ST03-013", "GD01-111"})] is SynergyKind.FUNCTIONAL_EFFECT
    assert all(not ({"GD05-111", "GD01-108"} & set(k)) for k in found)  # drawing is not damage, and damage to all is not damage to 1


def test_pilots_and_bases_have_no_same_job_rules_yet() -> None:
    assert ties([pilot("GD01-070", "Pilot A"), pilot("GD01-071", "Pilot B")]) == {}
