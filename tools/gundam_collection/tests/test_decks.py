"""Which decks I support, which I am close to, and what to get: on the synthetic worlds with known answers."""
from __future__ import annotations

from dataclasses import replace

from shared.basetypes import CardNumber
from tools.gundam_cards.models import CardModel
from tools.gundam_collection.bands import Band
from tools.gundam_collection.decks import (
    DECK_SIZE,
    Deck,
    Layer,
    Pick,
    Requirement,
    build_decks,
    fit_to_deck,
    coverage,
    needed_by,
    overview,
    package_stages,
    picks,
)
from tools.gundam_collection.models import Stage
from tools.gundam_packages.models import DataSource, PackageId, PackagesFile, RatesFile, SquadCard, Squad, SynergyKind
from tools.gundam_packages.tests.test_discover import A1, A2, A3, B1, F1, H, O, S2, world
from tools.gundam_packages.tests.helpers import catalog, pilot, unit
from tools.gundam_packages.tests.test_drift import base_file
from tools.gundam_packages.tests.test_rates import rates

N = CardNumber
PKG_A = PackageId("pkg:GD01-001")


def names(**overrides: str) -> dict[CardNumber, str]:
    out = {n: f"Card {n}" for d in world() for n in d}
    out.update({N(k): v for k, v in overrides.items()})
    return out


def tournament() -> dict[DataSource, tuple[PackagesFile, RatesFile]]:
    return {DataSource.TOURNAMENT: (base_file(), rates())}


def both() -> dict[DataSource, tuple[PackagesFile, RatesFile]]:
    online = (base_file().model_copy(update={"source": DataSource.ONLINE}), rates().model_copy(update={"source": DataSource.ONLINE}))
    return {**tournament(), DataSource.ONLINE: online}


def deck_a() -> Deck:
    return next(d for d in build_decks(tournament(), min_rate=0.0) if [r for _, _, r in d.package_refs] == [PKG_A])


def test_a_deck_is_layered_into_core_staples_and_options_with_copy_counts_from_its_lists() -> None:
    deck = deck_a()
    by_card = {r.card: r for r in deck.requirements}
    assert [by_card[c].layer for c in (A1, A2, A3)] == [Layer.CORE] * 3
    assert (by_card[A1].need, by_card[A2].need) == (4, 2)  # the majority copy count: A1 is a 4-of, A2 a 2-of in all 20 decks
    assert by_card[A1].why == ("core of pkg:GD01-001",)
    assert by_card[H].layer is Layer.STAPLE and by_card[H].need == 2 and by_card[H].share == 0.7 and by_card[H].why == ("in 70% of its lists",)
    assert by_card[F1].layer is Layer.STAPLE and by_card[O].layer is Layer.STAPLE and by_card[S2].layer is Layer.STAPLE  # half of the lists or more
    assert deck.requirements == tuple(sorted(deck.requirements, key=lambda r: (list(Layer).index(r.layer), -r.share, r.card)))  # core first, staples most-run first


def test_the_same_deck_in_both_sources_is_one_deck_with_both_play_rates() -> None:
    one = build_decks(tournament(), min_rate=0.0)
    two = build_decks(both(), min_rate=0.0)
    assert len(two) == len(one)  # the matching packages merge the decks
    merged = next(d for d in two if [r for _, _, r in d.package_refs] == [PKG_A])
    assert set(merged.rates) == {DataSource.TOURNAMENT, DataSource.ONLINE} and merged.requirements == deck_a().requirements


def test_decks_below_the_play_rate_floor_are_left_out() -> None:
    assert all(d.top_rate >= 0.3 for d in build_decks(tournament(), min_rate=0.3))
    assert len(build_decks(tournament(), min_rate=0.3)) < len(build_decks(tournament(), min_rate=0.0))
    assert build_decks(tournament(), min_rate=0.99) == ()


def own_everything(deck: Deck, copies: int = 4) -> dict[CardNumber, int]:
    return {r.card: copies for r in deck.requirements}


