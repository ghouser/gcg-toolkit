from __future__ import annotations

from datetime import UTC, date, datetime

from shared.basetypes import CardNumber
from tools.gundam_meta.dedupe import combined_events, find_duplicate_groups, match_events, normalize_player
from tools.gundam_meta.models import Deck, DeckCard, DeckId, Event, EventId, EventType, Source

NOW = datetime(2026, 10, 6, tzinfo=UTC)


def lst(*pairs: tuple[str, int]) -> tuple[DeckCard, ...]:
    return tuple(DeckCard(card_number=CardNumber(c), qty=q) for c, q in pairs)


def mk_deck(player: str, cards: tuple[DeckCard, ...], place: int = 1, *, available: bool = True, unresolved: tuple[str, ...] = ()) -> Deck:
    return Deck(id=DeckId(f"{player}-{place}"), player_name=player, placement=place, name=None, available=available,
                main=cards if available else (), side=(), unresolved=unresolved)  # fmt: skip


def mk_event(source: Source, name: str, day: date, decks: list[Deck]) -> Event:
    return Event(source=source, id=EventId(name), name=name, start_date=day, end_date=None, country=None, city=None, players=None,
                 rounds=None, event_type=EventType.REGIONAL if source is Source.DUELFRONTIER else EventType.LARGE_OFFICIAL,
                 type_raw="x", format_label=None, decks=tuple(decks), fetched_at=NOW, warnings=())  # fmt: skip


def lists(n: int) -> list[tuple[DeckCard, ...]]:
    """n distinct 50-card lists."""
    return [lst((f"GD01-{i:03d}", 4), ("GD02-001", 46)) for i in range(1, n + 1)]


PLAYERS = ["Taidana", "Drew F", "JeZZus", "Ana", "Bo", "Cy", "Dee", "Eli"]


def event_pair(day_b: date = date(2026, 10, 4), n: int = 8) -> tuple[Event, Event]:
    cards = lists(n)
    a = mk_event(Source.DUELFRONTIER, "Regional Santiago 2026", date(2026, 10, 3), [mk_deck(PLAYERS[i], cards[i], i + 1) for i in range(n)])
    b = mk_event(Source.EGM, "PlayLATAM's Chile Regionals", day_b, [mk_deck(PLAYERS[i], cards[i], i + 1) for i in range(n)])
    return a, b


def test_the_same_event_under_different_names_and_dates_is_found() -> None:
    a, b = event_pair(date(2026, 10, 4))
    m = match_events(a, b)
    assert m is not None and (m.confirmed, m.identical, m.smaller, m.days_apart) == (8, 8, 8, 1)


def test_player_names_compare_loosely() -> None:
    assert normalize_player("  JeZZus ") == normalize_player("jezzus") and normalize_player("ＡＢ  c") == "ab c"


def test_events_from_the_same_source_never_match() -> None:
    a, _ = event_pair()
    twin = mk_event(Source.DUELFRONTIER, "twin", a.start_date, list(a.decks))
    assert match_events(a, twin) is None


def test_far_apart_dates_do_not_match() -> None:
    a, b = event_pair(date(2026, 10, 3) + __import__("datetime").timedelta(days=4))
    assert match_events(a, b) is None


def test_one_coincidentally_identical_list_is_not_enough() -> None:
    # A popular netdeck at two unrelated events: same list, different players, everything else different.
    cards = lists(8)
    shared = cards[0]
    a = mk_event(Source.DUELFRONTIER, "A", date(2026, 10, 3), [mk_deck(f"a{i}", shared if i == 0 else cards[i], i + 1) for i in range(8)])
    other_lists = [lst((f"ST01-{i:03d}", 4), ("GD02-001", 46)) for i in range(1, 8)]
    b = mk_event(Source.EGM, "B", date(2026, 10, 3), [mk_deck("b0", shared, 1)] + [mk_deck(f"b{i}", other_lists[i - 1], i + 1) for i in range(1, 8)])
    m = match_events(a, b)
    assert m is None  # 1 identical list, 0 confirmed (no shared player names)


