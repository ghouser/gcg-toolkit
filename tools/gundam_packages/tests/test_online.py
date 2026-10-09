"""Online decks: the weighted example lists as whole decks, the same analysis, and comparing packages across sources."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from shared.basetypes import CardNumber
from tools.gundam_cards.models import CardKind
from tools.gundam_meta.models import DeckCard, ExampleArchetype, ExampleDecksSnapshot, ExampleList
from tools.gundam_packages.build import apportion, online_copy_decks, online_window
from tools.gundam_packages.compare import match_packages
from tools.gundam_packages.models import DataSource, PackageId
from tools.gundam_packages.store import load_packages, write_packages
from tools.gundam_packages.tests.helpers import catalog, unit
from tools.gundam_packages.tests.test_drift import base_file

N = CardNumber
NOW = datetime(2026, 10, 8, 6, 0, tzinfo=UTC)
A, B, C = N("GD01-001"), N("GD01-002"), N("GD01-003")


def lst(cards: dict[CardNumber, int], share: float | None) -> ExampleList:
    return ExampleList(url=f"https://x/?deck={sorted(cards)}", cards=tuple(DeckCard(card_number=c, qty=q) for c, q in cards.items()), share=share)


def snapshot(*archetypes: ExampleArchetype) -> ExampleDecksSnapshot:
    return ExampleDecksSnapshot(fetched_at=NOW, window_days=14, season="GD05", archetypes=archetypes,
                                slugs_without_archetype=(), unresolved_lists=())  # fmt: skip


def test_apportion_gives_whole_numbers_that_add_up_exactly() -> None:
    assert apportion([1, 1, 1], 10) == [4, 3, 3]  # the leftover goes to the earliest of equal remainders
    assert apportion([210, 90, 100], 10_000) == [5250, 2250, 2500]
    counts = apportion([0.1234, 0.5, 0.3766, 0.0001], 10_000)
    assert sum(counts) == 10_000 and counts[3] in (0, 1)  # a tiny weight gets at most one deck


def test_online_decks_are_the_lists_repeated_in_proportion_to_games_times_share() -> None:
    cards = catalog(unit("GD01-001", "A"), unit("GD01-002", "B"), unit("GD01-003", "C"))
    big = ExampleArchetype(slug="big", name="Big", games=300, sides_analyzed=500, lists=(lst({A: 4, B: 2}, 0.7), lst({A: 4, C: 1}, 0.3)))
    small = ExampleArchetype(slug="small", name="Small", games=100, sides_analyzed=80, lists=(lst({B: 4}, 1.0),))
    no_shares = ExampleArchetype(slug="none", name="None", games=999, sides_analyzed=None, lists=(lst({C: 4}, None),))
    decks, used = online_copy_decks(snapshot(big, small, no_shares), cards)
    assert len(decks) == 10_000 and used == 3  # the archetype without shares has no weight
    assert sum(1 for d in decks if d == {A: 4, B: 2}) == 5250 and sum(1 for d in decks if d == {A: 4, C: 1}) == 2250
    assert sum(1 for d in decks if d == {B: 4}) == 2500 and not any(C in d and A not in d for d in decks)


def test_online_decks_keep_only_deck_cards_of_the_catalog() -> None:
    cards = catalog(unit("GD01-001", "A"))
    resource = N("R-001")
    arch = ExampleArchetype(slug="x", name="X", games=10, sides_analyzed=5, lists=(lst({A: 4, resource: 2, N("GD09-999"): 1}, 1.0),))
    decks, _ = online_copy_decks(snapshot(arch), cards, total=100)
    assert decks == [{A: 4}] * 100
    assert CardKind.RESOURCE.is_deck_card is False


def test_the_online_window_says_it_is_example_decks_not_events() -> None:
    w = online_window(snapshot(), 10_000)
    assert (w.era, w.events, w.decks, str(w.start)) == (None, 0, 10_000, "2026-09-24")


def test_online_and_tournament_files_are_kept_apart(tmp_path: Path) -> None:
    online = base_file().model_copy(update={"source": DataSource.ONLINE})
    path = write_packages(online, tmp_path)
    assert path.name == "packages_online.json"
    assert load_packages(tmp_path, source=DataSource.ONLINE) == online and load_packages(tmp_path) is None
    assert write_packages(base_file(), tmp_path).name == "packages.json"


def test_packages_match_across_sources_by_the_cards_they_share() -> None:
    left = {PackageId("l1"): frozenset({A, B, C}), PackageId("l2"): frozenset({N("GD02-001"), N("GD02-002")}), PackageId("l3"): frozenset({N("GD09-001")})}
    right = {PackageId("r1"): frozenset({A, B, C, N("GD01-004")}), PackageId("r2"): frozenset({N("GD02-001"), N("GD02-002")}), PackageId("r3"): frozenset({N("GD07-001")})}
    pairs, left_only, right_only = match_packages(left, right)
    assert [(a, b, round(s, 2)) for a, b, s in pairs] == [("l2", "r2", 1.0), ("l1", "r1", 0.75)]
    assert left_only == ("l3",) and right_only == ("r3",)
