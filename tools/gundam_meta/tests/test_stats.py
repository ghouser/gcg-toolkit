from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from shared.basetypes import CardNumber, SetCode
from tools.gundam_cards.models import CardKind
from tools.gundam_meta.eras import load_era_defs, resolve_eras
from tools.gundam_meta.models import (
    Deck,
    DeckCard,
    DeckId,
    EraId,
    Event,
    EventId,
    EventType,
    MsaBucket,
    SnapshotFile,
    Source,
    Tier,
)
from tools.gundam_meta.stats import StatsResult, build_popularity, compute_stats, events_in_window

NOW = datetime(2026, 10, 6, 20, 0, tzinfo=UTC)
G, B, FILLER = CardNumber("GD05-001"), CardNumber("ST05-001"), CardNumber("GD01-100")  # "GFred", "Barbatos", filler
RESOURCE, UNKNOWN = CardNumber("R-001"), CardNumber("GD99-001")
KINDS = {G: CardKind.UNIT, B: CardKind.UNIT, FILLER: CardKind.UNIT, RESOURCE: CardKind.RESOURCE}
FIXTURES = Path(__file__).parent / "fixtures"


def deck(n: int, cards: dict[CardNumber, int], *, side: dict[CardNumber, int] | None = None, available: bool = True, unresolved: tuple[str, ...] = ()) -> Deck:
    main = () if not available else tuple(DeckCard(card_number=c, qty=q) for c, q in cards.items())
    sideboard = () if not available else tuple(DeckCard(card_number=c, qty=q) for c, q in (side or {}).items())
    return Deck(id=DeckId(f"d{n}"), player_name=f"p{n}", placement=n, name=None, available=available, main=main, side=sideboard, unresolved=unresolved)


def event(
    name: str,
    decks: list[Deck],
    *,
    day: date = date(2026, 10, 3),
    source: Source = Source.DUELFRONTIER,
    event_type: EventType = EventType.REGIONAL,
) -> Event:
    return Event(
        source=source, id=EventId(name), name=name, start_date=day, end_date=None, country=None, city=None, players=None,
        rounds=None, event_type=event_type, type_raw="x", format_label=None, decks=tuple(decks), fetched_at=NOW, warnings=(),
    )  # fmt: skip


def stats(events: list[Event]) -> StatsResult:
    return compute_stats(events, KINDS, source=Source.DUELFRONTIER, tier=Tier.MAJOR, era=None, start=date(2026, 1, 1), end=None)


def test_the_worked_example_from_the_design() -> None:
    # 8 decks x 50 cards = 400. A singleton in one list is 1/400; a 4-of in three lists is 12/400.
    decks = [deck(1, {G: 1, FILLER: 49})]
    decks += [deck(n, {B: 4, FILLER: 46}) for n in (2, 3, 4)]
    decks += [deck(n, {FILLER: 50}) for n in (5, 6, 7, 8)]
    result = stats([event("e", decks)])
    s = result.stats
    assert (s.events, s.decks, s.decks_not_counted, s.total_copies) == (1, 8, 0, 400)
    by_card = {c.card_number: c for c in s.cards}
    assert (by_card[G].copies, by_card[G].share, by_card[G].decks) == (1, 1 / 400, 1)
    assert (by_card[B].copies, by_card[B].share, by_card[B].decks) == (12, 12 / 400, 3)
    assert by_card[FILLER].copies == 49 + 3 * 46 + 4 * 50
    assert sum(c.share for c in s.cards) == pytest.approx(1.0)
    assert [c.card_number for c in s.cards][0] == FILLER  # most played first


def test_windows_pool_events_so_bigger_events_weigh_more() -> None:
    small = event("small", [deck(1, {G: 50})])  # 50 copies of G
    big = event("big", [deck(n, {B: 50}) for n in range(1, 4)])  # 150 copies of B
    s = stats([small, big]).stats
    assert s.total_copies == 200 and {c.card_number: c.share for c in s.cards} == {G: 0.25, B: 0.75}


def test_sideboard_cards_are_counted() -> None:
    s = stats([event("e", [deck(1, {FILLER: 50}, side={G: 10})])]).stats
    assert s.total_copies == 60 and {c.card_number: c.copies for c in s.cards}[G] == 10


def test_private_and_unreadable_decks_are_not_counted() -> None:
    decks = [deck(1, {FILLER: 50}), deck(2, {}, available=False), deck(3, {B: 50}, unresolved=("A:3|B:3",))]
    s = stats([event("e", decks)]).stats
    assert (s.decks, s.decks_not_counted, s.total_copies) == (1, 2, 50)


