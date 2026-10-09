"""Packages are one color; packages that work together are reported as package synergy, with bridge cards between them."""
from __future__ import annotations

from shared.basetypes import CardNumber
from tools.gundam_cards.models import Color
from tools.gundam_packages.discover import Discovery, discover
from tools.gundam_packages.models import PackageId, Params, SynergyEdge, SynergyKind
from tools.gundam_packages.synergy import SynergyGraph

N = CardNumber
X1, X2 = N("GD01-001"), N("GD01-002")  # package X (blue)
Y1, Y2 = N("GD02-001"), N("GD02-002")  # package Y (purple)
R = N("GD03-001")  # a blue card tied to both X and Y: carried into Y's decks by X
PARAMS = Params(min_decks=3, mutual_threshold=0.8, run_share=0.75, bridge_share=0.5)
COLORS: dict[CardNumber, Color | None] = {X1: Color.BLUE, X2: Color.BLUE, Y1: Color.PURPLE, Y2: Color.PURPLE, R: Color.BLUE}


def edge(a: CardNumber, b: CardNumber, kind: SynergyKind = SynergyKind.LINK_PILOT, detail: str = "x") -> SynergyEdge:
    return SynergyEdge(a=a, b=b, kind=kind, detail=detail)


def decks() -> list[frozenset[CardNumber]]:
    result = [frozenset({X1, X2, Y1, Y2, R}) for _ in range(20)]  # both packages, with R
    result += [frozenset({X1, X2, R}) if i < 40 else frozenset({X1, X2}) for i in range(60)]  # X alone: R in 2/3 of these
    result += [frozenset({Y1, Y2}) for _ in range(4)]  # Y without X: never R
    return result


def run(graph: SynergyGraph, colors: dict[CardNumber, Color | None] | None = None, world: list[frozenset[CardNumber]] | None = None) -> Discovery:
    return discover(world if world is not None else decks(), graph, PARAMS, COLORS if colors is None else colors, lambda pid, members, edges: str(pid))


BRIDGED = SynergyGraph([edge(X1, X2), edge(Y1, Y2), edge(R, X1, SynergyKind.LINK_TRAIT, "Orb"), edge(R, Y2, SynergyKind.SHARED_KEYWORD, "blocker")])


def test_packages_that_run_together_through_a_bridge_card_are_synergistic() -> None:
    result = run(BRIDGED)
    assert {p.id for p in result.packages} == {PackageId("pkg:GD01-001"), PackageId("pkg:GD02-001")}
    [synergy] = result.package_synergies
    assert synergy.decks_both == 20 and synergy.edges == ()
    assert [(b.card_number, b.decks, b.share) for b in synergy.bridges] == [(R, 20, 1.0)]
    assert synergy.share_of_b > 0.8 > synergy.share_of_a  # nearly all of Y's decks also run X


def test_a_card_carried_in_by_another_package_is_a_bridge_not_synergy_cards_with_it() -> None:
    result = run(BRIDGED)
    assert {(h.card_number, h.package) for h in result.synergy_cards} == {(R, PackageId("pkg:GD01-001"))}  # R stands on its own in X's decks only
    assert R not in {f.card_number for f in result.free_floating}


def test_without_a_tie_or_bridge_running_together_is_not_synergy() -> None:
    assert run(SynergyGraph([edge(X1, X2), edge(Y1, Y2)])).package_synergies == ()


def test_a_package_is_one_color() -> None:
    m1, m2, m3, m4 = N("GD04-001"), N("GD04-002"), N("GD04-003"), N("GD04-004")
    graph = SynergyGraph([edge(m1, m2), edge(m2, m3), edge(m3, m4)])
    world = [frozenset({m1, m2, m3, m4}) for _ in range(10)]
    mixed = run(graph, {}, world)  # no colors known: one package
    assert [{m.card_number for m in p.members} for p in mixed.packages] == [{m1, m2, m3, m4}]
    colors: dict[CardNumber, Color | None] = {m1: Color.RED, m2: Color.RED, m3: Color.WHITE, m4: Color.WHITE}
    split = run(graph, colors, world)
    assert sorted(sorted(m.card_number for m in p.members) for p in split.packages) == [[m1, m2], [m3, m4]]
    assert [p.colors for p in split.packages] and all(len(p.colors) == 1 for p in split.packages)
    [synergy] = split.package_synergies  # the halves still work together, through the tie that crossed colors
    assert [(e.a, e.b) for e in synergy.edges] == [(m2, m3)] and synergy.decks_both == 10
