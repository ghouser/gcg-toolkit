from __future__ import annotations

from datetime import UTC, date, datetime

from shared.basetypes import CardNumber
from tools.gundam_meta.models import EraId, Tier
from tools.gundam_packages.discover import discover
from tools.gundam_packages.drift import compute_drift, introduced_dates
from tools.gundam_packages.models import DriftFile, PackagesFile, SynergyEdge, SynergyKind, Window
from tools.gundam_packages.synergy import SynergyGraph
from tools.gundam_packages.tests.test_discover import A1, A2, A3, B1, B2, B3, B4, GRAPH, PARAMS, S1, world

N = CardNumber
NEW1, NEW2, NEW3, NEW4 = N("GD07-001"), N("GD07-002"), N("GD07-003"), N("GD07-004")
NOW = datetime(2026, 10, 6, tzinfo=UTC)
BASE_END, NEW_START = date(2026, 9, 25), date(2026, 9, 25)


def window(era: str, decks: int, end: date | None) -> Window:
    return Window(era=EraId(era), start=date(2026, 7, 24), end=end, tiers=(Tier.MAJOR, Tier.LOCAL), events=1, decks=decks, decks_not_counted=0)


def base_file() -> PackagesFile:
    decks = world()
    found = discover(decks, GRAPH, PARAMS, {}, lambda pid, members, edges: str(pid))
    return PackagesFile(generated_at=NOW, window=window("gd05", len(decks), BASE_END), params=PARAMS, packages=found.packages,
                        synergy_cards=found.synergy_cards, free_floating=found.free_floating, archetypes=found.archetypes, squads=found.squads, package_synergies=found.package_synergies, rare_cards=found.rare_cards)  # fmt: skip


def graph() -> SynergyGraph:
    extra = [
        SynergyEdge(a=NEW1, b=A2, kind=SynergyKind.LINK_PILOT, detail="x"),  # a new unit built around A's pilot
        SynergyEdge(a=NEW3, b=NEW4, kind=SynergyKind.LINK_PILOT, detail="y"),  # two new cards tied to each other
    ]
    edges = [e for n in (A1, A2, A3, B1, B2, B3, B4) for e in GRAPH.edges_of(n)]
    return SynergyGraph([*edges, *extra])


INTRODUCED = {**{n: date(2026, 1, 1) for n in (A1, A2, A3, B1, B2, B3, B4, S1)}, **{n: date(2026, 10, 1) for n in (NEW1, NEW2, NEW3, NEW4)}}


def new_decks() -> list[frozenset[CardNumber]]:
    decks = [frozenset({A1, A2, A3, NEW1}) for _ in range(12)]  # A, now with a new card in every deck
    decks += [frozenset({B1, B2, B4}) for _ in range(8)]  # B without B3: 3 of 4 still runs it
    decks += [frozenset({S1, NEW2}) for _ in range(3)]  # a new card with no ties
    decks += [frozenset({S1, NEW3, NEW4}) for _ in range(6)]  # two new, tied cards that always come together
    return decks


def make_drift() -> DriftFile:
    decks = new_decks()
    return compute_drift(base_file(), decks, window("gd05_5", len(decks), None), graph(), INTRODUCED, {}, lambda pid, m, e: f"new:{pid}", NOW)


def test_a_new_card_tied_to_a_package_joins_it() -> None:
    a = next(p for p in make_drift().packages if p.package == "pkg:GD01-001")
    assert [(h.card_number, h.decks, h.share) for h in a.joined] == [(NEW1, 12, 1.0)]
    assert a.share_after == 12 / 29 and a.share_before == 25 / 60


def test_a_core_member_that_stops_appearing_is_dropped() -> None:
    b = next(p for p in make_drift().packages if p.package == "pkg:GD02-001")
    assert b.dropped == (B3,) and b.joined == ()


def test_new_cards_are_listed_with_the_package_they_mainly_go_with() -> None:
    cards = {n.card_number: n for n in make_drift().new_cards}
    assert set(cards) == {NEW1, NEW2, NEW3, NEW4}
    assert cards[NEW1].package == "pkg:GD01-001" and cards[NEW1].decks == 12
    assert cards[NEW2].package is None and cards[NEW2].introduced == date(2026, 10, 1)  # a new free floater so far


def test_a_package_made_of_new_cards_is_reported_as_emerging_and_low_sample() -> None:
    (emerging,) = make_drift().emerging
    assert {m.card_number for m in emerging.package.members} == {NEW3, NEW4} and emerging.new_cards == (NEW3, NEW4)
    assert emerging.low_sample  # 29 decks


def test_introduced_dates_come_from_the_earliest_printing_with_a_known_date() -> None:
    from shared.basetypes import SetCode
    from tools.gundam_packages.tests.helpers import catalog, unit

    card = unit("GD01-001", "X")
    printing = card.printings[0].model_copy(update={"set_code": SetCode("GD01")})
    card = card.model_copy(update={"printings": (printing,)})
    assert introduced_dates(catalog(card), {SetCode("GD01"): date(2025, 7, 25)}) == {card.number: date(2025, 7, 25)}
    assert introduced_dates(catalog(card), {}) == {}  # a card from an undated set has no introduction date


def test_emerging_packages_are_discovered_with_relaxed_thresholds() -> None:
    relaxed = make_drift().params
    assert relaxed.min_decks == 3 and relaxed.mutual_threshold == PARAMS.mutual_threshold  # only the minimum deck count is relaxed
