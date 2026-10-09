"""The import and the links between my collection, prices and associations, on the synthetic worlds."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from shared.basetypes import CardNumber
from tools.gundam_cards.models import CardKind
from tools.gundam_collection.check import build_collection, check_lines
from tools.gundam_collection.link import associated_cards, classify, critical_cards, package_coverage
from tools.gundam_collection.models import Art, CardInfo, Stage
from tools.gundam_collection.store import load_collection, owned_copies, write_collection
from tools.gundam_packages.models import PackageId, PackagesFile, RatesFile, SquadCard, Squad, SynergyKind
from tools.gundam_packages.rates import compute_rates
from tools.gundam_packages.tests import test_package_synergy as ps
from tools.gundam_packages.tests.test_discover import A1, A2, A3, B1, PARAMS, world
from tools.gundam_packages.tests.helpers import catalog, pilot, unit
from tools.gundam_packages.tests.test_drift import base_file, window
from tools.gundam_packages.tests.test_rates import rates

N = CardNumber
NOW = datetime(2026, 10, 8, tzinfo=UTC)
PKG_A, PKG_B = PackageId("pkg:GD01-001"), PackageId("pkg:GD02-001")


def names(**overrides: str) -> dict[CardNumber, str]:
    out = {n: f"Card {n}" for d in world() for n in d}
    out.update({N(k): v for k, v in overrides.items()})
    return out


def package_a() -> tuple[RatesFile, PackagesFile]:
    return rates(), base_file()


def test_the_collection_is_summed_per_card_with_its_arts_and_round_trips(tmp_path: Path) -> None:
    catalog = {N("GD02-041"): CardInfo(name="Gundam Aerial", kind=CardKind.UNIT, arts=frozenset({Art.BASE, Art.ALT})),
               N("GD05-002"): CardInfo(name="Strike Freedom Gundam", kind=CardKind.UNIT, arts=frozenset({Art.BASE}))}  # fmt: skip
    report = check_lines(["GD05-002 3", "GD02-041 1", "GD02-041+ 2", "GD02-041 1"], catalog, file="mine")
    collection = build_collection(report, NOW)
    assert [(c.card_number, c.copies) for c in collection.data] == [("GD02-041", 4), ("GD05-002", 3)]  # sorted, duplicates summed
    assert [(p.art, p.copies) for p in collection.data[0].printings] == [(Art.BASE, 2), (Art.ALT, 2)]
    write_collection(collection, tmp_path)
    assert load_collection(tmp_path) == collection and owned_copies(collection) == {N("GD02-041"): 4, N("GD05-002"): 3}
    assert load_collection(tmp_path / "nothing") is None and owned_copies(None) == {}


def test_coverage_counts_critical_copies_against_the_majority_copy_count_and_prices_the_gap() -> None:
    rates_file, packages = package_a()
    a = next(p for p in rates_file.packages if p.package == PKG_A)
    owned = {A1: 4, A2: 1}  # A1 is a 4-of, A2 and A3 are 2-ofs in these decks
    coverage = package_coverage(a, packages.squads, owned, {A1: 500, A2: 100, A3: 50}, {})
    assert (coverage.critical_need, coverage.critical_have) == (8, 5) and round(coverage.share, 3) == 0.625
    assert coverage.cost_cents == 1 * 100 + 2 * 50  # one A2 and two A3 are missing
    assert coverage.unpriced_missing == 0
    unpriced = package_coverage(a, packages.squads, owned, {A1: 500}, {})
    assert unpriced.cost_cents == 0 and unpriced.unpriced_missing == 3  # no price: the cost is a minimum and says so


def test_a_peer_never_covers_a_core_member_it_is_only_a_suggestion() -> None:
    rates_file, packages = package_a()
    a = next(p for p in rates_file.packages if p.package == PKG_A)
    twin, wrong = N("GD09-001"), N("GD09-002")
    cards = catalog(unit(str(A1), "One", link="Pilot Q"), unit(str(A2), "Two", link="Pilot Q"), pilot(str(A3), "Pilot Q"),
                    unit(str(twin), "Twin", link="Pilot Q"), unit(str(wrong), "Wrong", link="Someone Else"))  # fmt: skip
    group = Squad(cards=(SquadCard(card_number=A2, decks=10), SquadCard(card_number=twin, decks=9), SquadCard(card_number=wrong, decks=9)),
                         decks_with_any=10, share_with_any=0.1, kinds=(SynergyKind.FUNCTIONAL_EFFECT,))  # fmt: skip
    packages = packages.model_copy(update={"squads": (group,)})
    owned = {A1: 4, A2: 1, twin: 4, wrong: 9, A3: 2}
    coverage = package_coverage(a, packages.squads, owned, {A2: 100, twin: 40, wrong: 5}, cards)
    slot = next(s for s in coverage.slots if A2 in s.members)
    assert slot.members == (A2,) and slot.alternates == () and set(slot.similar) == {twin, wrong}  # peers are redundant, not substitutes
    assert slot.owned == 1 and slot.critical_need == 2 and slot.critical_missing == 1  # I still need the second A2
    assert (slot.option, slot.unit_cents) == (A2, 100)


def test_packages_are_home_adjacent_or_new_from_what_i_own() -> None:
    found = ps.run(ps.BRIDGED)
    decks = ps.decks()
    base = PackagesFile(generated_at=NOW, window=window("gd05", len(decks), None), params=PARAMS, packages=found.packages, synergy_cards=found.synergy_cards,
                        free_floating=found.free_floating, archetypes=found.archetypes, squads=found.squads, package_synergies=found.package_synergies,
                        rare_cards=found.rare_cards)  # fmt: skip
    rates_file = compute_rates(base, [{c: 2 for c in d} for d in decks], NOW)
    x, y = PackageId("pkg:GD01-001"), PackageId("pkg:GD02-001")
    by_id = {p.package: p for p in rates_file.packages}
    assert ps.R in critical_cards(by_id[x]) and ps.R in critical_cards(by_id[y])  # the bridge is critical to both
    owned = {ps.Y1: 2, ps.Y2: 2}  # all of Y's critical copies, none of X's
    coverage = {pid: package_coverage(p, base.squads, owned, {}, {}) for pid, p in by_id.items()}
    stages = classify(coverage, rates_file)
    assert stages[y] is Stage.HOME and stages[x] is Stage.ADJACENT  # X shares the bridge with the home package
    assert classify({pid: package_coverage(p, base.squads, {}, {}, {}) for pid, p in by_id.items()}, rates_file) == {x: Stage.NEW, y: Stage.NEW}


def test_associated_cards_come_with_need_owned_and_price_and_skip_the_card_asked_about() -> None:
    rates_file, _ = package_a()
    a = next(p for p in rates_file.packages if p.package == PKG_A)
    rows = associated_cards(a, {PKG_A: "A", PKG_B: "B"}, {A1: 3}, {A1: 500, B1: 25}, limit=2, skip=A3)
    by_card = {r.card: r for r in rows}
    assert A3 not in by_card and by_card[A1].why.startswith("its package") and (by_card[A1].needed, by_card[A1].owned, by_card[A1].price_cents) == (4, 3, 500)
    assert by_card[B1].why == "with B" and by_card[B1].needed == 2 and by_card[B1].owned == 0 and by_card[B1].price_cents == 25
    assert any(r.why == "synergy" and r.needed is None for r in rows)