def test_a_deck_is_perfect_only_when_every_core_and_staple_copy_is_owned() -> None:
    deck = deck_a()
    prices = {r.card: 100 for r in deck.requirements}
    full = coverage(deck, (), own_everything(deck), prices, {})
    assert full.band is Band.PERFECT and full.working_share == 1.0 and full.cost_cents(Layer.CORE, Layer.STAPLE) == 0 and full.next_band is None
    owned = own_everything(deck)
    del owned[H]  # all the core, but a staple is missing
    core_only = coverage(deck, (), owned, prices, {})
    assert core_only.have(Layer.CORE) == core_only.need(Layer.CORE) and core_only.band is not Band.PERFECT  # staples count toward the band
    assert core_only.cost_cents(Layer.CORE, Layer.STAPLE) == 2 * 100  # two copies of H are missing
    up = core_only.next_band
    assert up is not None and up.band is Band.COMPLETE and dict(up.buys) == {H: 1} and up.cost_cents == 100  # one copy gets to 90%
    assert core_only.band is Band.PLAYABLE


def test_a_deck_with_a_core_card_at_one_of_four_is_not_playable_however_much_else_is_owned() -> None:
    deck = deck_a()
    prices = {r.card: 100 for r in deck.requirements}
    owned = own_everything(deck)
    owned[A1] = 1  # A1 is a core 4-of
    cov = coverage(deck, (), owned, prices, {})
    assert cov.working_share > 0.75 and cov.band is Band.REACHABLE and not cov.playable  # the key-card guard
    up = cov.next_band
    assert up is not None and up.band is Band.PLAYABLE and dict(up.buys) == {A1: 1}  # one more copy of the key card, nothing else
    owned[A1] = 2
    assert coverage(deck, (), owned, prices, {}).band in (Band.PLAYABLE, Band.COMPLETE) and coverage(deck, (), owned, prices, {}).playable


def test_nothing_owned_is_not_happening_and_a_missing_price_makes_the_cost_a_minimum() -> None:
    deck = deck_a()
    prices = {r.card: 100 for r in deck.requirements}
    empty = coverage(deck, (), {}, prices, {})
    assert empty.band is Band.NOT_HAPPENING and empty.working_share == 0.0
    up = empty.next_band
    assert up is not None and up.band is Band.LONG_SHOT
    assert coverage(deck, (), {}, {}, {}).unpriced_missing(Layer.CORE) == 8  # no prices: the cost is a minimum


def test_the_overview_puts_perfect_first_by_how_played_and_every_other_band_cheapest_to_move_up_first() -> None:
    decks = build_decks(tournament(), min_rate=0.0)
    prices = {n: 100 for d in decks for n in (r.card for r in d.requirements)}
    owned = {n: 4 for n in prices}
    groups = overview([coverage(d, (), owned, prices, {}) for d in decks])
    assert [c.deck.top_rate for c in groups[Band.PERFECT]] == sorted((c.deck.top_rate for c in groups[Band.PERFECT]), reverse=True)
    some = {n: (4 if i % 5 else 0) for i, n in enumerate(prices)}
    for band, rows in overview([coverage(d, (), some, prices, {}) for d in decks]).items():
        if band is not Band.PERFECT:
            costs = [c.next_band.cost_cents if c.next_band else 0 for c in rows]
            assert costs == sorted(costs)


def test_picks_come_core_first_then_staples_most_run_first_then_cheapest_and_explain_themselves() -> None:
    deck = deck_a()
    prices = {A1: 1500, A2: 50, A3: 80, H: 20, F1: 10, O: 30, S2: 5}
    cov = coverage(deck, (), {}, prices, {})
    buy = picks(cov, {})
    layers = [p.layer for p in buy]
    assert layers == sorted(layers, key=list(Layer).index)  # core, then staples
    core = [p for p in buy if p.layer is Layer.CORE]
    assert [p.card for p in core] == [A2, A3, A1]  # the cheapest first (no other deck shares them); the premium one last
    assert core[-1].premium and not core[0].premium and core[-1].copies == 4 and core[-1].line_cents == 6000
    staples = [p for p in buy if p.layer is Layer.STAPLE]
    assert [p.share for p in staples] == sorted((p.share for p in staples), reverse=True)  # the most-run staples first
    assert sum(p.copies for p in buy if p.layer in (Layer.CORE, Layer.STAPLE)) == cov.need(Layer.CORE, Layer.STAPLE)  # every missing copy is in exactly one pick
    assert all(p.why for p in buy)


def test_a_card_other_supported_or_close_decks_also_need_comes_first_and_says_so() -> None:
    deck = deck_a()
    prices = {A1: 100, A2: 100, A3: 100, H: 20, F1: 20, O: 20, S2: 20}
    cov = coverage(deck, (), {}, prices, {})
    durable = {A3: (("Another deck", 0.3), ("Third deck", 0.1)), A2: (("Another deck", 0.3),)}
    core = [p for p in picks(cov, durable) if p.layer is Layer.CORE]
    assert [p.card for p in core][:2] == [A3, A2] and core[0].also_needed_by == ("Another deck", "Third deck")  # needed by two others, then by one
    own_deck = {A3: (("Master", 0.5),)}
    assert [p for p in picks(cov, own_deck) if p.card == A3][0].also_needed_by == ("Master",)
    assert needed_by([]) == {}