def test_tiny_events_match_when_every_deck_is_confirmed() -> None:
    cards = lists(2)
    a = mk_event(Source.DUELFRONTIER, "NTC", date(2026, 8, 9), [mk_deck("Ana", cards[0], 1), mk_deck("Bo", cards[1], 2)])
    b = mk_event(Source.EGM, "Locals", date(2026, 8, 10), [mk_deck("ana", cards[0], 1), mk_deck("bo", cards[1], 2), mk_deck("Cy", lists(3)[2], 3)])
    m = match_events(a, b)
    assert m is not None and (m.confirmed, m.smaller) == (2, 2)


def test_names_spelled_differently_still_match_on_many_identical_lists() -> None:
    cards = lists(8)
    a = mk_event(Source.DUELFRONTIER, "A", date(2026, 10, 3), [mk_deck(f"Player {i}", cards[i], i + 1) for i in range(8)])
    b = mk_event(Source.EGM, "B", date(2026, 10, 3), [mk_deck(f"P. {i}", cards[i], i + 1) for i in range(8)])
    m = match_events(a, b)
    assert m is not None and m.confirmed == 0 and m.identical == 8  # the list-only fallback


def test_the_fuller_copy_is_kept_and_unreadable_decks_are_filled_in() -> None:
    a, b = event_pair()
    private = mk_deck(PLAYERS[1], (), 2, available=False)  # DuelFrontier couldn't read the second deck
    a = a.model_copy(update={"decks": (a.decks[0], private, *a.decks[2:])})
    (group,) = find_duplicate_groups([a, b])
    assert group.canonical.source is Source.EGM  # EGM has 8 counted decks, DuelFrontier 7
    assert group.others == (a,) and group.borrowed == ()


def test_a_tie_keeps_duelfrontier_and_borrows_nothing_when_both_are_readable() -> None:
    a, b = event_pair()
    (group,) = find_duplicate_groups([b, a])
    assert group.canonical.source is Source.DUELFRONTIER and group.others == (b,)


def test_unreadable_decks_in_the_kept_copy_are_filled_from_the_other() -> None:
    a, b = event_pair()
    # EGM keeps one more counted deck overall, but its player 3 list has an unreadable slot that DuelFrontier can read.
    bad = mk_deck(PLAYERS[2], (), 3, unresolved=("A:3|B:3",)).model_copy(update={"main": lists(8)[2]})
    b = b.model_copy(update={"decks": (*b.decks[:2], bad, *b.decks[3:])})
    extras = (mk_deck("Zed", lists(10)[8], 9), mk_deck("Yan", lists(10)[9], 10))
    b = b.model_copy(update={"decks": (*b.decks, *extras)})  # EGM now has 9 counted decks to DuelFrontier's 8, so EGM is kept
    (group,) = find_duplicate_groups([a, b])
    assert group.canonical.source is Source.EGM and group.borrowed == (PLAYERS[2],)
    filled = next(d for d in group.canonical.decks if d.player_name == PLAYERS[2])
    assert filled.counted and not filled.unresolved
    assert any("filled in 1 deck(s) from duelfrontier" in w for w in group.canonical.warnings)


def test_combined_events_counts_each_real_event_once() -> None:
    a, b = event_pair()
    lonely = mk_event(Source.EGM, "Some local", date(2026, 9, 1), [mk_deck("Q", lists(1)[0])])
    combined = combined_events([a, b, lonely])
    assert [e.name for e in combined] == ["Some local", "Regional Santiago 2026"]  # sorted by date; one copy of Santiago
    assert len(combined_events([a, lonely])) == 2  # nothing to merge: nothing changes


def test_each_event_is_used_in_at_most_one_group() -> None:
    a, b = event_pair()
    c = mk_event(Source.EGM, "Second EGM entry for the same event", date(2026, 10, 3), list(b.decks))
    groups = find_duplicate_groups([a, b, c])
    assert len(groups) == 1  # a pairs with one of them; the other stays on its own
    assert len(combined_events([a, b, c])) == 2
