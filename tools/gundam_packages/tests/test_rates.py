"""Appearance rates on synthetic worlds with known answers (the arithmetic in appearance-rates.md)."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from shared.basetypes import CardNumber
from tools.gundam_packages.discover import Discovery
from tools.gundam_packages.models import ArchetypeRole, OtherRole, PackageId, PackagesFile, RatedCard, RatesFile, majority_copies
from tools.gundam_packages.rates import compute_rates
from tools.gundam_packages.tests import test_package_synergy as ps
from tools.gundam_packages.tests.test_discover import A1, A2, A3, B1, B2, B3, B4, F1, H, O, PARAMS, S1, S2, world
from tools.gundam_packages.tests.test_drift import base_file, window

NOW = datetime(2026, 10, 7, tzinfo=UTC)
PKG_A, PKG_B = PackageId("pkg:GD01-001"), PackageId("pkg:GD02-001")


def copies(deck: frozenset[CardNumber]) -> dict[CardNumber, int]:
    return {c: 4 if c == A1 else 2 for c in deck}  # A1 is a 4-of, everything else a 2-of


def rates() -> RatesFile:
    return compute_rates(base_file(), [copies(d) for d in world()], NOW)


def package(file: RatesFile, pid: PackageId):  # type: ignore[no-untyped-def]
    return next(p for p in file.packages if p.package == pid)


def test_package_rate_and_member_rate_are_decks_over_all_decks_and_copies_over_four_per_deck() -> None:
    a = package(rates(), PKG_A)
    assert (a.package_decks, a.rate) == (25, 25 / 60)
    by_card = {m.card_number: m for m in a.members}
    assert (by_card[A1].copies, by_card[A1].possible, by_card[A1].rate) == (100, 100, 1.0)  # a 4-of in every deck
    assert (by_card[A2].copies, by_card[A2].possible, by_card[A2].rate) == (50, 100, 0.5)  # a 2-of in every deck


def test_a_partner_has_a_combined_rate_and_its_cards_are_multiplied_by_it() -> None:
    a = package(rates(), PKG_A)
    (b,) = a.partners
    assert b.package == PKG_B and b.pair_decks == 5
    assert b.combined_rate == 5 / 25 and b.joint_rate == 5 / 60  # B is played in 5 of A's 25 decks
    card = next(c for c in b.cards if c.card_number == B1)
    assert (card.copies, card.possible, card.rate_in_combo) == (10, 20, 0.5)  # a 2-of in the 5 decks that play both
    assert card.rate_from_x == pytest.approx(0.2 * 0.5) == pytest.approx(10 / (4 * 25))  # combined rate x rate in combo


def test_alone_rate_and_other_cards_are_measured_over_the_perspective_packages_games() -> None:
    a = package(rates(), PKG_A)
    assert a.alone_decks == 20 and a.alone_rate == 20 / 25
    others = {o.card_number: o for o in a.others}
    assert others[H].role is OtherRole.SYNERGY and others[H].copies == 2 * 14 and others[H].possible == 4 * 25  # not multiplied by anything
    assert others[F1].role is OtherRole.FREE_FLOATING and others[F1].copies == 2 * 15  # no tie to A: a rate, not a claim of synergy
    assert others[O].role is OtherRole.FREE_FLOATING and others[O].copies == 2 * 25 and others[O].rate == 0.5
    assert B1 not in others  # B's cards are listed under the partner


def test_archetype_rates_add_up_and_every_card_has_an_index_entry() -> None:
    file = rates()
    assert sum(a.rate for a in file.archetypes) == pytest.approx(1.0) and sum(a.decks for a in file.archetypes) == file.total_decks == 60
    cards = {c for d in world() for c in d}
    assert set(file.card_index) == cards
    assert file.card_index[A1] == PKG_A and file.card_index[B3] == PKG_B and file.card_index[S1] is None
    assert file.card_index[S2] is None


def test_the_file_round_trips_and_rates_that_do_not_match_their_counts_are_rejected() -> None:
    file = rates()
    assert RatesFile.model_validate_json(file.model_dump_json()) == file
    with pytest.raises(ValidationError):
        RatedCard(card_number=B2, copies=5, possible=20, rate=0.3)
    assert {B1, B2, B3, B4} <= {c.card_number for c in package(file, PKG_A).partners[0].cards}


def test_a_bridge_card_is_multiplied_by_the_combined_rate_and_reported_to_its_partner() -> None:
    found: Discovery = ps.run(ps.BRIDGED)
    decks = ps.decks()
    base = PackagesFile(
        generated_at=NOW, window=window("gd05", len(decks), None), params=PARAMS, packages=found.packages, synergy_cards=found.synergy_cards,
        free_floating=found.free_floating, archetypes=found.archetypes, squads=found.squads, package_synergies=found.package_synergies,
        rare_cards=found.rare_cards,
    )  # fmt: skip
    file = compute_rates(base, [{c: 2 for c in d} for d in decks], NOW)
    x, y = PackageId("pkg:GD01-001"), PackageId("pkg:GD02-001")
    partner = package(file, x).partners[0]
    assert partner.package == y and partner.synergistic and partner.pair_decks == 20 and partner.combined_rate == 20 / 80
    (bridge,) = partner.bridges
    assert bridge.card_number == ps.R and bridge.rate_in_combo == 0.5  # 2 copies of 4 possible in every deck that plays both
    assert bridge.rate_from_x == pytest.approx(0.25 * 0.5) == pytest.approx(40 / (4 * 80))
    from_y = package(file, y).partners[0]
    assert from_y.package == x and from_y.combined_rate == 20 / 24 and from_y.bridges[0].rate_from_x == pytest.approx(20 / 24 * 0.5)


def test_the_majority_copy_count_is_the_most_copies_that_half_the_decks_run() -> None:
    assert majority_copies((0, 0, 0, 0, 10)) == 4 and majority_copies((0, 0, 5, 5, 0)) == 3 and majority_copies((0, 0, 4, 6, 0)) == 3
    assert majority_copies((0, 0, 6, 4, 0)) == 2 and majority_copies((0, 10, 0, 0, 0)) == 1 and majority_copies((10, 0, 0, 0, 0)) == 0
    assert majority_copies((4, 0, 0, 0, 6)) == 4  # 6 of 10 decks run four


def test_each_package_member_and_partner_card_has_a_copy_histogram_that_matches_its_copies() -> None:
    a = package(rates(), PKG_A)
    by_card = {m.card_number: m for m in a.members}
    assert by_card[A1].histogram == (0, 0, 0, 0, 25) and by_card[A1].majority_copies == 4  # a 4-of in all 25 decks
    assert by_card[A2].histogram == (0, 0, 25, 0, 0) and by_card[A2].majority_copies == 2  # a 2-of in all 25 decks
    b_card = next(c for c in a.partners[0].cards if c.card_number == B1)
    assert b_card.histogram == (0, 0, 5, 0, 0) and b_card.majority_copies == 2  # in the 5 decks that play both packages


def test_each_archetype_has_a_card_table_with_roles_shares_and_copy_histograms() -> None:
    file = rates()
    only_a = next(a for a in file.archetypes if a.packages == (PKG_A,))
    assert only_a.decks == 20 and not only_a.low_sample  # 20 decks run package A alone
    table = {c.card_number: c for c in only_a.cards}
    assert [table[c].role for c in (A1, A2, A3)] == [ArchetypeRole.CORE] * 3
    assert table[A1].histogram == (0, 0, 0, 0, 20) and table[A1].majority_copies == 4
    assert table[H].role is ArchetypeRole.SYNERGY and table[H].decks == 14 and table[H].share == 14 / 20  # tied to A1, in 14 of the 20 decks
    assert table[H].histogram == (6, 0, 14, 0, 0) and table[H].majority_copies == 2
    assert table[F1].role is ArchetypeRole.FREE_FLOATING and table[S2].share == 0.5
    assert B1 not in table  # B's cards are not in an archetype that does not run B
    both = next(a for a in file.archetypes if set(a.packages) == {PKG_A, PKG_B})  # signatures follow the packages' order, B first
    assert both.decks == 5 and both.low_sample  # few decks: the copy counts are flagged
    assert {c.card_number for c in both.cards} >= {A1, A2, A3, B1, B2, B3, B4}


def test_the_no_package_archetype_has_no_card_table_and_every_table_matches_its_decks() -> None:
    file = rates()
    nothing = next(a for a in file.archetypes if a.packages == ())
    assert nothing.cards == ()
    for a in file.archetypes:
        assert all(sum(c.histogram) == a.decks for c in a.cards)  # the model checks this too; here it is a test of the data
        assert all(c.share >= 0.25 or c.role in (ArchetypeRole.CORE, ArchetypeRole.OPTIONAL) for c in a.cards)