def test_needed_by_counts_only_supported_and_close_decks_and_never_far_ones() -> None:
    decks = build_decks(tournament(), min_rate=0.0)
    prices = {r.card: 10 for d in decks for r in d.requirements}
    full = {n: 4 for n in prices}
    covs = [coverage(d, (), full, prices, {}) for d in decks]
    found = needed_by(covs)
    assert A1 in found and all(rate > 0 for rows in found.values() for _, rate in rows)
    assert needed_by([coverage(d, (), {}, prices, {}) for d in decks]) == {}  # I own nothing: every deck is far


def test_a_decks_packages_are_tagged_home_adjacent_or_new_in_the_source_they_are_known_by() -> None:
    deck = deck_a()
    stages = {DataSource.TOURNAMENT: {PKG_A: Stage.HOME}}
    assert package_stages(deck, stages) == (("pkg:GD01-001", Stage.HOME),)
    assert isinstance(picks(coverage(deck, (), {}, {}, {}), {})[0], Pick)


def test_core_plus_staples_never_need_more_copies_than_a_deck_holds() -> None:
    assert DECK_SIZE == 50
    reqs = [Requirement(N(f"C-00{i}"), Layer.CORE, 4, 1.0, ("core",)) for i in range(1, 8)]  # 28 core copies
    reqs += [Requirement(N(f"S-0{i:02d}"), Layer.STAPLE, 4, 0.9 - i / 100, ("staple",)) for i in range(1, 9)]  # 32 staple copies, most-run first
    fitted = fit_to_deck(reqs)
    working = [r for r in fitted if r.layer in (Layer.CORE, Layer.STAPLE)]
    assert sum(r.need for r in working) == 50  # the staples fill the 22 copies of room
    staples = [r for r in fitted if r.layer is Layer.STAPLE]
    assert [(r.card, r.need) for r in staples] == [("S-001", 4), ("S-002", 4), ("S-003", 4), ("S-004", 4), ("S-005", 4), ("S-006", 2)]  # the sixth fits in part
    assert [(r.card, r.layer, r.need) for r in fitted if r.layer is Layer.OPTION] == [("S-007", Layer.OPTION, 4), ("S-008", Layer.OPTION, 4)]  # the rest become options
    assert fit_to_deck(reqs[:7]) == tuple(reqs[:7])  # no staples: nothing to cut
    short = [Requirement(N("C-001"), Layer.CORE, 4, 1.0, ("core",)), Requirement(N("S-001"), Layer.STAPLE, 4, 0.8, ("staple",))]
    assert fit_to_deck(short) == tuple(short)  # a small deck is unchanged


def test_the_overview_can_be_sorted_by_how_played_instead_of_cost() -> None:
    decks = build_decks(tournament(), min_rate=0.0)
    prices = {n: 100 for d in decks for n in (r.card for r in d.requirements)}
    some = {n: (4 if i % 5 else 0) for i, n in enumerate(prices)}
    covs = [coverage(d, (), some, prices, {}) for d in decks]
    for band, rows in overview(covs, "played").items():
        assert [c.deck.top_rate for c in rows] == sorted((c.deck.top_rate for c in rows), reverse=True), band


def test_the_banned_and_restricted_list_clamps_needs_drops_banned_cards_and_flags_illegal_pairs() -> None:
    from tools.gundam_cards.legality import Rules

    rules = Rules(banned=frozenset({H}), limits={A2: 1}, pairs=frozenset({frozenset({A1, A3})}), vanilla=frozenset())
    deck = next(d for d in build_decks(tournament(), min_rate=0.0, rules=rules) if [r for _, _, r in d.package_refs] == [PKG_A])
    by_card = {r.card: r for r in deck.requirements}
    assert H not in by_card  # banned: not needed at all
    assert by_card[A2].need == 1  # restricted to 1 (the lists run 2)
    assert any("banned pair" in why for why in deck.illegal)  # A1 and A3 are both core and cannot be played together
    plain = next(d for d in build_decks(tournament(), min_rate=0.0) if [r for _, _, r in d.package_refs] == [PKG_A])
    assert plain.illegal == () and H in {r.card for r in plain.requirements}  # no list: nothing changes
