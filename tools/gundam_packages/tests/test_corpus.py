"""Your own examples, checked against the real GD05 decks (skipped when the synced data isn't present)."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared.basetypes import CardNumber
from tools.gundam_cards.models import CardModel, CardsFile
from tools.gundam_cards.store import OUT_DIR as CARDS_DIR
from tools.gundam_cards.store import load_sets, release_dates
from tools.gundam_meta.dedupe import combined_events
from tools.gundam_meta.eras import load_era_defs, resolve_eras
from tools.gundam_meta.models import Era, EraId, Event
from tools.gundam_meta.store import OUT_DIR as META_DIR
from tools.gundam_meta.store import load_events
from tools.gundam_packages.build import ALL_TIERS, build_packages, card_colors, copy_decks, deck_sets, make_window, window_events
from tools.gundam_packages.drift import compute_drift, introduced_dates
from tools.gundam_packages.models import PackageId, PackagesFile, RatesFile
from tools.gundam_packages.naming import PackageNamer
from tools.gundam_packages.rates import compute_rates
from tools.gundam_packages.store import load_packages, write_packages
from tools.gundam_packages.synergy import build_graph

pytestmark = pytest.mark.corpus
needs_data = pytest.mark.skipif(
    not (META_DIR / "events" / "duelfrontier").is_dir() or not (CARDS_DIR / "cards.json").is_file(),
    reason="synced meta data and card catalog not present",
)
N = CardNumber


@pytest.fixture(scope="module")
def cards() -> dict[CardNumber, CardModel]:
    return {c.number: c for c in CardsFile.model_validate_json((CARDS_DIR / "cards.json").read_text(encoding="utf-8")).data}


@pytest.fixture(scope="module")
def eras() -> dict[EraId, Era]:
    return {e.id: e for e in resolve_eras(load_era_defs(), release_dates(load_sets()))}


@pytest.fixture(scope="module")
def events() -> tuple[Event, ...]:
    return combined_events(load_events())


@pytest.fixture(scope="module")
def gd05(cards: dict[CardNumber, CardModel], eras: dict[EraId, Era], events: tuple[Event, ...]) -> PackagesFile:
    file, _ = build_packages(events, cards, eras[EraId("gd05")], generated_at=datetime(2026, 10, 6, tzinfo=UTC))
    return file


def members(file: PackagesFile, number: str) -> frozenset[CardNumber] | None:
    for p in file.packages:
        found = frozenset(m.card_number for m in p.members)
        if N(number) in found:
            return found
    return None


@needs_data
def test_the_barbatos_trio_is_one_package(gd05: PackagesFile) -> None:
    # Barbatos Adapt, Barbatos 1st Form and Mikazuki Augus: "you will never see one without the other two".
    assert members(gd05, "GD03-056") == frozenset({N("GD03-056"), N("GD02-054"), N("ST05-010")})
    package = next(p for p in gd05.packages if N("GD03-056") in {m.card_number for m in p.members})
    assert package.name == "Mikazuki Barbatos" and package.decks_running == package.decks_running_all  # always all three


@needs_data
def test_the_other_packages_named_by_players(gd05: PackagesFile) -> None:
    assert members(gd05, "GD05-002") == frozenset({N("GD05-002"), N("GD05-081")})  # Strike Freedom + Kira Yamato
    assert members(gd05, "GD05-089") == frozenset({N("GD05-033"), N("GD05-089")})  # Master Gundam + Master Asia (red)
    assert {N("GD05-066"), N("GD05-097")} <= (members(gd05, "GD05-097") or frozenset())  # Shining Gundam, Domon (white): its own package
    assert {N("ST03-006"), N("GD04-017"), N("ST03-011")} <= (members(gd05, "ST03-011") or frozenset())  # the Char package
    assert members(gd05, "GD01-093") == frozenset({N("GD01-093"), N("GD01-044")})  # Marida + Kshatriya (red); the blue Unicorn 02 is outside it
    assert {(h.card_number, h.share) for h in gd05.synergy_cards if h.package == next(p.id for p in gd05.packages if N("GD01-093") in {m.card_number for m in p.members})} >= {(N("GD01-003"), 1.0)}
    assert {N("GD05-085"), N("GD05-017")} <= (members(gd05, "GD05-017") or frozenset())  # Amuro Ray + Nu Gundam


@needs_data
def test_cards_that_are_simply_good_are_free_floating(gd05: PackagesFile) -> None:
    free = {f.card_number for f in gd05.free_floating}
    # Airframe Seizure ("simply the best red draw card"), Gundam Exia Repair (its link, Setsuna, isn't in the decks), and the staples.
    assert {N("GD05-111"), N("GD05-050"), N("GD01-100"), N("GD01-118"), N("GD02-129")} <= free
    assert not free & {m.card_number for p in gd05.packages for m in p.members}


@needs_data
def test_exia_repair_is_often_played_with_a_package_but_that_is_not_synergy(gd05: PackagesFile) -> None:
    exia = next(f for f in gd05.free_floating if f.card_number == N("GD05-050"))
    assert exia.affinities and exia.affinities[0].share > 0.5  # in GD05 main decks it mostly goes with the Char package (68%)
    assert N("GD05-050") not in {h.card_number for h in gd05.synergy_cards}  # its only tie is a link to Setsuna, who isn't in these decks


@needs_data
def test_darkness_finger_is_synergy_cards_with_the_master_asia_package(gd05: PackagesFile) -> None:
    master = next(p for p in gd05.packages if N("GD05-089") in {m.card_number for m in p.members})
    hs = [h for h in gd05.synergy_cards if h.card_number == N("GD05-110")]  # its text names "Master Gundam"
    by_package = {h.package: h for h in hs}
    assert master.id in by_package and by_package[master.id].share > 0.9
    assert {e.detail for e in by_package[master.id].edges} >= {"Master Gundam"}


@needs_data
def test_every_card_is_in_at_most_one_package_and_packages_are_sound(gd05: PackagesFile) -> None:
    all_members = [m.card_number for p in gd05.packages for m in p.members]
    assert len(all_members) == len(set(all_members))
    assert all(len(p.members) >= 2 and p.decks_running >= gd05.params.min_decks for p in gd05.packages)
    assert all(p.edges for p in gd05.packages)  # every package has at least one structural tie behind it
    assert {c.card_number for c in gd05.free_floating}.isdisjoint({h.card_number for h in gd05.synergy_cards})
    assert abs(sum(a.share for a in gd05.archetypes) - 1.0) < 1e-9


@needs_data
def test_rebuilding_gives_identical_output(cards: dict[CardNumber, CardModel], eras: dict[EraId, Era], events: tuple[Event, ...], gd05: PackagesFile) -> None:
    again, _ = build_packages(events, cards, eras[EraId("gd05")], generated_at=gd05.generated_at)
    assert again == gd05


@needs_data
def test_files_round_trip(gd05: PackagesFile, tmp_path: Path) -> None:
    write_packages(gd05, tmp_path)
    loaded = load_packages(tmp_path)
    assert loaded == gd05


@needs_data
def test_gd05_5_drift_shows_the_new_cards(cards: dict[CardNumber, CardModel], eras: dict[EraId, Era], events: tuple[Event, ...], gd05: PackagesFile) -> None:
    new_era = eras[EraId("gd05_5")]
    new_events = window_events(events, new_era, ALL_TIERS)
    decks, not_counted = deck_sets(new_events, cards)
    drift = compute_drift(gd05, decks, make_window(new_era, ALL_TIERS, new_events, len(decks), not_counted),
                          build_graph(list(cards.values())), introduced_dates(cards, release_dates(load_sets())),
                          card_colors(cards), PackageNamer(cards), datetime(2026, 10, 6, tzinfo=UTC))  # fmt: skip
    new_cards = {n.card_number: n for n in drift.new_cards}
    assert N("ST11-009") in new_cards and new_cards[N("ST11-009")].package is None  # Kapool: a new free floater
    assert all(n.introduced >= new_era.start for n in new_cards.values())  # only cards introduced since GD05.5 began
    barbatos = next(p for p in drift.packages if p.package == PackageId("pkg:GD02-054"))
    assert barbatos.share_after > barbatos.share_before  # the Barbatos package grew
    assert drift.new.decks < 100  # flagged as a small sample


@needs_data
def test_a_trait_check_that_counts_itself_is_not_a_package(cards: dict[CardNumber, CardModel]) -> None:
    # Kapool: "a friendly (Marine) Unit is in play" is satisfied by Kapool itself, so Marine gives it no ties.
    own = [e for e in build_graph(list(cards.values())).edges_of(N("ST11-009")) if e.a == N("ST11-009") and e.kind.value == "trait_reference"]
    assert own == []


@needs_data
def test_tekkadan_is_a_trait_package_built_from_abilities_that_need_other_cards(gd05: PackagesFile) -> None:
    tekkadan = members(gd05, "GD03-050")  # Barbatos Lupus: "Choose 3 (Tekkadan)/(Teiwaz) Unit cards from your trash"
    assert tekkadan is not None and {N("ST05-006"), N("ST05-004"), N("GD02-055")} <= tekkadan  # Hyakuren, Graze Custom, Gusion Rebake
    package = next(p for p in gd05.packages if N("GD03-050") in {m.card_number for m in p.members})
    assert package.name == "Tekkadan" and {e.kind.value for e in package.edges} == {"trait_reference"}


@needs_data
def test_darkness_finger_and_close_combat_are_the_same_job(cards: dict[CardNumber, CardModel]) -> None:
    # Both deal damage to 1 enemy Unit in Main/Action (Darkness Finger also draws, Close Combat is cheaper to lose): level and cost no longer matter.
    ties = build_graph(list(cards.values())).edges_between(N("GD05-110"), N("ST03-013"))
    assert {e.kind.value for e in ties} == {"functional_effect"} and {e.kind.relation.value for e in ties} == {"functional_reprint"}


@needs_data
def test_damage_commands_form_overlapping_squads(gd05: PackagesFile) -> None:
    squads = [{c.card_number for c in g.cards} for g in gd05.squads]
    assert {N("GD05-110"), N("ST03-013"), N("GD01-111")} in squads  # Darkness Finger, Close Combat, Battle of Aces: every pair are peers
    assert {N("ST03-013"), N("GD03-109"), N("GD01-111")} in squads  # Close Combat, Improved Technique, Battle of Aces
    assert not any({N("ST03-013"), N("GD04-109")} <= s for s in squads)  # Overwhelming Pressure deals 4: too far from Close Combat's 2


@needs_data
def test_tekkadan_units_with_the_same_ability_at_different_levels_are_synergy(cards: dict[CardNumber, CardModel]) -> None:
    graph = build_graph(list(cards.values()))
    for a, b in (("GD02-055", "GD03-050"), ("GD02-055", "GD03-056"), ("GD03-050", "GD03-056")):  # Gusion Rebake, Lupus, Barbatos Adapt
        relations = {e.kind.relation.value for e in graph.edges_between(N(a), N(b))}
        assert "functional_reprint" not in relations  # Lv5/cost4, Lv7/cost6 and Lv4/cost2 are not substitutes


@needs_data
def test_white_blockers_are_effective_duplicates_and_join_the_aile_strike_package(gd05: PackagesFile) -> None:
    aile = members(gd05, "ST04-001")
    assert aile is not None and {N("GD01-086"), N("GD02-079")} <= aile  # Gundam Lfrith and Rick Dias: white Units with Blocker
    package = next(p for p in gd05.packages if N("ST04-001") in {m.card_number for m in p.members})
    assert {"combo", "functional_reprint"} <= {e.kind.relation.value for e in package.edges}


@needs_data
def test_every_package_is_one_color(gd05: PackagesFile) -> None:
    assert all(len(p.colors) == 1 for p in gd05.packages)


@needs_data
def test_strike_rouge_is_a_bridge_between_the_strike_freedom_and_tekkadan_packages(gd05: PackagesFile) -> None:
    # Blue Strike Rouge (Ootori) is a good Tekkadan pick because it is a Blocker, but it is in Tekkadan decks only because they also run
    # Strike Freedom (0 of the 4 Tekkadan decks without it). So it links the two packages instead of being Tekkadan's synergy card.
    freedom = next(p.id for p in gd05.packages if N("GD05-002") in {m.card_number for m in p.members})
    tekkadan = next(p.id for p in gd05.packages if N("GD02-055") in {m.card_number for m in p.members})
    pair = next(s for s in gd05.package_synergies if {s.package_a, s.package_b} == {freedom, tekkadan})
    assert N("GD05-005") in {b.card_number for b in pair.bridges}
    assert (N("GD05-005"), tekkadan) not in {(h.card_number, h.package) for h in gd05.synergy_cards}
    assert (N("GD05-005"), freedom) in {(h.card_number, h.package) for h in gd05.synergy_cards}  # it does stand on its own in Strike Freedom's decks


@pytest.fixture(scope="module")
def gd05_rates(gd05: PackagesFile, cards: dict[CardNumber, CardModel], eras: dict[EraId, Era], events: tuple[Event, ...]) -> RatesFile:
    listed, _ = copy_decks(window_events(events, eras[EraId("gd05")], ALL_TIERS), cards)
    return compute_rates(gd05, listed, datetime(2026, 10, 7, tzinfo=UTC))


@needs_data
def test_rates_for_mikazuki_barbatos_match_the_hand_checked_numbers(gd05: PackagesFile, gd05_rates: RatesFile) -> None:
    assert gd05_rates.total_decks == gd05.window.decks == 253
    mika = next(p for p in gd05_rates.packages if p.name == "Mikazuki Barbatos")
    assert (mika.package_decks, mika.rate) == (54, 54 / 253)
    adapt = next(m for m in mika.members if m.card_number == N("GD03-056"))
    assert (adapt.copies, adapt.possible) == (216, 216)  # a 4-of in every deck that plays the package
    tekkadan = next(w for w in mika.partners if gd05_rates_name(gd05_rates, w.package) == "Tekkadan")
    assert (tekkadan.pair_decks, tekkadan.combined_rate, tekkadan.joint_rate) == (24, 24 / 54, 24 / 253)
    graze = next(c for c in tekkadan.cards if c.card_number == N("ST05-004"))
    assert graze.rate_from_x == pytest.approx(92 / 216)  # 92 copies of 216 possible in Mika's 54 decks: the figure in appearance-rates.md


def gd05_rates_name(file: RatesFile, package: PackageId) -> str:
    return next(p.name for p in file.packages if p.package == package)


@needs_data
def test_rates_are_consistent_everywhere(gd05_rates: RatesFile) -> None:
    assert sum(a.rate for a in gd05_rates.archetypes) == pytest.approx(1.0)
    for p in gd05_rates.packages:
        assert all(0.0 <= m.rate <= 1.0 for m in p.members) and all(0.0 <= o.rate <= 1.0 for o in p.others)
        for w in p.partners:  # rate from X is also copies / (4 x X's decks)
            assert all(c.rate_from_x == pytest.approx(c.copies / (4 * p.package_decks)) for c in (*w.cards, *w.bridges))
    members = {m.card_number: p.package for p in gd05_rates.packages for m in p.members}
    assert all(gd05_rates.card_index[c] == pid for c, pid in members.items())
