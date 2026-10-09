from __future__ import annotations

import pytest

from shared.basetypes import CardNumber
from tools.gundam_cards.models import CardModel, Color
from tools.gundam_packages.models import PackageId, PackageMember, Role, SynergyEdge, SynergyKind
from tools.gundam_packages.naming import PackageNamer, pilot_unit_name, unit_core
from tools.gundam_packages.tests.helpers import catalog, pilot, unit


@pytest.mark.parametrize(
    ("pilot_name", "units", "expected"),
    [
        ("Mikazuki Augus", ["Gundam Barbatos 1st Form", "Gundam Barbatos Adapt"], "Mikazuki Barbatos"),
        ("Kira Yamato", ["Strike Freedom Gundam"], "Kira Strike Freedom"),
        ("Ple-Twelve", ["Unicorn Gundam"], "Ple-Twelve Unicorn"),  # your example
        ("Suletta Mercury", ["Gundam Calibarn"], "Suletta Calibarn"),  # your example
        ("Master Asia", ["Master Gundam"], "Master Asia"),  # shares a word: never "Master Master"
        ("Char Aznable", ["Char's Zaku Ⅱ", "Zeong"], "Char Aznable"),  # "Char's" counts as "Char"
        ("Amuro Ray", ["Gundam"], "Amuro Ray"),  # nothing left of the unit name once "Gundam" goes
        ("Marida Cruz", ["Kshatriya", "Unicorn Gundam 02 Banshee (Destroy Mode)"], "Marida Kshatriya"),
    ],
)
def test_pilot_and_unit_names(pilot_name: str, units: list[str], expected: str) -> None:
    assert pilot_unit_name(pilot_name, units) == expected


def test_unit_core_keeps_what_every_unit_shares() -> None:
    assert unit_core(["Gundam Barbatos 1st Form", "Gundam Barbatos Adapt"]) == ["Barbatos"]
    assert unit_core(["Nu Gundam"]) == ["Nu"] and unit_core(["Gundam"]) == []


def _members(*numbers: str) -> list[PackageMember]:
    return [PackageMember(card_number=CardNumber(n), role=Role.CORE, decks=10, share=1.0) for n in numbers]


def test_the_namer_uses_the_pilot_unit_pair_from_the_packages_link_ties() -> None:
    cards = catalog(
        unit("GD03-056", "Gundam Barbatos Adapt", link="Mikazuki Augus"),
        unit("GD02-054", "Gundam Barbatos 1st Form", link="Mikazuki Augus"),
        pilot("ST05-010", "Mikazuki Augus"),
    )
    edges = [SynergyEdge(a=CardNumber(u), b=CardNumber("ST05-010"), kind=SynergyKind.LINK_PILOT, detail="Mikazuki Augus") for u in ("GD03-056", "GD02-054")]
    name = PackageNamer(cards)(PackageId("pkg:GD02-054"), _members("GD03-056", "GD02-054", "ST05-010"), edges)
    assert name == "Mikazuki Barbatos"  # what both units share, with the pilot's given name


def test_a_package_without_a_pilot_is_named_after_what_its_ties_share() -> None:
    cards = catalog(unit("ST05-006", "Hyakuren", traits=("Tekkadan",)), unit("ST05-004", "Graze Custom", traits=("Tekkadan",)))
    edge = SynergyEdge(a=CardNumber("ST05-006"), b=CardNumber("ST05-004"), kind=SynergyKind.TRAIT_REFERENCE, detail="Tekkadan")
    assert PackageNamer(cards)(PackageId("pkg:ST05-004"), _members("ST05-006", "ST05-004"), [edge]) == "Tekkadan"


def test_same_job_ties_never_name_a_package() -> None:
    cards = catalog(unit("GD04-024", "Gundam Aerial Rebuild"), unit("GD05-022", "Gundam Schwarzette"))
    edge = SynergyEdge(a=CardNumber("GD04-024"), b=CardNumber("GD05-022"), kind=SynergyKind.FUNCTIONAL_EFFECT, detail="same job")
    assert PackageNamer(cards)(PackageId("pkg:GD04-024"), _members("GD04-024", "GD05-022"), [edge]) == "Gundam Aerial Rebuild"  # the first member, not "same job"


def test_nicknames_override_and_duplicate_names_are_made_unique() -> None:
    blue = unit("GD01-001", "Gundam", link="Amuro Ray", color=Color.BLUE)
    green = unit("GD05-017", "Nu Gundam", link="Amuro Ray", color=Color.GREEN)
    p1, p2 = pilot("ST01-010", "Amuro Ray", color=Color.BLUE), pilot("GD05-085", "Amuro Ray", color=Color.GREEN)
    cards = catalog(blue, green, p1, p2)
    namer = PackageNamer(cards, {PackageId("pkg:GD99-001"): "Barbatos package"})
    e1 = SynergyEdge(a=blue.number, b=p1.number, kind=SynergyKind.LINK_PILOT, detail="Amuro Ray")
    first = namer(PackageId("pkg:GD01-001"), _members("GD01-001", "ST01-010"), [e1])
    # a second package that would get the same name is told apart by its colors
    unit_only = unit("GD01-002", "Gundam", link="Amuro Ray", color=Color.GREEN)
    e2 = SynergyEdge(a=unit_only.number, b=p2.number, kind=SynergyKind.LINK_PILOT, detail="Amuro Ray")
    second = PackageNamer({**cards, unit_only.number: unit_only}, {})  # fresh namer, no collision
    assert first == "Amuro Ray" and second(PackageId("pkg:GD01-002"), _members("GD01-002", "GD05-085"), [e2]) == "Amuro Ray"
    again = namer(PackageId("pkg:GD01-003"), _members("GD01-001", "ST01-010"), [e1])
    assert again == "Amuro Ray (blue)"
    assert namer(PackageId("pkg:GD99-001"), _members("GD01-001", "ST01-010"), [e1]) == "Barbatos package"  # override wins


def test_the_namer_accepts_any_card_model() -> None:
    cards: dict[CardNumber, CardModel] = catalog(unit("GD01-001", "Solo Unit"))
    assert PackageNamer(cards)(PackageId("pkg:GD01-001"), _members("GD01-001", "GD01-001"), []) == "Solo Unit"