def test_non_deck_cards_are_excluded_from_whole_and_parts() -> None:
    s = stats([event("e", [deck(1, {FILLER: 48, RESOURCE: 2})])]).stats
    assert (s.total_copies, s.excluded_copies) == (48, 2) and RESOURCE not in {c.card_number for c in s.cards}


def test_cards_missing_from_the_catalog_are_reported_not_guessed() -> None:
    result = stats([event("e", [deck(1, {FILLER: 49, UNKNOWN: 1})])])
    assert result.unknown_cards == {UNKNOWN} and result.stats.total_copies == 49


def test_source_tier_and_window_filters() -> None:
    mke = event("mke", [deck(1, {G: 50})], day=date(2026, 10, 3))
    old = event("old", [deck(1, {B: 50})], day=date(2026, 9, 1))
    egm = event("egm", [deck(1, {FILLER: 50})], source=Source.EGM, event_type=EventType.LARGE_OFFICIAL)
    local = event("local", [deck(1, {FILLER: 50})], event_type=EventType.STORE_CHAMPIONSHIP)
    everything = [mke, old, egm, local]
    assert [e.name for e in events_in_window(everything, Source.DUELFRONTIER, Tier.MAJOR, date(2026, 1, 1), None)] == ["mke", "old"]
    assert [e.name for e in events_in_window(everything, Source.DUELFRONTIER, Tier.MAJOR, date(2026, 9, 25), None)] == ["mke"]
    assert [e.name for e in events_in_window(everything, Source.DUELFRONTIER, Tier.MAJOR, date(2026, 9, 1), date(2026, 9, 25))] == ["old"]  # end is exclusive
    assert [e.name for e in events_in_window(everything, Source.EGM, Tier.MAJOR, date(2026, 1, 1), None)] == ["egm"]
    assert [e.name for e in events_in_window(everything, Source.DUELFRONTIER, Tier.LOCAL, date(2026, 1, 1), None)] == ["local"]


def test_an_empty_window_has_no_cards_and_does_not_divide_by_zero() -> None:
    s = stats([]).stats
    assert (s.events, s.decks, s.total_copies, s.cards) == (0, 0, 0, ())


def test_popularity_covers_started_eras_per_source_and_tier() -> None:
    dates = {SetCode("GD05"): date(2026, 7, 24), SetCode("ST11"): date(2026, 9, 25), SetCode("ST12"): date(2026, 9, 25),
             SetCode("ST13"): date(2026, 9, 25), SetCode("ST14"): date(2026, 9, 25), SetCode("GD06"): date(2026, 10, 30)}  # fmt: skip
    eras = resolve_eras(load_era_defs(), dates)
    events = [
        event("august", [deck(1, {G: 50})], day=date(2026, 8, 15)),
        event("october", [deck(1, {B: 50})], day=date(2026, 10, 3)),
        event("egm-oct", [deck(1, {FILLER: 50})], day=date(2026, 10, 3), source=Source.EGM, event_type=EventType.UNOFFICIAL),
        event("before-any-era", [deck(1, {G: 50})], day=date(2026, 6, 1)),
    ]
    snap = SnapshotFile.model_validate_json((FIXTURES / "online_ranking_snapshot.json").read_text(encoding="utf-8")).data
    build = build_popularity(events, [snap], KINDS, eras, date(2026, 10, 6), NOW)
    keys = [("combined" if t.source is None else t.source.value, t.tier.value, str(t.era)) for t in build.popularity.tournaments]
    assert keys == [  # ordered by era, then source (combined first), then tier
        ("combined", "major", "gd05"), ("duelfrontier", "major", "gd05"),
        ("combined", "major", "gd05_5"), ("combined", "local", "gd05_5"),
        ("duelfrontier", "major", "gd05_5"), ("egm", "local", "gd05_5"),
    ]  # fmt: skip
    assert all(str(t.era) != "gd06" for t in build.popularity.tournaments)  # GD06 hasn't started
    assert build.popularity.msa is not None and build.popularity.msa.cards[0].bucket is MsaBucket.CORE_META
    assert build.popularity.msa.snapshot == snap.generated_at and len(build.popularity.msa.cards) == 282
    assert EraId("gd05") in {t.era for t in build.popularity.tournaments}


def test_popularity_without_snapshots_has_no_msa() -> None:
    assert build_popularity([], [], KINDS, [], date(2026, 10, 6), NOW).popularity.msa is None
