"""Archetypes: a deck's most-played package plus its plan; shares are sums of play rates and partition the meta."""
from __future__ import annotations

import pytest

from shared.basetypes import CardNumber
from tools.gundam_cards.models import CardModel, Color
from tools.gundam_collection.archetypes import assign_archetypes, group_archetypes
from tools.gundam_collection.decks import Deck, Layer, Requirement, deck_id
from tools.gundam_packages.models import DataSource, PackageId
from tools.gundam_packages.tests.helpers import catalog, command, unit

N = CardNumber
T, O = DataSource.TOURNAMENT, DataSource.ONLINE

CHEAP = unit("GD01-001", "Cheap Breacher", level=2, ap=4, hp=2, text="<Breach 2> (...)", color=Color.RED)
WALL = unit("GD01-011", "Wall", level=6, ap=2, hp=5, text="<Blocker> (Rest this Unit to change the attack target to it.)", color=Color.BLUE)
ANSWER = command("GD01-014", "Answer", text="【Action】Choose 1 enemy Unit. Return it to its owner's hand.", color=Color.BLUE)
CARDS: dict[CardNumber, CardModel] = catalog(
    CHEAP, WALL, ANSWER, unit("GD02-054", "Barbatos", color=Color.PURPLE), unit("ST05-010", "Mikazuki", color=Color.PURPLE), unit("GD05-002", "Strike Freedom", color=Color.BLUE),
    unit("GD01-026", "Char's Zaku II", color=Color.GREEN), unit("ST11-001", "Char's Z'Gok", color=Color.BLUE),
)  # fmt: skip
AGGRO = (Requirement(CHEAP.number, Layer.CORE, 4, 1.0, ()),)
CONTROL = (Requirement(WALL.number, Layer.CORE, 4, 1.0, ()), Requirement(ANSWER.number, Layer.CORE, 4, 1.0, ()))


def deck(packages: list[tuple[str, str, float]], requirements: tuple[Requirement, ...], rates: dict[DataSource, float]) -> Deck:
    """A deck of (package name, anchor card, how often that package is played) with a card table and its own play rates."""
    refs = tuple((n, T, PackageId(f"pkg:{a}")) for n, a, _ in packages)
    anchors = tuple(a for _, a, _ in packages)
    return Deck(name=" + ".join(n for n, _, _ in packages), package_refs=refs, rates=rates, low_sample=False, requirements=requirements, anchors=anchors,
                package_rates=tuple(r for _, _, r in packages), id=deck_id(anchors), plain_name="x")  # fmt: skip


def test_the_primary_package_is_the_most_played_one_and_ties_go_to_the_lower_anchor() -> None:
    d = deck([("Mikazuki", "ST05-010", 0.10), ("Barbatos", "GD02-054", 0.30)], AGGRO, {T: 0.05})
    assert d.primary == 1  # Barbatos is more played
    tie = deck([("Zeta", "ST05-010", 0.2), ("Alpha", "GD02-054", 0.2)], AGGRO, {T: 0.05})
    assert tie.primary == 1  # equal rates: the lower anchor card (GD02-054) wins


def test_decks_with_the_same_primary_package_and_plan_share_an_archetype_and_add_up() -> None:
    a = deck([("Barbatos", "GD02-054", 0.3)], AGGRO, {T: 0.03, O: 0.04})
    b = deck([("Barbatos", "GD02-054", 0.3), ("Mikazuki", "ST05-010", 0.1)], AGGRO, {T: 0.02, O: 0.03})
    c = deck([("Barbatos", "GD02-054", 0.3), ("Strike Freedom", "GD05-002", 0.1)], CONTROL, {T: 0.05})
    named = assign_archetypes([a, b, c], CARDS)
    assert [d.archetype for d in named] == ["Barbatos aggro", "Barbatos aggro", "Barbatos control"]  # the same package splits by plan
    assert dict(named[0].archetype_rates) == {T: 0.05, O: 0.07} and dict(named[2].archetype_rates) == {T: 0.05}  # sums of the decks' rates
    arch = group_archetypes(named)
    assert [(x.name, len(x.decks)) for x in arch] == [("Barbatos aggro", 2), ("Barbatos control", 1)]  # biggest first
    assert sum(x.rates.get(T, 0.0) for x in arch) == pytest.approx(0.10)  # every deck is in exactly one archetype: the shares add up to the decks' total, no double counting


def test_a_deck_with_two_packages_is_named_by_the_more_played_one_only() -> None:
    kira = deck([("Kira Aile Strike", "GD05-002", 0.095), ("Kira Strike Freedom", "ST05-010", 0.105)], CONTROL, {O: 0.05})
    named = assign_archetypes([kira], CARDS)
    assert named[0].archetype == "Kira Strike Freedom control"  # not counted again under Kira Aile Strike


def test_two_different_packages_with_one_name_get_a_color_letter_in_the_archetype_name() -> None:
    green = deck([("Char Aznable", "GD01-026", 0.1)], AGGRO, {T: 0.04})
    blue = deck([("Char Aznable", "ST11-001", 0.1)], AGGRO, {O: 0.02})
    assert [d.archetype for d in assign_archetypes([green, blue], CARDS)] == ["Char Aznable (G) aggro", "Char Aznable (B) aggro"]


def test_a_variant_of_a_played_archetype_is_kept_but_dust_is_not() -> None:
    from tools.gundam_collection.decks import is_played

    big = deck([("Barbatos", "GD02-054", 0.3)], AGGRO, {T: 0.08, O: 0.07})
    variant = deck([("Barbatos", "GD02-054", 0.3), ("Char", "ST05-010", 0.1)], AGGRO, {O: 0.02})  # 2% of its own, in a 15% archetype
    dust = deck([("Barbatos", "GD02-054", 0.3), ("Shinn", "GD05-002", 0.1)], AGGRO, {O: 0.002})
    named = assign_archetypes([big, variant, dust], CARDS)
    assert [is_played(d, 0.05) for d in named] == [True, True, False]  # the floor is 5%: the variant clears a fifth of it (1%), the dust does not
    assert is_played(named[2], 0.0)  # a floor of zero keeps everything
